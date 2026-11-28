#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_roms.py — 국립해양조사원 ROMS 수치예측모델(3 km, 조석 포함) 유향·유속 → 앱 '조류' 격자  [2026-10-08]

왜 (2026-10-08): 앱 지도 '조류' 색 바탕은 Open-Meteo 해류(MeteoFrance SMOC 0.08° ≈ 9 km)다. 부산 앞에서는
  대마난류(북동쪽 정상류)가 훨씬 세서 밀물·썰물로 방향이 뒤집히지 않는다(10/8 실측 비교: 태종대남측 흐름 20 cm/s 이상
  66시간 중 정반대 20시간). 국립해양조사원 ROMS 는 조석을 넣고 돌린 3 km 모델이라 연안 조류가 뒤집힌다.
  키(KHOA_KEY)는 깃허브 비밀값에만 있으므로 서버에서 받아 Pages 에 올리고, 앱은 키 없이 받는다.

API (data.go.kr 15142227, 활용가이드 v1.0 2025-03-14):
  GET https://apis.data.go.kr/1192136/roms/GetRomsApiService
      ?serviceKey&type=json&ymin&ymax&xmin&xmax&pageNo&numOfRows(≤300)[&include|exclude]
  → response.body.items.item[] {predcDt, lat, lot, crdir(유향 deg), crsp(유속 m/s), wtem(수온 ℃)}
  위도·경도 범위는 각각 최대 1° → 앱 범위(1.1° × 1.5°)는 2×2 타일로 나눠 받는다. 시간 필터가 없어 모든 예보 시각이 함께 온다.
  개발계정 하루 10,000회 — 실행마다 쓴 요청 수를 로그·meta.json 에 남긴다.

출력 (앱 kakao_map.html setCurrentField 와 **같은 꼴** — 받은 그대로 넘기면 된다):
  data/roms/current_busan.json
    {"minLat","maxLat","minLng","maxLng","rows","cols","t0"(UTC epoch 초),"n"(시간 수, 1시간 간격),
     "dLat","dLng","unit":"cm/s","dirConv":"toward","source", "spd":[…], "dir":[…]}
    점 순서 = row-major(row0 = 북쪽 maxLat, col0 = 서쪽 minLng), 각 점 안은 시간순 → spd[(r*cols+c)*n + k]
    spd = 유속 cm/s 정수, dir = **흘러가는 쪽** 도(0=북, 90=동), 육지·자료 없음 = -1
    (앱 디스크 사본 검사 hasPrefix('{"minLat"')·hasSuffix(']}') 와도 맞게 키 순서를 고정했다)
  data/roms/meta.json — 출처·예보 시작·시간 수·격자·요청 수·KHOA 조류예보 지점과의 대조(check)

모르는 것(실제 응답을 아직 못 봤다, 2026-10-08) — 가정과 확인 장치:
  · predcDt 시간대: KST 로 가정(바다누리 다른 API 와 같다). ROMS_TZ=UTC 로 바꿀 수 있다.
  · crdir 규칙: '가는 쪽'(해양 관례, KHOA 조류예보와 같음)으로 가정. ROMS_DIR=from 이면 180° 뒤집는다.
  · 유속 단위: 문서는 m/s. 값의 99백분위가 5 를 넘으면 cm/s 로 보고 그대로 쓴다(로그에 남김).
  · 격자: 위경도 정규 격자면 그대로, 아니면(곡선 격자) 원래 간격으로 다시 격자화한다.
  → 매 실행 KHOA 조류예보 지점(data/tides/crnt_*.json)과 같은 시각끼리 대조해 meta.check 에 판정을 적는다.
     ±12시간 시차 점수로 시간대가, 유향 일치/정반대 비율로 가는 쪽/오는 쪽이 드러난다.
  → (2026-10-08 검토 수정) 그 판정이 곧 게시 관문이다(gate): '⚠️ 가정이 틀림'이면 격자를 올리지 않고 작업을 실패로 알린다.
     '판정 보류'면 같은 가정으로 '맞음'을 받은 기록(meta.verified)이 있을 때만 올린다 — 첫 게시는 '맞음' 뒤에만.
     거부·보류 까닭은 meta.json 의 last_attempt 에 남는다(Pages 에서 보인다).

실패하면 이전 파일을 그대로 둔다(덮어쓰지 않음). 자료가 바뀌지 않았으면 파일을 다시 쓰지 않는다(빈 커밋 방지).
키는 출력하지 않는다(URL·예외 문자열도 가린다).
"""
import bisect
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

KEY = os.environ.get("KHOA_KEY", "").strip()
if not KEY:
    print("KHOA_KEY 없음 → ROMS 조류 격자 생성 건너뜀(기존 파일 유지).")
    sys.exit(0)

KST = timezone(timedelta(hours=9))
API = os.environ.get("ROMS_API", "https://apis.data.go.kr/1192136/roms/GetRomsApiService")
# 서울 중계(khoa-relay) — 2026-10-08 현재 허용 목록에 'roms' 가 없어 400 이 온다 → 그때는 이번 실행 내내 직접 호출.
#   (중계에 roms 를 넣으면 코드 수정 없이 중계를 타게 된다. 중계 재배포는 조팀장 승인 사항.)
RELAY = os.environ.get("KHOA_RELAY", "").strip()
RELAY_PATH = "roms/GetRomsApiService"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.environ.get("ROMS_OUT", os.path.join(ROOT, "data", "roms"))
TIDES_DIR = os.path.join(ROOT, "data", "tides")
OUT_GRID = os.path.join(OUT_DIR, "current_busan.json")
OUT_META = os.path.join(OUT_DIR, "meta.json")

BOX = (34.5, 35.6, 128.2, 129.7)                 # ymin, ymax, xmin, xmax — 앱 조류 격자 범위(CurrentFieldService)
TILE_MAX = 1.0                                   # 문서: 위도·경도 범위 각각 최대 1°
INCLUDE = "predcDt,lat,lot,crdir,crsp"           # 수온(wtem)은 빼서 응답을 줄인다(호출 수는 행 기준이라 그대로)
ROWS = 300                                       # 문서 상한
DAILY_LIMIT = 10000                              # 개발계정 1일 한도(이 API 하나 기준)
BUDGET = int(os.environ.get("ROMS_BUDGET", "3000"))        # 한 번 실행 최대 요청 — 하루 2번 돌아도 한도의 60%
TIME_BUDGET = int(os.environ.get("ROMS_TIME_BUDGET", "1500"))  # 초. 넘기면 새 요청을 멈추고(불완전 → 기존 파일 유지)
WORKERS = int(os.environ.get("ROMS_WORKERS", "6"))
TIMEOUT = float(os.environ.get("ROMS_TIMEOUT", "25"))
TZ_NAME = os.environ.get("ROMS_TZ", "KST").upper()          # predcDt 시간대 가정
DIR_CONV = os.environ.get("ROMS_DIR", "toward").lower()     # crdir 규칙 가정(toward=가는 쪽, from=오는 쪽)
MIN_COVER = 0.995                                # 타일별 고유 행 / totalCount — 이보다 적으면 불완전 → 덮어쓰지 않음(빈 칸이 시각마다 깜빡인다)
SOURCE = "국립해양조사원 ROMS(3km, 조석 포함)"
NATIONAL = (32.0, 39.0, 123.0, 132.0)            # 전국 범위 — 요청 수 '추정'만(받지는 않는다, 아래 national_estimate)

_t0 = time.time()
_lock = threading.Lock()
_calls = {"n": 0, "ok": 0, "fail": 0}
_state = {"stop": "", "relay": bool(RELAY), "include": True}
_secret_forms = [s for s in {KEY, urllib.parse.quote(KEY, safe=""), urllib.parse.unquote(KEY)} if s]

DENY_TEXT = ("SERVICE_KEY_IS_NOT_REGISTERED", "SERVICE_ACCESS_DENIED", "UNREGISTERED_IP", "DEADLINE_HAS_EXPIRED",
             "SERVICE_KEY_IS_NULL")
LIMIT_TEXT = ("LIMITED_NUMBER_OF_SERVICE_REQUESTS",)
DIR16 = ["북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동",
         "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"]


def mask(s) -> str:
    s = str(s)
    for f in _secret_forms:
        s = s.replace(f, "***")
    return s


def log(*a):
    print(mask(" ".join(str(x) for x in a)), flush=True)


def enc_key(k: str) -> str:
    return k if "%" in k else urllib.parse.quote(k, safe="")


def stop(reason: str):
    with _lock:
        if not _state["stop"]:
            _state["stop"] = reason
            log(f"⛔ {reason} → 새 요청 중단")


def _request(params: dict, via_relay: bool) -> urllib.request.Request:
    q = "serviceKey=" + enc_key(KEY) + "&" + urllib.parse.urlencode(params, safe=",")   # include=a,b — 쉼표 그대로
    if via_relay:
        return urllib.request.Request(RELAY + "?path=" + urllib.parse.quote(RELAY_PATH, safe="/") + "&" + q,
                                      headers={"User-Agent": "busan-wave/1.0", "x-region": "ap-northeast-2"})
    return urllib.request.Request(API + "?" + q, headers={"User-Agent": "busan-wave/1.0"})


def _classify_text(raw: str) -> str:
    for t in LIMIT_TEXT:
        if t in raw:
            return "limit"
    for t in DENY_TEXT:
        if t in raw:
            return "deny"
    return ""


def header_body(js):
    if not isinstance(js, dict):
        return {}, {}
    r = js.get("response", js)
    if not isinstance(r, dict):
        return {}, {}
    return (r.get("header") or {}), (r.get("body") or {})


def items_of(body) -> list:
    it = body.get("items") if isinstance(body, dict) else None
    if isinstance(it, dict):
        it = it.get("item", [])
    if isinstance(it, dict):
        it = [it]
    return it if isinstance(it, list) else []


def call(params: dict, label: str, tries: int = 3):
    """한 번 받기 → (header, body) 또는 None. 키 거절·한도는 실행 전체를 멈춘다(재시도해도 같다)."""
    attempt = -1
    relay_switched = False
    while attempt + 1 < tries or relay_switched:
        if relay_switched:
            relay_switched = False          # 중계 거절 직후 직접 호출 — 재시도 횟수를 깎지 않는다
        else:
            attempt += 1
        with _lock:
            if _state["stop"]:
                return None
            if _calls["n"] >= BUDGET:
                _state["stop"] = f"요청 예산 {BUDGET}회 도달"
                log(f"⛔ {_state['stop']}")
                return None
            if time.time() - _t0 > TIME_BUDGET:
                _state["stop"] = f"시간 예산 {TIME_BUDGET}s 도달"
                log(f"⛔ {_state['stop']}")
                return None
            _calls["n"] += 1
        via_relay = _state["relay"]       # 이 요청이 중계로 나갔나(다른 스레드가 그새 끌 수 있다)
        req = _request(params, via_relay)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read()[:600].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            if via_relay and e.code in (400, 404):
                # 중계가 roms 경로를 모른다(허용 목록 밖) — 직접 호출로 바꾸고 같은 요청을 바로 다시 보낸다
                with _lock:
                    if _state["relay"]:
                        log(f"중계 응답 {e.code}({mask(body[:40])}) → 이번 실행은 data.go.kr 직접 호출")
                    _state["relay"] = False
                relay_switched = True
                continue
            kind = _classify_text(body)
            if e.code in (401, 403) or kind:
                stop(f"[{label}] HTTP {e.code} {('일일 한도 초과' if kind == 'limit' else '키 거절/활용신청 확인')}: {mask(body[:160])}")
                return None
            with _lock:
                _calls["fail"] += 1
            log(f"[{label}] HTTP {e.code} (시도 {attempt + 1}/{tries})")
            time.sleep(2 * (attempt + 1))
            continue
        except Exception as e:  # noqa: BLE001 — 타임아웃·연결 실패
            with _lock:
                _calls["fail"] += 1
            log(f"[{label}] {type(e).__name__}: {mask(e)} (시도 {attempt + 1}/{tries})")
            time.sleep(3 * (attempt + 1))
            continue
        kind = _classify_text(raw[:600]) if raw.lstrip().startswith("<") or "OpenAPI_ServiceResponse" in raw[:200] else ""
        if kind:
            stop(f"[{label}] {'일일 한도 초과' if kind == 'limit' else '키 거절/활용신청 확인'}: {mask(raw[:160])}")
            return None
        try:
            js = json.loads(raw)
        except json.JSONDecodeError:
            with _lock:
                _calls["fail"] += 1
            log(f"[{label}] JSON 아님: {mask(raw[:160])} (시도 {attempt + 1}/{tries})")
            time.sleep(2 * (attempt + 1))
            continue
        hdr, body = header_body(js)
        rc = str(hdr.get("resultCode", "")).strip()
        if rc in ("20", "30", "31", "32"):
            stop(f"[{label}] 응답코드 {rc} {hdr.get('resultMsg', '')} — 키/활용신청 확인")
            return None
        if rc == "22":
            stop(f"[{label}] 응답코드 22 — 일일 한도({DAILY_LIMIT}) 초과")
            return None
        if rc == "10" and "include" in params and _state["include"]:
            # include 를 못 알아듣는 경우(문서와 다른 형식) — 이번 실행은 include 없이 받는다(호출 수는 같고 응답만 커진다)
            with _lock:
                if _state["include"]:
                    log(f"[{label}] 응답코드 10 — include 를 거절한 것으로 보고 끄고 다시")
                _state["include"] = False
            params = {k: v for k, v in params.items() if k != "include"}
            relay_switched = True          # 재시도 횟수를 깎지 않는다
            continue
        if rc in ("10", "11"):
            stop(f"[{label}] 응답코드 {rc} {hdr.get('resultMsg', '')} — 요청 매개변수 오류(코드 버그)")
            return None
        if rc not in ("", "0", "00", "03"):
            with _lock:
                _calls["fail"] += 1
            log(f"[{label}] 응답코드 {rc} {hdr.get('resultMsg', '')} (시도 {attempt + 1}/{tries})")
            time.sleep(2 * (attempt + 1))
            continue
        with _lock:
            _calls["ok"] += 1
        return hdr, body
    return None


def tiles(box) -> list:
    ymin, ymax, xmin, xmax = box
    ny = max(1, math.ceil((ymax - ymin) / TILE_MAX - 1e-9))
    nx = max(1, math.ceil((xmax - xmin) / TILE_MAX - 1e-9))
    dy, dx = (ymax - ymin) / ny, (xmax - xmin) / nx
    return [dict(ymin=round(ymin + i * dy, 4), ymax=round(ymin + (i + 1) * dy, 4),
                 xmin=round(xmin + j * dx, 4), xmax=round(xmin + (j + 1) * dx, 4))
            for i in range(ny) for j in range(nx)]


def page_params(t: dict, page: int, rows: int = ROWS) -> dict:
    p = dict(type="json", ymin=t["ymin"], ymax=t["ymax"], xmin=t["xmin"], xmax=t["xmax"], pageNo=page, numOfRows=rows)
    if _state["include"]:
        p["include"] = INCLUDE
    return p


NEED = ("predcDt", "lat", "lot", "crdir", "crsp")


def fetch_box(box) -> dict:
    """앱 범위를 타일로 나눠 모든 페이지를 받는다. 반환 {rows: [...], tiles: [...], complete: bool}."""
    ts = tiles(box)
    info, rows, jobs = [], [], []
    keys = [set() for _ in ts]          # 타일별 고유 (점,시각) — 쪽 순서가 흔들려 같은 행이 두 번 오면 '받은 행 수'로는 빈 곳을 못 본다

    def add(i, its):
        rows.extend(its)
        for it in its:
            if isinstance(it, dict):
                keys[i].add((it.get("lat"), it.get("lot"), it.get("predcDt")))
    # 1) 타일마다 1쪽(=totalCount 확인) — 순서대로. 첫 타일이 통째로 실패하면(러너에서 data.go.kr 불통) 바로 접는다.
    for i, t in enumerate(ts):
        r = call(page_params(t, 1), f"타일{i + 1} p1")
        if r is not None and _state["include"]:
            its = items_of(r[1])
            if its and not all(k in its[0] for k in NEED):
                # include 가 문서와 다르게 동작하면(필드가 빠짐) 이번 실행은 include 없이 받는다
                log(f"include 응답에 필드 부족 {sorted(its[0])} → include 끄고 다시")
                _state["include"] = False
                r = call(page_params(t, 1), f"타일{i + 1} p1 (include 없이)")
        if r is None:
            info.append({"tile": t, "total": None, "got": 0})
            if i == 0 or _state["stop"]:
                stop(_state["stop"] or "첫 타일 1쪽을 못 받음 — data.go.kr 응답 없음(러너 해외망 차단 가능)")
                return {"rows": [], "tiles": info, "complete": False}
            continue
        hdr, body = r
        try:
            total = int(body.get("totalCount") or 0)
        except (TypeError, ValueError):
            total = 0
        its = items_of(body)
        add(i, its)
        pages = math.ceil(total / ROWS) if total else 0
        info.append({"tile": t, "total": total, "pages": pages, "got": len(its)})
        jobs += [(i, p) for p in range(2, pages + 1)]
        log(f"타일{i + 1} {t['ymin']}–{t['ymax']}N {t['xmin']}–{t['xmax']}E: totalCount {total} → {pages}쪽")
    need = len(jobs) + len(ts)
    log(f"요청 예정 {need}회(지금까지 {_calls['n']}회, 실행 예산 {BUDGET}, 일일 한도 {DAILY_LIMIT})")
    if need > BUDGET:
        stop(f"필요 요청 {need}회가 실행 예산 {BUDGET}회를 넘음 — ROMS_BUDGET 확인")
        return {"rows": [], "tiles": info, "complete": False}

    # 2) 나머지 쪽 — 동시에. 실패한 쪽은 끝에 한 번 더(순서대로).
    def one(job):
        i, p = job
        r = call(page_params(ts[i], p), f"타일{i + 1} p{p}")
        return job, (items_of(r[1]) if r is not None else None)

    failed = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for (i, p), its in ex.map(one, jobs):
            if its is None:
                failed.append((i, p))
                continue
            add(i, its)
            info[i]["got"] += len(its)
    for job in failed:
        (i, p), its = one(job)
        if its is not None:
            add(i, its)
            info[i]["got"] += len(its)
    for i, t in enumerate(info):
        t["uniq"] = len(keys[i])
    return {"rows": rows, "tiles": info, "complete": not _state["stop"]}


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else x


def parse_dt(s):
    s = str(s or "").strip().split(".")[0]          # '2025-08-25 00:00:00.0' 같은 꼴도 받는다
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d%H"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(tzinfo=KST if TZ_NAME != "UTC" else timezone.utc)
        except ValueError:
            pass
    return None


def ingest(rows: list):
    """행 → {(lat,lon): {epoch: (crsp_raw, crdir_raw)}}. 겹친 타일 경계·중복 행은 하나로."""
    pts, bad, dup = {}, 0, 0
    raw_speeds = []
    for it in rows:
        if not isinstance(it, dict):
            bad += 1
            continue
        la, lo = fnum(it.get("lat")), fnum(it.get("lot"))
        dt = parse_dt(it.get("predcDt"))
        s, d = fnum(it.get("crsp")), fnum(it.get("crdir"))
        if la is None or lo is None or dt is None:
            bad += 1
            continue
        if not (BOX[0] - 1e-6 <= la <= BOX[1] + 1e-6 and BOX[2] - 1e-6 <= lo <= BOX[3] + 1e-6):
            continue
        key = (round(la, 5), round(lo, 5))
        e = int(dt.timestamp())
        ser = pts.setdefault(key, {})
        if e in ser:
            dup += 1
        # 채움값(음수·터무니없이 큰 값·360 넘는 각도)은 '자료 없음'
        if s is None or d is None or s < 0 or s > 1000 or d < 0 or d > 360:
            ser[e] = None
        else:
            ser[e] = (s, d)
            raw_speeds.append(s)
    return pts, bad, dup, raw_speeds


def pctl(vals, q):
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * (len(v) - 1)))]


def lattice_index(vals):
    """정렬된 좌표값 → (값→인덱스, 간격) 또는 None. 통째로 빠진 줄(전부 육지)은 건너뛴 인덱스로 둔다."""
    if len(vals) < 2:
        return None
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    step = sorted(diffs)[len(diffs) // 2]
    if step <= 1e-6:
        return None
    idx, k = {vals[0]: 0}, 0
    for v, d in zip(vals[1:], diffs):
        m = d / step
        if abs(m - round(m)) > 0.2 or round(m) < 1:      # 간격이 들쭉날쭉 → 정규 격자 아님
            return None
        k += int(round(m))
        idx[v] = k
    return idx, step, k + 1


def km(la1, lo1, la2, lo2):
    x = (lo2 - lo1) * 111.32 * math.cos(math.radians((la1 + la2) / 2))
    y = (la2 - la1) * 110.57
    return math.hypot(x, y)


def build_grid(pts: dict):
    """점들 → 정규 격자 (geo, cell{(r,c)->점 키}). row0 = 북."""
    keys = list(pts)
    lats = sorted({k[0] for k in keys})
    lons = sorted({k[1] for k in keys})
    li, ni = lattice_index(lats), lattice_index(lons)
    if li and ni and li[2] * ni[2] <= 8 * len(keys):
        (lat_ix, dlat, ny), (lon_ix, dlon, nx) = li, ni
        cell, coll = {}, 0
        for k in keys:
            rc = (ny - 1 - lat_ix[k[0]], lon_ix[k[1]])
            coll += rc in cell
            cell[rc] = k
        if coll <= 0.01 * len(keys):
            geo = dict(minLat=lats[0], maxLat=lats[-1], minLng=lons[0], maxLng=lons[-1], rows=ny, cols=nx,
                       dLat=round((lats[-1] - lats[0]) / max(1, ny - 1), 6), dLng=round((lons[-1] - lons[0]) / max(1, nx - 1), 6),
                       regular=True, native_step_km=round(km(lats[0], lons[0], lats[0] + dlat, lons[0]), 2))
            return geo, cell
        log(f"정규 격자로 보기엔 겹침 {coll}개 → 다시 격자화")
    # 곡선 격자 — 원래 간격(최근접 거리의 중앙값)으로 정규 격자를 새로 깔고, 0.75 간격 안의 가장 가까운 점을 쓴다
    sample = keys[:: max(1, len(keys) // 400)]
    nn = []
    for a in sample:
        best = min((km(a[0], a[1], b[0], b[1]) for b in keys if b != a), default=None)
        if best:
            nn.append(best)
    s_km = sorted(nn)[len(nn) // 2] if nn else 3.0
    mid = (lats[0] + lats[-1]) / 2
    dlat = s_km / 110.57
    dlon = s_km / (111.32 * math.cos(math.radians(mid)))
    ny = int((lats[-1] - lats[0]) / dlat) + 1
    nx = int((lons[-1] - lons[0]) / dlon) + 1
    bucket = {}
    for k in keys:
        bucket.setdefault((int((k[0] - lats[0]) / dlat), int((k[1] - lons[0]) / dlon)), []).append(k)
    cell = {}
    for r in range(ny):
        la = lats[0] + (ny - 1 - r) * dlat
        br = int((la - lats[0]) / dlat)
        for c in range(nx):
            lo = lons[0] + c * dlon
            bc = int((lo - lons[0]) / dlon)
            best, bd = None, 0.75 * s_km
            for i in (br - 1, br, br + 1):
                for j in (bc - 1, bc, bc + 1):
                    for k in bucket.get((i, j), ()):
                        d = km(la, lo, k[0], k[1])
                        if d <= bd:
                            best, bd = k, d
            if best:
                cell[(r, c)] = best
    geo = dict(minLat=round(lats[0], 5), maxLat=round(lats[0] + (ny - 1) * dlat, 5), minLng=round(lons[0], 5),
               maxLng=round(lons[0] + (nx - 1) * dlon, 5), rows=ny, cols=nx, dLat=round(dlat, 6), dLng=round(dlon, 6),
               regular=False, native_step_km=round(s_km, 2))
    return geo, cell


def to_cm_toward(s, d, speed_factor, flip):
    sc = s * speed_factor
    dd = (d + 180.0) % 360.0 if flip else d % 360.0
    return sc, dd


def hourly(ser_items, t0, n, step, speed_factor, flip):
    """한 점의 (epoch, 값) 정렬 목록 → n 시간 (spd cm/s 정수, dir 도 정수) 목록. 1시간보다 성기면 u·v 선형 보간."""
    ts = [e for e, _ in ser_items]
    out_s, out_d = [-1] * n, [-1] * n
    vals = {}
    for e, v in ser_items:
        if v is not None:
            vals[e] = to_cm_toward(v[0], v[1], speed_factor, flip)
    for k in range(n):
        e = t0 + 3600 * k
        v = vals.get(e)
        if v is None and step > 3600:
            j = bisect.bisect_left(ts, e)
            if 0 < j < len(ts):
                a, b = ts[j - 1], ts[j]
                va, vb = vals.get(a), vals.get(b)
                if va and vb and b - a <= step * 1.01:
                    w = (e - a) / (b - a)
                    ua, wa = va[0] * math.sin(math.radians(va[1])), va[0] * math.cos(math.radians(va[1]))
                    ub, wb = vb[0] * math.sin(math.radians(vb[1])), vb[0] * math.cos(math.radians(vb[1]))
                    u, vv = ua + (ub - ua) * w, wa + (wb - wa) * w
                    v = (math.hypot(u, vv), math.degrees(math.atan2(u, vv)) % 360.0)
        if v is not None:
            out_s[k] = int(round(v[0]))
            out_d[k] = int(round(v[1])) % 360
    return out_s, out_d


# ── KHOA 조류예보 지점과 대조 ─────────────────────────────────────────────────

def dir_deg(d):
    if isinstance(d, (int, float)):
        return float(d) % 360.0
    if isinstance(d, str) and d in DIR16:
        return DIR16.index(d) * 22.5
    return None


def adiff(a, b):
    x = abs(a - b) % 360.0
    return 360.0 - x if x > 180.0 else x


def load_stations():
    out = []
    try:
        names = sorted(f for f in os.listdir(TIDES_DIR) if f.startswith("crnt_") and f.endswith(".json"))
    except OSError:
        return out
    for f in names:
        try:
            with open(os.path.join(TIDES_DIR, f), encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        la, lo = fnum(doc.get("lat")), fnum(doc.get("lon"))
        if la is None or lo is None or not (BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]):
            continue
        ser = {}
        for day, evs in (doc.get("days") or {}).items():
            for ev in evs or []:
                try:
                    dt = datetime.strptime(f"{day} {ev['t']}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
                except (KeyError, ValueError):
                    continue
                s, d = fnum(ev.get("s")), dir_deg(ev.get("d"))
                if s is not None and d is not None:
                    ser[int(dt.timestamp())] = (s, d)
        if ser:
            out.append({"code": doc.get("code"), "name": doc.get("name"), "lat": la, "lon": lo, "ser": ser})
    return out


def compare(geo, spd, dvals, t0, n):
    """같은 시각끼리 ROMS 격자(가장 가까운 바다 칸) ↔ KHOA 조류예보 지점. 흐름 20 cm/s 이상인 시각만 유향 비교."""
    rows, cols = geo["rows"], geo["cols"]
    stations = load_stations()
    res, all_pairs = [], []
    for st in stations:
        best, bd = None, 6.0                                   # 6 km 안의 바다 칸만
        for r in range(rows):
            la = geo["maxLat"] - r * (geo["maxLat"] - geo["minLat"]) / max(1, rows - 1)
            if abs(la - st["lat"]) > 0.07:
                continue
            for c in range(cols):
                lo = geo["minLng"] + c * (geo["maxLng"] - geo["minLng"]) / max(1, cols - 1)
                if abs(lo - st["lon"]) > 0.08:
                    continue
                i = r * cols + c
                valid = sum(1 for k in range(n) if spd[i * n + k] >= 0)
                if valid < n * 0.5:
                    continue
                d = km(st["lat"], st["lon"], la, lo)
                if d < bd:
                    best, bd = i, d
        if best is None:
            res.append({"code": st["code"], "name": st["name"], "dist_km": None})
            continue
        pairs = []                                             # (lag 시간, ROMS s, ROMS d, KHOA s, KHOA d)
        for lag in range(-12, 13):
            for k in range(n):
                s1, d1 = spd[best * n + k], dvals[best * n + k]
                if s1 < 0:
                    continue
                kh = st["ser"].get(t0 + 3600 * k + 3600 * lag)
                if kh:
                    pairs.append((lag, s1, d1, kh[0], kh[1]))
        p0 = [p for p in pairs if p[0] == 0]
        strong = [p for p in p0 if p[1] >= 20 and p[3] >= 20]
        ratios = sorted(p[1] / p[3] for p in p0 if p[3] >= 20)
        row = {"code": st["code"], "name": st["name"], "dist_km": round(bd, 2), "n": len(p0), "n_strong": len(strong),
               "roms_max_cms": max((p[1] for p in p0), default=None), "khoa_max_cms": max((p[3] for p in p0), default=None),
               "speed_ratio_med": round(ratios[len(ratios) // 2], 2) if ratios else None}
        if strong:
            ad = [adiff(p[2], p[4]) for p in strong]
            row.update(agree45=sum(a <= 45 for a in ad), opposite135=sum(a >= 135 for a in ad),
                       dir_diff_med=round(sorted(ad)[len(ad) // 2]))
        res.append(row)
        all_pairs += pairs
    # 시차 점수: lag L = 'ROMS 격자 시각 e' 와 'KHOA e+L' 을 맞댐. 흐름 세기로 가중한 cos(유향 차) 평균(+1 같은 쪽, −1 정반대).
    #   predcDt 가 사실 UTC 인데 KST 로 읽었으면 ROMS 시각표가 9시간 이르게 붙어 L=+9 에서 최고가 된다.
    score = {}
    for lag in range(-12, 13):
        num = den = 0.0
        for p in all_pairs:
            if p[0] == lag and p[1] >= 20 and p[3] >= 20:
                w = min(p[1], p[3])
                num += w * math.cos(math.radians(p[2] - p[4]))
                den += w
        if den:
            score[lag] = round(num / den, 3)
    strong_all = [p for p in all_pairs if p[0] == 0 and p[1] >= 20 and p[3] >= 20]
    ad = [adiff(p[2], p[4]) for p in strong_all]
    rat = sorted(p[1] / p[3] for p in all_pairs if p[0] == 0 and p[3] >= 20)
    overall = {"stations": sum(1 for r in res if r.get("n")), "n_strong": len(strong_all),
               "agree45": sum(a <= 45 for a in ad), "opposite135": sum(a >= 135 for a in ad),
               "speed_ratio_med": round(rat[len(rat) // 2], 2) if rat else None}
    best_lag = max(score, key=lambda L: score[L]) if score else None
    s0 = score.get(0)
    # 가설 6개(유향 그대로/뒤집기 × 시차 0/+9/−9) 중 점수가 가장 높은 것. 뒤집으면 cos 부호만 바뀐다(−점수).
    # WHY 가설로 고르나 (2026-10-08 모의 시험): 유향을 거꾸로 읽으면 '최고 lag' 가 ±6시간으로 나온다 — 반일주조가 약 6.2시간마다
    #   뒤집히기 때문이다. 그래서 '최고 lag' 만 보면 반대 유향을 시차로 오판한다(모의 from 사례: 최고 lag −6h, lag0 −1.0).
    hyp = {}
    for L in (0, 9, -9):
        if L in score:
            hyp[("toward", L)] = score[L]
            hyp[("from", L)] = -score[L]
    best_h = max(hyp, key=lambda h: hyp[h]) if hyp else None
    # status(2026-10-08 검토 수정): 게시 판단(gate)이 글자(verdict)를 다시 읽지 않도록 판정을 따로 둔다 — ok 맞음 · wrong 가정이 틀림 · unsure 보류
    if len(strong_all) < 12 or s0 is None or best_h is None:
        status, verdict = "unsure", "판정 보류 — 같은 시각 대조 자료 부족"
    elif best_h == ("toward", 0) and s0 >= 0.3:
        status, verdict = "ok", f"맞음 — 유향 '가는 쪽'·시각 {TZ_NAME} 가정이 KHOA 조류예보와 맞는다(lag0 점수 {s0})"
    elif hyp[best_h] - s0 >= 0.3:
        conv, L = best_h
        what = []
        if conv == "from":
            what.append("유향이 반대(ROMS_DIR 확인)")
        if L:
            what.append(f"시각이 {L:+d}시간 어긋남(ROMS_TZ 확인)")
        status, verdict = "wrong", f"⚠️ {' + '.join(what)} — 그 가설 점수 {hyp[best_h]:.2f} vs 지금 가정 {s0}"
    else:
        status, verdict = "unsure", f"판정 보류 — 지금 가정 점수 {s0}, 최고 lag {best_lag:+d}h 점수 {score.get(best_lag)}"
    return {"stations": res, "overall": overall, "lag_score": score, "best_lag_h": best_lag,
            "best_hypothesis": {"dir": best_h[0], "lag_h": best_h[1], "score": round(hyp[best_h], 3)} if best_h else None,
            "status": status, "verdict": verdict}


def gate(check: dict, prev_meta: dict, now: datetime):
    """게시할까 — (결정, 까닭, 이번 뒤의 verified 기록). 결정 = "publish" | "reject-hard" | "reject-soft".  (2026-10-08 검토 수정)

    WHY: crdir 이 '가는 쪽'인지·predcDt 가 KST 인지는 문서에 없는 가정이다(위 '모르는 것'). 가정이 틀린 파일을 올리면
      앱은 dirConv:"toward"(우리가 늘 쓰는 값)만 보고 받아들이고, ROMS 면에서는 '연안 방향은 화살표를 보세요' 단서를 뺀 캡션을 띄운다
      → 약 3일 동안 색·흐름이 같은 화면의 KHOA 화살표와 정반대인데 경고도 없다. 지금의 CMEMS(단서 있음)보다 나쁘다.
      (모의 시험 r_from2·r_utc2·r_fromutc: '⚠️' 판정을 로그에만 적고 파일을 저장했다.)
    규칙:
      · wrong(다른 가설이 0.3 이상 낫다) → 거부(hard): 격자 안 씀 + 작업 실패로 알림 + 예전 '맞음' 기록도 취소(가정을 다시 확인할 때까지)
      · unsure(대조 자료 부족·애매) → 같은 가정(시간대·유향)으로 '맞음'을 받은 기록이 있으면 게시, 없으면 거부(soft).
        첫 게시는 '맞음' 확인 뒤에만 — 서버에 파일이 없으면 앱은 CMEMS+단서로 그대로 있으니 기다리는 쪽이 안전하다.
      · ok → 게시 + '맞음' 기록 갱신.
    """
    prev_v = (prev_meta or {}).get("verified")
    same_assumption = (isinstance(prev_v, dict) and prev_v.get("predcDt_tz") == TZ_NAME and prev_v.get("crdir") == DIR_CONV)
    st = check.get("status")
    if st == "ok":
        o = check.get("overall") or {}
        rec = {"at": now.isoformat(timespec="seconds"), "predcDt_tz": TZ_NAME, "crdir": DIR_CONV,
               "lag0_score": (check.get("lag_score") or {}).get(0), "n_strong": o.get("n_strong")}
        return "publish", check["verdict"], rec
    if st == "wrong":
        return "reject-hard", f"KHOA 대조가 지금 가정(시간대 {TZ_NAME}·유향 {DIR_CONV})을 부정 — {check['verdict']}", None
    if same_assumption:
        return "publish", f"{check['verdict']} — 같은 가정이 {prev_v.get('at')} '맞음' 확인됨 → 게시", prev_v
    return ("reject-soft", f"{check['verdict']} — 이 가정으로 '맞음' 확인된 적이 없어 첫 게시를 미룸(앱은 CMEMS 그대로)",
            prev_v if isinstance(prev_v, dict) else None)


def gh_output(**kv):
    """깃허브 작업 출력(steps.<id>.outputs.*) — 워크플로가 거부(hard)를 '실패'로 알릴 때 쓴다. 로컬에선 아무 일 없음."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in kv.items():
            f.write(f"{k}={str(v).replace(chr(10), ' ')}\n")


def national_estimate(prev_meta):
    """전국 범위를 받으면 몇 번 불러야 하나 — 타일마다 1행만 받아 totalCount 합. 7일에 한 번만."""
    ne = (prev_meta or {}).get("national_estimate") or {}
    try:
        if ne.get("at") and datetime.now(KST) - datetime.fromisoformat(ne["at"]) < timedelta(days=7):
            return ne, False
    except ValueError:
        pass
    if _state["stop"] or BUDGET - _calls["n"] < 120:
        return ne, False
    total, done, ts = 0, 0, tiles(NATIONAL)
    for i, t in enumerate(ts):
        r = call(page_params(t, 1, rows=1), f"전국{i + 1}", tries=2)
        if r is None:
            continue
        try:
            total += int(r[1].get("totalCount") or 0)
        except (TypeError, ValueError):
            pass
        done += 1
    if done < len(ts):
        log(f"전국 추정: {done}/{len(ts)} 타일만 응답 → 저장 안 함")
        return ne, False
    need = math.ceil(total / ROWS) + len(ts)
    ne = {"at": datetime.now(KST).isoformat(timespec="seconds"), "box": NATIONAL, "tiles": len(ts),
          "totalCount": total, "calls_per_run": need, "fits_daily_limit": need <= DAILY_LIMIT // 2}
    log(f"전국 추정: 행 {total:,} → 한 번에 {need:,}회 필요(일일 한도 {DAILY_LIMIT:,}) "
        f"→ {'받을 만함' if ne['fits_daily_limit'] else '한도에 비해 너무 많음 — 받지 않음'}")
    return ne, True


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def keep_previous(reason):
    log(f"⚠️ {reason} → 이전 파일 유지(덮어쓰지 않음). 요청 {_calls['n']}회 사용")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::ROMS 조류 격자 갱신 실패 — {mask(reason)} (이전 파일 유지)")
    sys.exit(0)


def main():
    now = datetime.now(KST)
    log(f"ROMS 조류 격자 — 범위 {BOX}, 시간대 가정 {TZ_NAME}, 유향 가정 {DIR_CONV}, 중계 {'시도' if RELAY else '없음'}")
    got = fetch_box(BOX)
    tinfo = got["tiles"]
    if not got["complete"]:
        keep_previous(f"받기 중단: {_state['stop']}")
    for t in tinfo:
        if t.get("total") is None:
            keep_previous(f"타일 {t['tile']} 응답 없음")
    total = sum(t["total"] or 0 for t in tinfo)
    pts, bad, dup, raw_speeds = ingest(got["rows"])
    uniq = sum(len(s) for s in pts.values())
    log(f"받은 행 {len(got['rows']):,} / totalCount {total:,} · 고유 (점,시각) {uniq:,} · 점 {len(pts):,} · 형식 오류 {bad} · 중복 {dup}")
    for t in tinfo:
        if t["total"] and t.get("uniq", 0) < MIN_COVER * t["total"]:
            keep_previous(f"타일 {t['tile']} 고유 행 {t.get('uniq', 0)}/{t['total']}(받은 행 {t['got']}) — 불완전")
    if not pts:
        keep_previous("자료 0점")

    # 유속 단위: 문서는 m/s. 99백분위가 5 를 넘으면 cm/s 로 본다(부산 앞 조류 최대 ≈ 1.5 m/s)
    p99 = pctl(raw_speeds, 0.99) or 0.0
    speed_factor = 1.0 if p99 > 5 else 100.0
    unit_in = "cm/s" if speed_factor == 1.0 else "m/s"
    flip = DIR_CONV == "from"

    epochs = sorted({e for s in pts.values() for e in s})
    deltas = Counter(b - a for a, b in zip(epochs, epochs[1:]) if b > a)
    step = deltas.most_common(1)[0][0] if deltas else 3600
    t0 = epochs[0] if epochs[0] % 3600 == 0 else epochs[0] + (3600 - epochs[0] % 3600)
    tN = epochs[-1] - epochs[-1] % 3600
    n = (tN - t0) // 3600 + 1
    if n < 24:
        keep_previous(f"예보 시간 {n}시간뿐(24시간 미만)")
    log(f"예보 시각 {len(epochs)}개 · 간격 {step // 60}분(최빈) · {datetime.fromtimestamp(t0, KST):%m-%d %H:%M} ~ "
        f"{datetime.fromtimestamp(tN, KST):%m-%d %H:%M} KST → 1시간 축 {n}개 · 유속 원단위 {unit_in}(99%={p99:.2f})")

    geo, cell = build_grid(pts)
    rows, cols = geo["rows"], geo["cols"]
    series, per_hour = {}, [0] * n
    for rc, k in cell.items():
        s_list, d_list = hourly(sorted(pts[k].items()), t0, n, step, speed_factor, flip)
        series[rc] = (s_list, d_list)
        for h, v in enumerate(s_list):
            if v >= 0:
                per_hour[h] += 1
    sea = len(cell)
    # 시간 축 다듬기 — 바다 칸 절반 이상에 값이 있는 시각만. WHY (2026-10-08): 문서끼리 예보 길이가 72·148시간·8일로 다르다.
    #   유향·유속이 72시간까지만 있고 시각은 8일치가 오면 뒤쪽이 통째로 빈다 → 그대로 두면 '채움 38%'로 실행 전체를 버리게 된다.
    good = [h for h, c in enumerate(per_hour) if c >= 0.5 * max(1, sea)]
    if not good:
        keep_previous(f"바다 칸 {sea} — 값이 있는 시각이 없음")
    k0, k1 = good[0], good[-1]
    if (k0, k1) != (0, n - 1):
        log(f"시간 축 다듬음: {n}시간 → {k1 - k0 + 1}시간(값 있는 구간 {datetime.fromtimestamp(t0 + 3600 * k0, KST):%m-%d %H시}"
            f" ~ {datetime.fromtimestamp(t0 + 3600 * k1, KST):%m-%d %H시} KST)")
    t0, n = t0 + 3600 * k0, k1 - k0 + 1
    if n < 24:
        keep_previous(f"값 있는 예보 {n}시간뿐(24시간 미만)")
    spd, dvals = [-1] * (rows * cols * n), [-1] * (rows * cols * n)
    valid = 0
    for (r, c), (s_list, d_list) in series.items():
        base = (r * cols + c) * n
        spd[base:base + n] = s_list[k0:k1 + 1]
        dvals[base:base + n] = d_list[k0:k1 + 1]
        valid += sum(1 for v in s_list[k0:k1 + 1] if v >= 0)
    fill = valid / max(1, sea * n)
    log(f"격자 {rows}×{cols}({'정규' if geo['regular'] else '곡선→재격자'}, 원간격 ≈{geo['native_step_km']} km) · "
        f"바다 칸 {sea} · {n}시간 · 값 채움 {fill:.1%}")
    if sea < 100 or fill < 0.8:
        keep_previous(f"바다 칸 {sea} / 채움 {fill:.0%} — 이상한 응답")

    check = compare(geo, spd, dvals, t0, n)
    log(f"KHOA 대조: {check['verdict']}")
    o = check["overall"]
    log(f"  지점 {o['stations']}곳 · 흐름 20cm/s↑ 같은 시각 {o['n_strong']}개 중 유향 45° 이내 {o['agree45']} · "
        f"정반대 {o['opposite135']} · 유속비(ROMS/KHOA) 중앙 {o['speed_ratio_med']} · lag 최고 {check['best_lag_h']}h")
    for s in check["stations"]:
        if s.get("n"):
            log(f"  {s['name']}({s['code']}) {s['dist_km']}km: 같은 시각 {s['n']} · 강 {s['n_strong']} · "
                f"45°내 {s.get('agree45')} · 정반대 {s.get('opposite135')} · 유속비 {s['speed_ratio_med']} · "
                f"최대 ROMS {s['roms_max_cms']} / KHOA {s['khoa_max_cms']} cm/s")

    prev_meta = load_json(OUT_META, {})
    decision, why, verified = gate(check, prev_meta, now)
    log(f"게시 판단: {decision} — {why}")
    if decision != "publish":
        # (2026-10-08 검토 수정) 격자는 쓰지 않는다(이전 파일·없으면 없음 그대로 — 앱은 CMEMS+단서). meta.json 에만 까닭을 남겨
        #   Pages(data/roms/meta.json)에서 왜 안 바뀌었는지 보이게 한다. 위쪽 필드(예보 시작·격자·check)는 '지금 게시된 격자'의 것 그대로 두고
        #   이번 시도는 last_attempt 에만 — 섞으면 meta 가 올라가 있지 않은 격자를 설명하게 된다.
        meta = dict(prev_meta) if isinstance(prev_meta, dict) and prev_meta else {
            "source": SOURCE, "api": "data.go.kr 15142227 해양수산부 국립해양조사원_ROMS 수치예측모델 조회",
            "license": "공공누리 제1유형(출처표시)"}
        if decision == "reject-hard" and isinstance(prev_meta.get("verified"), dict):
            meta["verified_revoked"] = {**prev_meta["verified"], "revoked_at": now.isoformat(timespec="seconds")}
        meta["verified"] = verified
        meta["last_attempt"] = {
            "at": now.isoformat(timespec="seconds"), "status": "rejected" if decision == "reject-hard" else "deferred",
            "reason": why, "forecast_start": datetime.fromtimestamp(t0, KST).isoformat(timespec="minutes"), "hours": n,
            "assumed": {"predcDt_tz": TZ_NAME, "crdir": DIR_CONV, "crsp_unit_in": unit_in, "crsp_p99_raw": round(p99, 3)},
            "requests": {"this_run": _calls["n"], "ok": _calls["ok"], "fail": _calls["fail"], "relay": _state["relay"]},
            "check": check}
        write_atomic(OUT_META, json.dumps(meta, ensure_ascii=False, indent=1))
        gh_output(publish=decision)
        if os.environ.get("GITHUB_ACTIONS"):
            lvl = "error" if decision == "reject-hard" else "warning"
            print(f"::{lvl}::ROMS 조류 격자 게시 {'거부' if decision == 'reject-hard' else '보류'} — {mask(why)}")
        log(f"⛔ 격자 게시 안 함({decision}) — {OUT_GRID} 그대로, meta.json 에 까닭 기록. 요청 {_calls['n']}회")
        return
    gh_output(publish="publish")
    ne, ne_new = national_estimate(prev_meta)

    doc = {"minLat": geo["minLat"], "maxLat": geo["maxLat"], "minLng": geo["minLng"], "maxLng": geo["maxLng"],
           "rows": rows, "cols": cols, "t0": t0, "n": n, "dLat": geo["dLat"], "dLng": geo["dLng"],
           "unit": "cm/s", "dirConv": "toward", "source": SOURCE, "spd": spd, "dir": dvals}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    prev = load_json(OUT_GRID, None)
    same = isinstance(prev, dict) and all(prev.get(k) == doc[k] for k in ("t0", "n", "rows", "cols", "spd", "dir"))
    meta = {
        "source": SOURCE,
        "api": "data.go.kr 15142227 해양수산부 국립해양조사원_ROMS 수치예측모델 조회",
        "license": "공공누리 제1유형(출처표시)",
        "generated": now.isoformat(timespec="seconds"),
        "changed": prev_meta.get("changed") if same else now.isoformat(timespec="seconds"),
        "forecast_start": datetime.fromtimestamp(t0, KST).isoformat(timespec="minutes"),
        "forecast_end": datetime.fromtimestamp(t0 + 3600 * (n - 1), KST).isoformat(timespec="minutes"),
        "native_first": datetime.fromtimestamp(epochs[0], KST).isoformat(timespec="minutes"),
        "native_last": datetime.fromtimestamp(epochs[-1], KST).isoformat(timespec="minutes"),
        "t0": t0, "hours": n, "native_step_min": step // 60, "native_times": len(epochs),
        "grid": {"rows": rows, "cols": cols, "dLat": geo["dLat"], "dLng": geo["dLng"], "regular": geo["regular"],
                 "native_step_km": geo["native_step_km"], "sea_cells": sea, "fill": round(fill, 4),
                 "bbox": [geo["minLat"], geo["maxLat"], geo["minLng"], geo["maxLng"]]},
        "assumed": {"predcDt_tz": TZ_NAME, "crdir": DIR_CONV, "crsp_unit_in": unit_in, "crsp_p99_raw": round(p99, 3)},
        "file": {"path": "data/roms/current_busan.json", "bytes": len(text.encode("utf-8"))},
        "requests": {"this_run": _calls["n"], "ok": _calls["ok"], "fail": _calls["fail"], "daily_limit": DAILY_LIMIT,
                     "relay": _state["relay"], "include": _state["include"], "rows_received": len(got["rows"]),
                     "totalCount": total, "tiles": len(tinfo)},
        "check": check,
        "verified": verified,                 # 이 가정으로 KHOA 대조 '맞음'을 받은 기록 — 다음 '판정 보류' 실행이 게시해도 되는 근거 (2026-10-08)
        "last_attempt": {"at": now.isoformat(timespec="seconds"), "status": "published", "reason": why},
        "national_estimate": ne,
    }
    # 같은 격자·같은 가정이 이미 게시돼 있으면 아무것도 안 쓴다(빈 커밋 방지). 직전 시도가 거부·보류였으면 meta 의 last_attempt 를 바로잡도록 쓴다.
    pv = prev_meta.get("verified") if isinstance(prev_meta.get("verified"), dict) else None
    v_same = pv is not None and (pv.get("predcDt_tz"), pv.get("crdir")) == (TZ_NAME, DIR_CONV)
    if same and not ne_new and v_same and (prev_meta.get("last_attempt") or {}).get("status") == "published":
        log(f"자료 변경 없음(t0·격자·값 동일) → 파일 그대로. 요청 {_calls['n']}회")
        return
    if not same:
        write_atomic(OUT_GRID, text)
    write_atomic(OUT_META, json.dumps(meta, ensure_ascii=False, indent=1))
    log(f"✅ {'저장' if not same else 'meta 만 갱신'}: {OUT_GRID} {len(text.encode('utf-8')) / 1024:.0f} KB · "
        f"{rows}×{cols}×{n}h · 요청 {_calls['n']}회(성공 {_calls['ok']}, 실패 {_calls['fail']}) · "
        f"{time.time() - _t0:.0f}s")


if __name__ == "__main__":
    main()
