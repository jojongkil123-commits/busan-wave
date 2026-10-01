#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tides.py — 전국 연안 물때(고·저조) + 부산권 조류예보 빌더  [2026-10-01]

국립해양조사원(KHOA) 신규 바다누리(공공데이터포털 1192136):
  · 조석예보(고저조) tideFcstHghLw  → data/tides/<obsCode>.json  (+ 하루 조차·물흐름 %)
  · 조류예보(시계열) crntFcstTime   → data/tides/crnt_<code>.json (활용신청이 안 돼 있으면 조용히 건너뜀)
  · 목록 data/tides/index.json
관측소: scripts/tide_stations.json (조위관측소 DT_ + 남해·동해·제주 조석예보지점 SO_)
조류예보지점: scripts/current_stations.json (부산·거제·통영·울산권)

왜 서버에서 받나 (2026-10-01 조팀장 "만조·간조·물때·조류가 다 부정확"):
  앱은 키가 있는 폰에서만 공식 조위를 받고, 나머지는 Open-Meteo 해수면(평균해면·격자 보간)으로 간조를 추정했다
  → 시각이 수십 분씩 틀렸다. 조류도 Open-Meteo '해류'(조류 아님)였다. 키는 서버(GitHub Actions 비밀값)에만 두고
  결과 JSON 을 올리면 모든 사용자가 공식 물때·조류를 본다.

증분 수집: 조석·조류 '예보'는 천문 계산값이라 한 번 받은 날은 바뀌지 않는다 → 빠진 날만 받는다.
  창 = 이번 달 1일 ~ 다음 달 말일(물흐름 % 는 같은 양력 달 안에서 정규화 — 바다타임 규칙, 185/185일 일치 확인).
  바다누리가 해외(깃허브 러너)에서 가끔 타임아웃 → 재시도 + 동시 4개 + 요청 예산(BUDGET).

물흐름 % (바다타임 역산 규칙): 하루 조차 R = 그날 00:00 ~ 다음 날 01:00 의 최고 고조 − 최저 저조,
  % = floor((R − 그 달 최소 R) / (그 달 최대 R − 그 달 최소 R) × 100).
"""
import os
import sys
import json
import time
import calendar
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

KEY = os.environ.get("KHOA_KEY", "").strip()
if not KEY:
    print("KHOA_KEY 없음 → 물때(전국) 생성 건너뜀.")
    sys.exit(0)

KST = timezone(timedelta(hours=9))
API_HL = "https://apis.data.go.kr/1192136/tideFcstHghLw/GetTideFcstHghLwApiService"
API_CR = "https://apis.data.go.kr/1192136/crntFcstTime/GetCrntFcstTimeApiService"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data", "tides")
BUDGET = int(os.environ.get("TIDE_BUDGET", "7000"))      # 한 번 실행 최대 요청(공공데이터 개발계정 1일 10,000회/API)
CR_DAYS = 17                                               # 조류: 어제 ~ +15일
WORKERS = 4

_lock = threading.Lock()
_used = {"hl": 0, "cr": 0}
_denied = {"hl": False, "cr": False}


def encode_key(k: str) -> str:
    return k if "%" in k else urllib.parse.quote(k, safe="")


def get(api: str, params: list):
    q = "&".join(["serviceKey=" + encode_key(KEY)] + [f"{k}={urllib.parse.quote(str(v))}" for k, v in params])
    req = urllib.request.Request(api + "?" + q, headers={"User-Agent": "busan-wave/1.0"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw[:300]}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):            # 키 거절·활용신청 없음 — 재시도해도 같다
                return {"resultCode": "30", "_http": e.code}
            last = e
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def result_code(js) -> str:
    """header.resultCode (문서상 위치가 가변) — 못 찾으면 ''."""
    if isinstance(js, dict):
        if "resultCode" in js:
            return str(js.get("resultCode"))
        for v in js.values():
            c = result_code(v)
            if c:
                return c
    if isinstance(js, list):
        for v in js:
            c = result_code(v)
            if c:
                return c
    raw = js.get("_raw", "") if isinstance(js, dict) else ""
    for code in ("SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "SERVICE ERROR", "LIMITED_NUMBER_OF_SERVICE_REQUESTS"):
        if code in raw:
            return code
    return ""


DENY_CODES = {"20", "30", "31", "32", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "SERVICE ERROR"}
LIMIT_CODES = {"22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS"}


def items(obj, key, out):
    if isinstance(obj, list):
        for v in obj:
            items(v, key, out)
    elif isinstance(obj, dict):
        if key in obj:
            out.append(obj)
        else:
            for v in obj.values():
                items(v, key, out)


def parse_hl(js, day: str) -> list:
    arr = []
    items(js, "predcDt", arr)
    ev = []
    for it in arr:
        dt = str(it.get("predcDt") or "")
        if len(dt) < 16 or dt[:10] != day:
            continue
        try:
            h = float(it.get("predcTdlvVl"))
        except (TypeError, ValueError):
            continue
        se = str(it.get("extrSe", ""))
        ev.append({"t": dt[11:16], "h": round(h), "k": "H" if se in ("1", "3") else "L"})
    ev.sort(key=lambda e: e["t"])
    return ev


def parse_cr(js, day: str) -> list:
    arr = []
    items(js, "crsp", arr)
    out = []
    for it in arr:
        dt = str(it.get("predcDt") or it.get("obsrvnDt") or "")
        if len(dt) < 16 or dt[:10] != day:
            continue
        try:
            s = float(it.get("crsp"))
        except (TypeError, ValueError):
            continue
        d = it.get("crdir")
        try:
            d = round(float(d))
        except (TypeError, ValueError):
            d = str(d) if d is not None else None
        out.append({"t": dt[11:16], "s": round(s), "d": d})    # s = cm/s
    out.sort(key=lambda e: e["t"])
    return out


def fetch(kind: str, code: str, day: str):
    """한 관측소·하루. 거절(활용신청 없음)·한도면 그 API 는 이번 실행에서 멈춘다."""
    with _lock:
        if _denied[kind] or sum(_used.values()) >= BUDGET:
            return None
        _used[kind] += 1
    api = API_HL if kind == "hl" else API_CR
    params = [("obsCode", code), ("reqDate", day.replace("-", "")), ("type", "json"), ("numOfRows", "300")]
    if kind == "cr":
        params.append(("min", "30"))
    try:
        js = get(api, params)
    except Exception as e:  # noqa: BLE001
        print(f"[{kind}] {code} {day} 실패: {e}", flush=True)
        return None
    rc = result_code(js)
    if rc in DENY_CODES or rc in LIMIT_CODES:
        with _lock:
            if not _denied[kind]:
                print(f"[{kind}] 응답코드 {rc} — {'활용신청/키 확인 필요' if rc in DENY_CODES else '일일 한도'} → 이번 실행에서 이 API 중단", flush=True)
            _denied[kind] = True
        return None
    return parse_hl(js, day) if kind == "hl" else parse_cr(js, day)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def month_window(today):
    first = today.replace(day=1)
    nm = (first + timedelta(days=32)).replace(day=1)
    last = nm.replace(day=calendar.monthrange(nm.year, nm.month)[1])
    return [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((last - first).days + 1)]


def flow_table(days: dict) -> dict:
    """하루 조차 R(cm) 와 물흐름 %(같은 양력 달 정규화) — 바다타임 규칙."""
    ds = sorted(days)
    R = {}
    for i, d in enumerate(ds):
        ev = list(days[d])
        nxt = days.get((datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d"), [])
        ev += [e for e in nxt if e["t"] <= "01:00"]
        hs = [e["h"] for e in ev if e["k"] == "H"]
        ls = [e["h"] for e in ev if e["k"] == "L"]
        if hs and ls:
            R[d] = max(hs) - min(ls)
    out = {}
    for d, r in R.items():
        month = [v for k, v in R.items() if k[:7] == d[:7]]
        lo, hi = min(month), max(month)
        p = int((r - lo) / (hi - lo) * 100) if hi > lo else 0
        out[d] = {"r": r, "p": max(0, min(100, p)), "full": len(month) >= 28}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(KST)
    today = now.date()
    hl_window = month_window(today)
    cr_window = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(-1, CR_DAYS - 1)]

    stations = load_json(os.path.join(HERE, "tide_stations.json"), [])
    cstations = load_json(os.path.join(HERE, "current_stations.json"), [])

    # ── 물때(고저조) ──
    docs = {}
    jobs = []
    for st in stations:
        old = load_json(os.path.join(OUT, f"{st['code']}.json"), {})
        days = {d: v for d, v in (old.get("days") or {}).items() if d in hl_window and v}
        docs[st["code"]] = (st, days)
        jobs += [("hl", st["code"], d) for d in hl_window if d not in days]
    # 가까운 날부터(오늘·앞으로 16일) 먼저 채운다 — 예산이 모자라도 쓸모 있는 날이 먼저
    order = {d: abs((datetime.strptime(d, "%Y-%m-%d").date() - today).days) + (0 if d >= str(today) else 40) for d in hl_window}
    jobs.sort(key=lambda j: order[j[2]])

    # ── 조류 ──
    cdocs = {}
    for st in cstations:
        old = load_json(os.path.join(OUT, f"crnt_{st['code']}.json"), {})
        days = {d: v for d, v in (old.get("days") or {}).items() if d in cr_window and v}
        cdocs[st["code"]] = (st, days)
        jobs += [("cr", st["code"], d) for d in cr_window if d not in days]

    print(f"요청 예정: 물때 {sum(1 for j in jobs if j[0]=='hl')} · 조류 {sum(1 for j in jobs if j[0]=='cr')} (예산 {BUDGET})", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda j: (j, fetch(*j)), jobs))
    for (kind, code, d), res in results:
        if not res:
            continue
        (docs if kind == "hl" else cdocs)[code][1][d] = res

    gen = now.isoformat(timespec="seconds")
    rows = []
    for code, (st, days) in docs.items():
        covered = sorted(days)
        if not covered:                       # 한 번도 못 받은 관측소는 파일·목록에서 뺀다(앱이 빈 파일을 고르지 않게)
            continue
        flows = flow_table(days)
        doc = {"code": code, "name": st["name"], "lat": st["lat"], "lon": st["lon"],
               "datum": "DL", "unit": "cm", "tz": "Asia/Seoul",
               "source": "국립해양조사원 조석예보(고저조)", "generated": gen,
               "days": {d: days[d] for d in covered}, "flow": flows}
        with open(os.path.join(OUT, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        rows.append({"code": code, "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                     "from": covered[0], "to": covered[-1]})
    crow = []
    for code, (st, days) in cdocs.items():
        covered = sorted(days)
        if not covered:
            continue
        doc = {"code": code, "name": st["name"], "lat": st["lat"], "lon": st["lon"], "unit": "cm/s",
               "tz": "Asia/Seoul", "source": "국립해양조사원 조류예보(시계열)", "generated": gen,
               "days": {d: days[d] for d in covered}}
        with open(os.path.join(OUT, f"crnt_{code}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        crow.append({"code": code, "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                     "from": covered[0], "to": covered[-1]})

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": gen, "datum": "DL", "source": "국립해양조사원(KHOA) 바다누리",
                   "stations": rows, "currents": crow}, f, ensure_ascii=False, separators=(",", ":"))
    ok = sum(1 for r in rows if r["to"] and r["to"] >= (today + timedelta(days=15)).strftime("%Y-%m-%d"))
    print(f"물때 관측소 {len(rows)}곳(16일 다 채운 곳 {ok}) · 조류 지점 {len(crow)}곳 · 요청 물때 {_used['hl']} 조류 {_used['cr']}"
          f"{' · 조류 API 거절(활용신청 필요)' if _denied['cr'] else ''}{' · 물때 API 거절' if _denied['hl'] else ''}")


if __name__ == "__main__":
    main()
