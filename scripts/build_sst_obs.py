#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_sst_obs.py — 국립해양조사원 실측 수온(조위관측소 DT_ + 해양관측부이 TW_) 최신값  [2026-10-01]

왜: 조팀장 "수온은 바다타임과 동일하게". 바다타임은 국립해양조사원(조위관측소·해양관측부이) +
    국립수산과학원 관측소 중 **가장 가까운 곳의 지금 실측값**을 보여준다(부산 = 국립해양조사원 부산 875m).
    앱은 국립수산과학원(키 불필요)만 써서 부산 시내 앞바다에서 11km 떨어진 다대포 값을 보여줬다.
    국립해양조사원 쪽은 키가 필요하므로 서버(깃허브 비밀값 KHOA_KEY)가 1시간마다 받아 data/sst_obs.json 으로 올린다.

  · 조위관측소 실측 수온  surveyWaterTemp (data.go.kr 15142506)
  · 해양관측부이 최신 관측 twRecent      (data.go.kr 15155516)
  해양관측부이 코드는 처음 한 번(그 뒤 7일마다) TW_0001~0120 을 훑어 data/sst_stations.json 에 적어 둔다.
  미국 러너에서 data.go.kr 가 막히는 날이 있어 서울 중계(KHOA_RELAY)를 먼저 쓴다(build_tides.py 와 같은 방식).
"""
import os
import sys
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

KEY = os.environ.get("KHOA_KEY", "").strip()
if not KEY:
    print("KHOA_KEY 없음 → 실측 수온 생성 건너뜀.")
    sys.exit(0)

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
OUT = os.path.join(DATA, "sst_obs.json")
STATIONS = os.path.join(DATA, "sst_stations.json")
RELAY = os.environ.get("KHOA_RELAY", "").strip()
_relay_ok = {"v": bool(RELAY)}
MAX_AGE_H = 3          # 이보다 오래된 관측은 버린다(센서 고장·점검)

API = {
    "DT": "https://apis.data.go.kr/1192136/surveyWaterTemp/GetSurveyWaterTempApiService",
    "TW": "https://apis.data.go.kr/1192136/twRecent/GetTWRecentApiService",
}

# 조위관측소(실측 수온 제공 확인분) — 앱 WaterTempService.stations 와 같은 목록
DT_STATIONS = [
    ("DT_0001", "인천", 37.45194, 126.59222), ("DT_0002", "평택", 36.96694, 126.82277),
    ("DT_0004", "제주", 33.52750, 126.54305), ("DT_0005", "부산", 35.09638, 129.03527),
    ("DT_0006", "묵호", 37.55027, 129.11638), ("DT_0007", "목포", 34.77972, 126.37555),
    ("DT_0008", "안산", 37.19222, 126.64722), ("DT_0010", "서귀포", 33.24000, 126.56166),
    ("DT_0011", "후포", 36.67750, 129.45305), ("DT_0012", "속초", 38.20722, 128.59416),
    ("DT_0013", "울릉도", 37.49138, 130.91361), ("DT_0014", "통영", 34.82777, 128.43472),
    ("DT_0016", "여수", 34.74722, 127.76555), ("DT_0017", "대산", 37.00750, 126.35277),
    ("DT_0018", "군산", 35.97555, 126.56305), ("DT_0020", "울산", 35.50194, 129.38722),
    ("DT_0021", "추자도", 33.96194, 126.30027), ("DT_0022", "성산포", 33.47472, 126.92777),
    ("DT_0023", "모슬포", 33.21444, 126.25111), ("DT_0025", "보령", 36.40638, 126.48611),
    ("DT_0026", "고흥발포", 34.48111, 127.34277), ("DT_0027", "완도", 34.31555, 126.75972),
    ("DT_0028", "진도", 34.37777, 126.30861), ("DT_0029", "거제도", 34.80138, 128.69916),
    ("DT_0031", "거문도", 34.02833, 127.30888), ("DT_0035", "흑산도", 34.68416, 125.43555),
    ("DT_0037", "어청도", 36.11722, 125.98472), ("DT_0091", "포항", 36.05177, 129.37627),
    ("DT_0094", "서거차도", 34.25142, 125.91544),
]


def encode_key(k: str) -> str:
    return k if "%" in k else urllib.parse.quote(k, safe="")


def get(kind: str, code: str, day: str):
    api = API[kind]
    q = "&".join(["serviceKey=" + encode_key(KEY)] + [f"{k}={urllib.parse.quote(str(v))}" for k, v in
                  [("obsCode", code), ("reqDate", day), ("min", "10"), ("numOfRows", "300"), ("type", "json")]])
    for attempt in range(2):
        if _relay_ok["v"]:
            path = api.split("/1192136/", 1)[1]
            req = urllib.request.Request(RELAY + "?path=" + urllib.parse.quote(path, safe="/") + "&" + q,
                                         headers={"User-Agent": "busan-wave/1.0", "x-region": "ap-northeast-2"})
        else:
            req = urllib.request.Request(api + "?" + q, headers={"User-Agent": "busan-wave/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None
            if _relay_ok["v"] and e.code in (400, 404):
                _relay_ok["v"] = False
                print(f"중계 응답 {e.code} → 직접 호출", flush=True)
                continue
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def items(js) -> list:
    out = []

    def walk(o):
        if isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, dict):
            if "obsrvnDt" in o:
                out.append(o)
            else:
                for v in o.values():
                    walk(v)
    walk(js)
    return out


def parse_dt(s: str):
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=KST)
        except (TypeError, ValueError):
            pass
    return None


def latest(kind: str, code: str, now: datetime):
    """그 관측소 오늘(자정 직후면 어제까지) 관측 중 가장 최근의 수온."""
    rows = []
    for day in ([now - timedelta(days=1), now] if now.hour < 1 else [now]):
        js = get(kind, code, day.strftime("%Y%m%d"))
        rows += items(js) if js else []
    best = None
    for r in rows:
        t = parse_dt(str(r.get("obsrvnDt") or ""))
        try:
            w = float(r.get("wtem"))
        except (TypeError, ValueError):
            continue
        if t is None or not (0.5 < w < 40):
            continue
        if best is None or t > best[0]:
            best = (t, w, r)
    if not best or now - best[0] > timedelta(hours=MAX_AGE_H):
        return None
    return best


def discover_tw(now: datetime) -> list:
    """해양관측부이 코드 훑기 — 응답에 좌표·수온이 오는 곳만."""
    found = []

    def one(n):
        code = f"TW_{n:04d}"
        b = latest("TW", code, now)
        if not b:
            return None
        r = b[2]
        try:
            lat, lon = float(r.get("lat")), float(r.get("lot"))
        except (TypeError, ValueError):
            return None
        return {"code": code, "name": str(r.get("obsvtrNm") or code), "lat": lat, "lon": lon}

    with ThreadPoolExecutor(max_workers=6) as ex:
        for s in ex.map(one, range(1, 121)):
            if s:
                found.append(s)
    return found


def main():
    now = datetime.now(KST)
    try:
        with open(STATIONS, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:  # noqa: BLE001
        st = {}
    fresh = st.get("discovered") and (now - datetime.fromisoformat(st["discovered"])) < timedelta(days=7)
    if not fresh:
        tw = discover_tw(now)
        if tw:
            st = {"discovered": now.isoformat(timespec="seconds"), "tw": tw}
            with open(STATIONS, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=0)
            print(f"해양관측부이 {len(tw)}곳 찾음", flush=True)
        else:
            print("해양관측부이 찾기 실패(키·활용신청·네트워크) — 이전 목록 유지", flush=True)
    tw_list = st.get("tw", [])

    jobs = [("DT", c, n, la, lo) for c, n, la, lo in DT_STATIONS] + \
           [("TW", s["code"], s["name"], s["lat"], s["lon"]) for s in tw_list]

    def run(j):
        kind, code, name, lat, lon = j
        b = latest(kind, code, now)
        if not b:
            return None
        return {"code": code, "name": name, "lat": lat, "lon": lon,
                "t": round(b[1], 1), "at": b[0].strftime("%Y-%m-%d %H:%M"), "src": "khoa"}

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = [r for r in ex.map(run, jobs) if r]

    if not res:
        print("실측 수온 0건 — 기존 파일 유지", flush=True)
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated": now.isoformat(timespec="seconds"), "source": "국립해양조사원 실측 수온",
                   "items": res}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"실측 수온 {len(res)}곳 (조위관측소 {sum(1 for r in res if r['code'].startswith('DT'))} · "
          f"해양관측부이 {sum(1 for r in res if r['code'].startswith('TW'))}) → data/sst_obs.json", flush=True)


if __name__ == "__main__":
    main()
