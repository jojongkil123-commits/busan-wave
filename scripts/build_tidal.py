#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tidal.py — 전국 조류(조석 성분만) 격자  [2026-10-09]
(2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)

출처 두 갈래 (TIDAL_SOURCE, 기본 auto) — (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) 검토 반영:
  ① cmems     = CMEMS SMOC 원파일의 utide·vtide(조석 유속)를 그대로 — 윈디 '조류'와 같은 변수. tidal_cmems.py 참고.
                Open-Meteo 호출 0, 실행 수 분, 시각(HH:30) 정확, 필터 새는 것 없음. numpy·h5py·requests 필요.
  ② openmeteo = 아래 설명한 처음 방식(Open-Meteo 합성 해류 − 저역통과). 시각 30분 밀림은 고쳤다(라벨 L 의 값 = 실제 L+30분 →
                출력 t 는 라벨 t−1·t 사이 3차 가운데 보간). 조석이 약한 동해에선 관성진동·바람이 조금 남는다(필터 한계) — 대체 경로로만 쓴다.
  auto = ①을 먼저, 실패하면(원파일 못 찾음·꼴 바뀜·받기 실패) ②로. 어느 쪽이었는지는 meta.json source_path 에 남긴다.

처음 방식(②)의 설명 — 왜 (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국):
  앱 지도 '조류' 색·입자는 부산 상자(34.5–35.6N, 128.2–129.7E)뿐이었다(ROMS 는 부산만, 깃허브 러너에서 막힘).
  조팀장 기준 화면은 윈디 '조류'(Tidal currents, 출처 CMEMS) — 전국 바다, 조석만(밀물·썰물로 방향이 뒤집힘), 약 2일.
  Open-Meteo 해류(ocean_current_velocity/direction)는 CMEMS SMOC 'utotal' = 해류(Eulerian) + 조석 + 스토크스 표류의 합이라
  부산 앞에서는 대마난류(북동 정상류)가 압도해 거의 안 뒤집힌다. 그래서 시간 저역통과(조석 주기를 지우는 필터)로 느린 성분을
  구해 빼고(조석 = 합성 − 저역통과) 조석만 남긴다 — 윈디의 '조석만' 레이어와 같은 생각이다.

API (Open-Meteo Marine — 앱 CurrentFieldService 와 같은 엔드포인트·변수·단위 km/h):
  GET https://marine-api.open-meteo.com/v1/marine?latitude=a,b,…&longitude=…&hourly=ocean_current_velocity,ocean_current_direction
      &models=meteofrance_currents&timeformat=unixtime&timezone=Asia/Seoul&past_days&forecast_days&cell_selection=nearest
  · models=meteofrance_currents 를 박아 둔다 — 2026-10-09 확인: 기본(best_match)과 192시간 값이 바이트까지 같다(앱이 쓰는 그것).
  · cell_selection=nearest — 육지 칸은 전부 null 이 온다 → 바다 마스크(sea_mask.json)를 배운다('sea' 는 옆 바다 값을 끌어와 마스크를 못 배운다).
  · 무료 한도: 분 600 · 시 5,000 · 일 10,000 '호출'이고 여러 지점 요청은 지점마다 1호출(변수 2개·8일이라 1배). 이 스크립트는
    분 MIN_CAP · 시(미끄러지는 60분) HOUR_CAP · 실행당 RUN_BUDGET 아래로 스스로 늦춘다. 쓴 호출 수는 로그·meta.json 에 남긴다.
  · 첫 실행(마스크 없음)은 7,081점 전부(시 한도 때문에 중간에 쉰다, 2026-10-09 실측 67분). 다음부터는 바다 칸 4,955점만(육지는 안 묻는다)
    — 그래도 시 상한(4,500)을 넘어 45묶음 뒤 약 48분 쉬었다가 마저 받는다(실행 ≈ 62분). 무료 시 한도 5,000 에 바짝 붙이지 않으려고 둔 여유다.

격자 위치 — 반 칸 보정 (2026-10-09 해안선 대조로 확인):
  Open-Meteo 는 SMOC 칸을 (j+0.5)/12° 에 라벨을 붙인다(칸 경계가 j/12 — 34.50 을 물으면 34.5417 과 34.4583 사이 동점).
  실제 해안선(korea_coast.json)과 맞대 보니 '그 라벨의 값 = CMEMS 격자점 j/12' 가설이 가장 잘 맞았다 — 다도해 216칸 육지/바다 일치
  0.903(라벨 그대로 0.861), 전국 7,081칸 brier 0.0200(라벨 그대로 0.0244)·전체 일치 0.971(0.966). 위도는 두 시험 모두 이 가설,
  경도는 전국 해안칸만 세면 '라벨 경도 그대로'가 0.766 vs 0.749 로 근소하게 앞서 ±1/24°(≈4 km) 불확실이 남는다(CMEMS 원격자가
  j/12 이므로 이 가설을 쓴다). → 계약 격자점 P(=j/12)는 'P + 1/24' 를 물어 받는다(칸 중심이라 동점 없음).
  받은 라벨이 물은 곳과 다르면(Open-Meteo 격자가 바뀜) 위치 가정이 깨진 것이라 이번 실행을 버린다.

출력 (앱과 고정 계약 — 2026-10-09):
  data/tidal/korea_tidal.json
    {"minLat":32.75,"maxLat":38.75,"minLng":124.0,"maxLng":132.0,"rows":73,"cols":97,"t0","n":96,
     "src":"cmems-smoc-tide","unit":"cm/s","dirConv":"toward","step":3600,"generated","filter","spd":[…],"dir":[…]}
    점 순서 = 앱 CurrentFieldService·지도 sampleFieldRaw 와 같다: row-major, row0 = 북(maxLat), col0 = 서(minLng),
      각 점 안은 시간순 → spd[(r*cols+c)*n + k]. t0 = 실행일(KST) 00:00 의 epoch 초, 1시간 간격 n 개.
    spd = 조석 성분 유속 cm/s 정수, dir = 조석 흐름이 **흘러가는 쪽** 도(0=북, 90=동), 육지·자료 없음 = -1(둘 다).
    키 순서 고정 — 앱 디스크 사본 검사(hasPrefix('{"minLat"')·hasSuffix(']}'))와 맞게 dir 이 마지막.
  data/tidal/meta.json — 출처·라이선스·격자·호출 수·필터·KHOA 대조·스펙트럼 점검·last_attempt
  data/tidal/sea_mask.json — 배운 바다 마스크(행 문자열 73줄, 북→남, '1' 바다 '0' 육지). 지우면 다음 실행이 전부 다시 묻는다.

필터 (TIDAL_FILTER, 기본 godin):
  godin = Godin 24-24-25 시간 이동평균(71시간, 가운데 맞춤) — 조석 분리의 표준 저역통과. M2·S2·K1·O1 통과율이 모두 0.1% 안팎이라
          일주조(K1·O1)까지 저역통과에 거의 안 샌다(→ 조석 성분에 고스란히 남는다). 앞뒤 35시간이 더 필요 → past_days=2·forecast_days=6.
  a25   = 가운데 맞춘 25시간 이동평균 — K1 4%·O1 3%·S2 4% 가 저역통과에 샌다(조석 성분이 그만큼 작아진다). past_days=1·forecast_days=5.
  둘 다 2~3일 주기 바람 성분 일부는 조석 쪽에 남는다(필터로는 못 가른다) — 그래서 KHOA 대조와 스펙트럼 점검을 매번 meta 에 남긴다.

검증 (매 실행, meta.json):
  · KHOA 조류예보 지점(data/tides/crnt_*.json, 부산권 29곳 — 'd' 16방위 가는 쪽, 's' cm/s)과 같은 시각끼리, KHOA 유속 ≥ 20 cm/s 인 시각에서
    합성(raw total)·조석 성분 각각: 유향 45° 이내 %, 정반대(>135°) %, 유속비 중앙값, 조석 성분의 시차 점수.
  · 표본 지점 몇 곳에서 조석 성분의 스펙트럼(반일주 띠 비중·우세 주기)·영점 교차 주기(≈12.4 h 기대)와, 저역통과 쪽에 반일주 신호가 안 남았는지.

실패하면(받기 중단·바다 칸 5% 넘게 빠짐·격자 가정 깨짐) korea_tidal.json 을 덮어쓰지 않는다 — meta.json 의 last_attempt 에만 까닭을 남기고
GITHUB_OUTPUT 에 publish=keep(또는 stale: 남은 옛 파일 예보도 끝남)을 쓴다. 키는 없다(무료 API).
"""
import gzip
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
API = os.environ.get("TIDAL_API", "https://marine-api.open-meteo.com/v1/marine")
MODEL = "meteofrance_currents"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.environ.get("TIDAL_OUT", os.path.join(ROOT, "data", "tidal"))
TIDES_DIR = os.path.join(ROOT, "data", "tides")
OUT_GRID = os.path.join(OUT_DIR, "korea_tidal.json")
OUT_META = os.path.join(OUT_DIR, "meta.json")
OUT_MASK = os.path.join(OUT_DIR, "sea_mask.json")

# 계약 격자 — SMOC 원격자(1/12°) 점에 맞춤 (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)
MIN_LAT, MAX_LAT, MIN_LNG, MAX_LNG = 32.75, 38.75, 124.0, 132.0
ROWS, COLS = 73, 97
D = 1.0 / 12.0
OM_SHIFT = 1.0 / 24.0          # 계약점 P 는 Open-Meteo 칸 'P + 1/24' 로 받는다(위 '격자 위치' 참고)
N_OUT = 96                     # 출력 시간 수(1시간 간격)
SRC = "cmems-smoc-tide"

SOURCE = os.environ.get("TIDAL_SOURCE", "auto").lower()       # auto | cmems | openmeteo (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)
FILTER = os.environ.get("TIDAL_FILTER", "godin").lower()
BATCH = int(os.environ.get("TIDAL_BATCH", "100"))              # 한 요청 지점 수(URL ≈ 2 KB, 응답 ≈ 250 KB)
MIN_CAP = int(os.environ.get("TIDAL_MIN_CAP", "480"))          # 미끄러지는 60초 상한(무료 600)
HOUR_CAP = int(os.environ.get("TIDAL_HOUR_CAP", "4500"))       # 미끄러지는 60분 상한(무료 5,000)
RUN_BUDGET = int(os.environ.get("TIDAL_BUDGET", "9000"))       # 한 실행 상한(무료 하루 10,000 — 하루 1번 실행)
TIME_BUDGET = int(os.environ.get("TIDAL_TIME_BUDGET", "5400"))  # 초. 받기(시 한도 쉬는 시간 포함)가 이보다 길면 멈추고 이전 파일 유지
TIMEOUT = float(os.environ.get("TIDAL_TIMEOUT", "60"))
MISSING_MAX = 0.05                                              # 바다 칸 중 빠진 비율 상한 — 넘으면 이전 파일 유지
RAW_SAVE = os.environ.get("TIDAL_RAW_SAVE", "")                 # 개발용: 받은 원자료를 이 경로에 저장(저장소 밖에 둘 것)
RAW_LOAD = os.environ.get("TIDAL_RAW_LOAD", "")                 # 개발용: 받지 않고 이 원자료로 처리만(호출 0)

DIR16 = ["북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동",
         "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"]

_t0 = time.time()
_calls = {"locations": 0, "requests": 0, "ok": 0, "fail": 0, "http429": 0, "waited_s": 0.0}
_win = deque()                 # (시각, 호출 수) — 미끄러지는 창
_peak = {"min": 0, "hour": 0}
_state = {"stop": ""}


def log(*a):
    print(" ".join(str(x) for x in a), flush=True)


def gh_output(**kv):
    """깃허브 작업 출력(steps.<id>.outputs.*). 로컬에선 아무 일 없음."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in kv.items():
            f.write(f"{k}={str(v).replace(chr(10), ' ')}\n")


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


# ── 격자 ────────────────────────────────────────────────────────────────────

def point_latlon(i):
    """계약 격자 i(row-major, row0=북) → (위도, 경도)"""
    r, c = divmod(i, COLS)
    return MAX_LAT - r * D, MIN_LNG + c * D


def req_latlon(i):
    la, lo = point_latlon(i)
    return round(la + OM_SHIFT, 5), round(lo + OM_SHIFT, 5)


def km(la1, lo1, la2, lo2):
    x = (lo2 - lo1) * 111.32 * math.cos(math.radians((la1 + la2) / 2))
    y = (la2 - la1) * 110.57
    return math.hypot(x, y)


def load_mask():
    m = load_json(OUT_MASK, None)
    if not isinstance(m, dict):
        return None
    rows = m.get("rows")
    g = m.get("grid") or {}
    if (not isinstance(rows, list) or len(rows) != ROWS or any(not isinstance(s, str) or len(s) != COLS for s in rows)
            or g.get("minLat") != MIN_LAT or g.get("maxLat") != MAX_LAT or g.get("minLng") != MIN_LNG
            or g.get("maxLng") != MAX_LNG or abs(float(m.get("om_shift", 0)) - OM_SHIFT) > 1e-6):
        log("⚠️ sea_mask.json 꼴·격자가 지금과 다름 → 무시하고 전부 묻는다")
        return None
    return [ch == "1" for s in rows for ch in s]


def save_mask(sea, now):
    rows = ["".join("1" if sea[r * COLS + c] else "0" for c in range(COLS)) for r in range(ROWS)]
    doc = {"note": "Open-Meteo SMOC(meteofrance_currents) 바다 칸 — '1' 바다 '0' 육지. 행 0 = 북(maxLat), 열 0 = 서(minLng). "
                   "cell_selection=nearest 에서 192시간 전부 null 이면 육지. 지우면 다음 실행이 전 격자를 다시 묻는다. "
                   "(2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)",
           "grid": {"minLat": MIN_LAT, "maxLat": MAX_LAT, "minLng": MIN_LNG, "maxLng": MAX_LNG, "rows": ROWS, "cols": COLS},
           "om_shift": round(OM_SHIFT, 6), "learned": now.isoformat(timespec="seconds"),
           "sea_count": sum(sea), "land_count": len(sea) - sum(sea), "rows": rows}
    write_atomic(OUT_MASK, json.dumps(doc, ensure_ascii=False, indent=0))


# ── 받기 (호출 수 조절) ─────────────────────────────────────────────────────

def _win_sum(now, span):
    return sum(w for t, w in _win if now - t < span)


def pace(w):
    """w 호출을 보내도 분·시 한도 안일 때까지 기다린다. 시간 예산을 넘기면 False."""
    while True:
        now = time.time()
        while _win and now - _win[0][0] >= 3600:
            _win.popleft()
        m, h = _win_sum(now, 60), _win_sum(now, 3600)
        if _calls["locations"] + w > RUN_BUDGET:
            _state["stop"] = f"실행 예산 {RUN_BUDGET}호출 도달"
            return False
        if m + w <= MIN_CAP and h + w <= HOUR_CAP:
            _win.append((now, w))
            _calls["locations"] += w
            _peak["min"] = max(_peak["min"], m + w)
            _peak["hour"] = max(_peak["hour"], h + w)
            return True
        # 가장 이른 '자리가 나는' 시각
        wait = 1.0
        if m + w > MIN_CAP:
            acc = m + w - MIN_CAP
            for t, ww in _win:
                if now - t < 60:
                    acc -= ww
                    if acc <= 0:
                        wait = max(wait, 60 - (now - t) + 0.5)
                        break
        if h + w > HOUR_CAP:
            acc = h + w - HOUR_CAP
            for t, ww in _win:
                acc -= ww
                if acc <= 0:
                    wait = max(wait, 3600 - (now - t) + 0.5)
                    break
        if time.time() - _t0 + wait > TIME_BUDGET:
            _state["stop"] = f"시간 예산 {TIME_BUDGET}s 안에 한도 자리가 안 남(필요 대기 {wait:.0f}s)"
            return False
        if wait > 30:
            log(f"  한도 대기 {wait:.0f}s (최근 60초 {m} · 60분 {h} 호출, 상한 {MIN_CAP}/{HOUR_CAP})")
        _calls["waited_s"] += wait
        time.sleep(wait)


def _url(idx):
    lats, lons = zip(*(req_latlon(i) for i in idx))
    q = {"latitude": ",".join(f"{v:.5f}" for v in lats), "longitude": ",".join(f"{v:.5f}" for v in lons),
         "hourly": "ocean_current_velocity,ocean_current_direction", "models": MODEL, "timeformat": "unixtime",
         "timezone": "Asia/Seoul", "past_days": str(PAST_DAYS), "forecast_days": str(FORECAST_DAYS),
         "cell_selection": "nearest"}
    return API + "?" + urllib.parse.urlencode(q, safe=",/")


def fetch_batch(idx):
    """한 묶음 → [(라벨위도, 라벨경도, times, vel, dir)] 또는 None. 429 는 종류별로 기다리거나 멈춘다.
    첫 시도의 호출 수는 부른 쪽(fetch_all)이 pace 로 이미 셌다 — 다시 보낼 때마다 여기서 다시 센다."""
    url = _url(idx)
    tries, waits429, first = 0, 0, True
    while tries < 4 and not _state["stop"]:
        # 다시 보내는 요청도 Open-Meteo 쪽에선 셌을 수 있다(타임아웃은 서버가 처리했을 수 있음) → 한도 창에 다시 넣는다
        if not first and not pace(len(idx)):
            return None
        first = False
        _calls["requests"] += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "busan-wave-tidal/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                js = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read()[:400].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            if e.code == 429:
                _calls["http429"] += 1
                waits429 += 1
                low = body.lower()
                if "daily" in low:
                    _state["stop"] = f"Open-Meteo 일일 한도 초과(429): {body[:120]}"
                    return None
                wait = 65 if "minutely" in low else 600
                if waits429 > 8 or time.time() - _t0 + wait > TIME_BUDGET:
                    _state["stop"] = f"429 가 계속됨({body[:120]})"
                    return None
                log(f"  429 {('분' if wait == 65 else '시')} 한도 — {wait}s 쉬고 다시: {body[:100]}")
                _calls["waited_s"] += wait
                time.sleep(wait)
                continue
            if e.code == 400:
                _state["stop"] = f"요청 매개변수 거절(400 — 코드/계약 확인): {body[:160]}"
                return None
            _calls["fail"] += 1
            tries += 1
            log(f"  HTTP {e.code} (시도 {tries}/4): {body[:100]}")
            time.sleep(5 * tries)
            continue
        except Exception as e:  # noqa: BLE001 — 타임아웃·연결 실패·JSON 깨짐
            _calls["fail"] += 1
            tries += 1
            log(f"  {type(e).__name__}: {str(e)[:100]} (시도 {tries}/4)")
            time.sleep(5 * tries)
            continue
        if isinstance(js, dict) and js.get("error"):
            _state["stop"] = f"Open-Meteo 오류 응답: {str(js.get('reason'))[:160]}"
            return None
        if isinstance(js, dict):
            js = [js]
        if not isinstance(js, list) or len(js) != len(idx):
            _calls["fail"] += 1
            tries += 1
            log(f"  응답 지점 수 {len(js) if isinstance(js, list) else '?'} ≠ {len(idx)} (시도 {tries}/4)")
            time.sleep(5 * tries)
            continue
        out = []
        for p in js:
            h = p.get("hourly") or {}
            out.append((p.get("latitude"), p.get("longitude"), h.get("time") or [],
                        h.get("ocean_current_velocity") or [], h.get("ocean_current_direction") or []))
        _calls["ok"] += 1
        return out
    return None


def fetch_all(todo):
    """todo 점들을 묶음으로 받는다 → {i: (vel, dir)}, times, 라벨 불일치 수, 실패 점 목록"""
    got, times, mism, failed = {}, None, 0, []
    batches = [todo[b:b + BATCH] for b in range(0, len(todo), BATCH)]
    log(f"받기: {len(todo):,}점 → {len(batches)}묶음 × ≤{BATCH} (분 ≤{MIN_CAP} · 60분 ≤{HOUR_CAP} · 실행 ≤{RUN_BUDGET} 호출)")
    for bi, idx in enumerate(batches):
        if _state["stop"] or not pace(len(idx)):
            failed += idx
            continue
        res = fetch_batch(idx)
        if res is None:
            failed += idx
            continue
        for i, (la, lo, ts, vs, ds) in zip(idx, res):
            rla, rlo = req_latlon(i)
            if la is None or lo is None or abs(la - rla) > 0.01 or abs(lo - rlo) > 0.01:
                mism += 1
            if times is None and ts:
                times = [int(t) for t in ts]
            if ts and times and (len(ts) != len(times) or int(ts[0]) != times[0]):
                failed.append(i)
                continue
            got[i] = (vs, ds)
        if (bi + 1) % 10 == 0 or bi + 1 == len(batches):
            log(f"  {bi + 1}/{len(batches)}묶음 · 호출 {_calls['locations']:,} · {time.time() - _t0:.0f}s")
    return got, times, mism, failed


# ── 조석 분리 ───────────────────────────────────────────────────────────────

def box(n):
    return [1.0 / n] * n


def conv(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def kernel(name):
    if name == "godin":          # A24·A24·A25 / (24²·25) — 71점, 가운데 35
        return conv(conv(box(24), box(24)), box(25)), "godin-24-24-25"
    if name == "a25":
        return box(25), "a25-centered"
    raise SystemExit(f"TIDAL_FILTER={name} 모름 (godin|a25)")


KER, FILTER_NAME = kernel(FILTER)
HALF = (len(KER) - 1) // 2
PAST_DAYS = max(1, math.ceil(HALF / 24))
FORECAST_DAYS = math.ceil((N_OUT + HALF + 1) / 24)   # +1 = HH:30 보정이 라벨 하나 더 뒤를 쓴다(2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)


def response(f_cph):
    """필터의 주파수 응답(실수, 대칭 커널) — meta 에 남기는 통과율"""
    return sum(w * math.cos(2 * math.pi * f_cph * (j - HALF)) for j, w in enumerate(KER))


def uv_series(vs, ds):
    """km/h·가는 쪽 → (u, v) cm/s 목록(없음 None)"""
    u, v = [], []
    for s, d in zip(vs, ds):
        if s is None or d is None:
            u.append(None)
            v.append(None)
            continue
        c = s / 3.6 * 100.0
        th = math.radians(d)
        u.append(c * math.sin(th))
        v.append(c * math.cos(th))
    return u, v


def lowpass_at(x, j):
    """x[j] 를 가운데로 한 저역통과 값. 커널 무게의 95% 이상이 있을 때만(아니면 None)"""
    a = j - HALF
    if a < 0 or j + HALF >= len(x):
        return None
    seg = x[a:j + HALF + 1]
    if None not in seg:
        return sum(map(float.__mul__, KER, seg))
    s = wsum = 0.0
    for w, val in zip(KER, seg):
        if val is not None:
            s += w * val
            wsum += w
    return s / wsum if wsum >= 0.95 else None


def tidal_split(u, v, j):
    """data 인덱스 j 의 (조석 u, 조석 v, 저역 u, 저역 v) — 하나라도 없으면 None"""
    if u[j] is None:
        return None
    lu, lv = lowpass_at(u, j), lowpass_at(v, j)
    if lu is None or lv is None:
        return None
    return u[j] - lu, v[j] - lv, lu, lv


def mid4(a, b, c, d):
    """네 점(1시간 간격) 가운데(b·c 사이 30분) 값 — 3차 라그랑주 (−a+9b+9c−d)/16. a·d 가 없으면 단순 평균 (b+c)/2.
    (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) M2 진폭 손실 0.15%(단순 평균은 3.2%)"""
    if a is None or d is None:
        return 0.5 * (b + c)
    return (-a + 9.0 * b + 9.0 * c - d) / 16.0


def tidal_hh00(u, v, j):
    """출력 시각 t(= 라벨 t 의 자리 j)의 조석 (u, v) — 시각 30분 밀림 보정 (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국).
    SMOC 원값 시각은 HH:30 인데 Open-Meteo 는 HH:00 으로 잘라 붙인다(원파일 time = 672960.5 h = 00:30Z, 대조 rms 0.023 vs 0.368 m/s).
    → 라벨 L 의 값 = 실제 L+30분. 실제 t 는 라벨 j−1(실제 t−30분)·j(실제 t+30분) 사이 → 라벨 j−2…j+1 로 가운데 보간."""
    b, c = tidal_split(u, v, j - 1), tidal_split(u, v, j)
    if b is None or c is None:
        return None
    a, d = tidal_split(u, v, j - 2), tidal_split(u, v, j + 1)
    if a is None or d is None:
        return mid4(None, b[0], c[0], None), mid4(None, b[1], c[1], None)
    return mid4(a[0], b[0], c[0], d[0]), mid4(a[1], b[1], c[1], d[1])


def spd_dir(u, v):
    return int(round(math.hypot(u, v))), int(round(math.degrees(math.atan2(u, v)))) % 360


# ── KHOA 조류예보 대조 ──────────────────────────────────────────────────────

def dir_deg(d):
    if isinstance(d, (int, float)):
        return float(d) % 360.0
    if isinstance(d, str) and d in DIR16:
        return DIR16.index(d) * 22.5
    return None


def adiff(a, b):
    x = abs(a - b) % 360.0
    return 360.0 - x if x > 180.0 else x


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else x


def load_stations():
    """build_roms.py load_stations 와 같은 해석 — 'd' 16방위(가는 쪽), 's' cm/s, 시각 KST"""
    out = []
    try:
        names = sorted(f for f in os.listdir(TIDES_DIR) if f.startswith("crnt_") and f.endswith(".json"))
    except OSError:
        return out
    for f in names:
        doc = load_json(os.path.join(TIDES_DIR, f), None)
        if not isinstance(doc, dict):
            continue
        la, lo = fnum(doc.get("lat")), fnum(doc.get("lon"))
        if la is None or lo is None or not (MIN_LAT <= la <= MAX_LAT and MIN_LNG <= lo <= MAX_LNG):
            continue
        ser = {}
        for day, evs in (doc.get("days") or {}).items():
            for ev in evs or []:
                try:
                    dt = datetime.strptime(f"{day} {ev['t']}", "%Y-%m-%d %H:%M").replace(tzinfo=KST)
                except (KeyError, ValueError, TypeError):
                    continue
                s, d = fnum(ev.get("s")), dir_deg(ev.get("d"))
                if s is not None and d is not None:
                    ser[int(dt.timestamp())] = (s, d)
        if ser:
            out.append({"code": doc.get("code"), "name": doc.get("name"), "lat": la, "lon": lo, "ser": ser})
    return out


def summarize(pairs):
    """pairs = [(모델 s, 모델 d, KHOA s, KHOA d)] → 비율들"""
    if not pairs:
        return {"n": 0}
    ad = [adiff(p[1], p[3]) for p in pairs]
    rat = sorted(p[0] / p[2] for p in pairs)
    n = len(pairs)
    return {"n": n, "agree45_pct": round(100 * sum(a <= 45 for a in ad) / n, 1),
            "opposite135_pct": round(100 * sum(a > 135 for a in ad) / n, 1),
            "dir_diff_med": round(sorted(ad)[n // 2]), "speed_ratio_med": round(rat[n // 2], 2)}


def compare(spd, dvals, raw_at, sea, t0, n):
    """같은 시각끼리 — 가장 가까운 바다 칸(15 km 안) ↔ KHOA 지점, KHOA 유속 ≥ 20 cm/s 인 시각만.
    합성(raw)·조석 성분을 **같은 시각 집합**으로 비교한다. 조석 성분은 ±6시간 시차 점수(유속 가중 cos)도.
    raw_at = None 이면(CMEMS 직접 — 합성은 안 받는다) 조석 성분만 (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)."""
    if raw_at is None:
        raw_at = lambda i, k: (0, 0)  # noqa: E731 — 조석 성분 표본을 줄이지 않게 '있음'으로 두고, raw 요약은 아래에서 뺀다
        no_raw = True
    else:
        no_raw = False
    stations = load_stations()
    res, all_raw, all_tid, lagp = [], [], [], []
    for st in stations:
        best, bd = None, 15.0
        for i in range(ROWS * COLS):
            if not sea[i]:
                continue
            la, lo = point_latlon(i)
            if abs(la - st["lat"]) > 0.15 or abs(lo - st["lon"]) > 0.2:
                continue
            if sum(1 for k in range(n) if spd[i * n + k] >= 0) < n * 0.5:
                continue
            d = km(st["lat"], st["lon"], la, lo)
            if d < bd:
                best, bd = i, d
        if best is None:
            res.append({"code": st["code"], "name": st["name"], "dist_km": None})
            continue
        pr, pt = [], []
        for k in range(n):
            kh = st["ser"].get(t0 + 3600 * k)
            ts, td = spd[best * n + k], dvals[best * n + k]
            rs, rd = raw_at(best, k)
            if kh and kh[0] >= 20 and ts >= 0 and rs >= 0:
                pt.append((ts, td, kh[0], kh[1]))
                pr.append((rs, rd, kh[0], kh[1]))
        for lag in range(-6, 7):
            for k in range(n):
                kh = st["ser"].get(t0 + 3600 * k + 3600 * lag)
                ts, td = spd[best * n + k], dvals[best * n + k]
                if kh and kh[0] >= 20 and ts >= 0:
                    lagp.append((lag, min(ts, kh[0]), math.cos(math.radians(td - kh[1]))))
        la, lo = point_latlon(best)
        if no_raw:
            pr = []
        res.append({"code": st["code"], "name": st["name"], "cell": [round(la, 4), round(lo, 4)], "dist_km": round(bd, 1),
                    "raw": summarize(pr), "tidal": summarize(pt)})
        all_raw += pr
        all_tid += pt
    score = {}
    for lag in range(-6, 7):
        num = den = 0.0
        for L, w, c in lagp:
            if L == lag:
                num += w * c
                den += w
        if den:
            score[lag] = round(num / den, 3)
    best_lag = max(score, key=lambda L: score[L]) if score else None
    return {"stations_total": len(stations), "stations_used": sum(1 for r in res if r.get("dist_km") is not None),
            "rule": "KHOA 유속 ≥ 20 cm/s 인 같은 시각(1시간 간격), 가장 가까운 바다 칸 15 km 안 — raw·tidal 같은 시각 집합",
            "raw_total": summarize(all_raw), "tidal": summarize(all_tid),
            "tidal_lag_score": score, "tidal_best_lag_h": best_lag, "stations": res}


# ── 스펙트럼·영점 교차 점검 ─────────────────────────────────────────────────

SAMPLES = [("서해 중부(태안 앞)", 36.5, 125.75), ("서해 남부(진도 앞)", 34.5, 125.75), ("제주해협", 33.75, 126.75),
           ("남해 동부(거제 앞)", 34.5, 128.75), ("경기만 바깥", 37.25, 126.0), ("동해 중부", 37.5, 130.0)]


def dft_bands(x):
    """평균 뺀 뒤 Hann 창 DFT 세기 — 띠별 비중(저 >36h · 일주 20–30h · 반일주 10.5–14.5h), 우세 주기(8–40h)"""
    n = len(x)
    m = sum(x) / n
    y = [(a - m) * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))) for i, a in enumerate(x)]
    pw = {}
    for f in range(1, n // 2 + 1):
        re = sum(a * math.cos(2 * math.pi * f * i / n) for i, a in enumerate(y))
        im = sum(a * math.sin(2 * math.pi * f * i / n) for i, a in enumerate(y))
        pw[n / f] = re * re + im * im
    tot = sum(pw.values()) or 1.0
    band = lambda lo, hi: sum(p for per, p in pw.items() if lo <= per <= hi) / tot  # noqa: E731
    dom = max((per for per in pw if 8 <= per <= 40), key=lambda per: pw[per], default=None)
    return {"semidiurnal": round(band(10.5, 14.5), 3), "diurnal": round(band(20, 30), 3),
            "low_gt36h": round(band(36.01, 1e9), 3), "dominant_period_h": round(dom, 1) if dom else None}, pw


def zero_cross_period(u, v):
    """주축(공분산 고유벡터)에 투영 → 부호 바뀜 간격의 평균 × 2 = 주기(시간)"""
    n = len(u)
    mu, mv = sum(u) / n, sum(v) / n
    a = sum((x - mu) ** 2 for x in u) / n
    b = sum((x - mu) * (y - mv) for x, y in zip(u, v)) / n
    c = sum((y - mv) ** 2 for y in v) / n
    th = 0.5 * math.atan2(2 * b, a - c)
    p = [(x - mu) * math.cos(th) + (y - mv) * math.sin(th) for x, y in zip(u, v)]
    zc = []
    for i in range(1, n):
        if p[i - 1] == 0 or (p[i - 1] < 0) != (p[i] < 0):
            frac = p[i - 1] / (p[i - 1] - p[i]) if p[i - 1] != p[i] else 0.0
            zc.append(i - 1 + frac)
    if len(zc) < 3:
        return None, len(zc)
    gaps = [b2 - a2 for a2, b2 in zip(zc, zc[1:])]
    return round(2 * sum(gaps) / len(gaps), 2), len(zc)


def spectral_check(series, sea, times):
    out = []
    for name, la, lo in SAMPLES:
        best, bd = None, 30.0
        for i in range(ROWS * COLS):
            if not sea[i] or i not in series:
                continue
            pla, plo = point_latlon(i)
            if abs(pla - la) > 0.3 or abs(plo - lo) > 0.3:
                continue
            d = km(la, lo, pla, plo)
            if d < bd:
                best, bd = i, d
        if best is None:
            out.append({"name": name, "cell": None})
            continue
        u, v = series[best]
        tu, tv, lu, lv, ru, rv = [], [], [], [], [], []
        for j in range(HALF, len(u) - HALF):
            s = tidal_split(u, v, j)
            if s is None:
                continue
            tu.append(s[0]); tv.append(s[1]); lu.append(s[2]); lv.append(s[3]); ru.append(u[j]); rv.append(v[j])
        if len(tu) < 48:
            out.append({"name": name, "cell": None, "why": "필터 구간 부족"})
            continue
        bt, _ = dft_bands(tu)
        bt_v, _ = dft_bands(tv)
        _, pw_raw_u = dft_bands(ru)
        _, pw_raw_v = dft_bands(rv)
        _, pw_lp_u = dft_bands(lu)
        _, pw_lp_v = dft_bands(lv)
        semi = lambda pw: sum(p for per, p in pw.items() if 10.5 <= per <= 14.5)  # noqa: E731
        raw_semi = semi(pw_raw_u) + semi(pw_raw_v)
        lp_semi = semi(pw_lp_u) + semi(pw_lp_v)
        per, ncross = zero_cross_period(tu, tv)
        pla, plo = point_latlon(best)
        sp = sorted(math.hypot(a, b) for a, b in zip(tu, tv))
        out.append({"name": name, "cell": [round(pla, 4), round(plo, 4)], "hours": len(tu),
                    "tidal_u_bands": bt, "tidal_v_bands": bt_v,
                    "zero_cross_period_h": per, "zero_crossings": ncross,
                    "lowpass_semidiurnal_vs_raw": round(lp_semi / raw_semi, 5) if raw_semi else None,
                    "tidal_speed_p50_p95_cms": [round(sp[len(sp) // 2]), round(sp[int(0.95 * (len(sp) - 1))])]})
    return out


# ── 마무리 ─────────────────────────────────────────────────────────────────

def finish_keep(reason, prev_meta, now, extra=None):
    """korea_tidal.json 은 그대로. meta.json 의 last_attempt 에만 까닭. 옛 파일 예보도 끝났으면 'stale'."""
    log(f"⚠️ {reason} → korea_tidal.json 그대로(덮어쓰지 않음). 호출 {_calls['locations']:,}")
    prev = load_json(OUT_GRID, None)
    stale = True
    if isinstance(prev, dict) and isinstance(prev.get("t0"), (int, float)) and isinstance(prev.get("n"), int):
        stale = prev["t0"] + 3600 * (prev["n"] - 1) < now.timestamp()
    meta = dict(prev_meta) if isinstance(prev_meta, dict) and prev_meta else {"src": SRC}
    meta["last_attempt"] = {"at": now.isoformat(timespec="seconds"), "status": "kept_previous", "reason": reason,
                            "previous_file_forecast_over": stale, "requests": dict(_calls, peak=_peak), **(extra or {})}
    write_atomic(OUT_META, json.dumps(meta, ensure_ascii=False, indent=1))
    flag = "stale" if stale else "keep"
    gh_output(publish=flag, reason=reason)
    if os.environ.get("GITHUB_ACTIONS"):
        lvl = "error" if stale else "warning"
        print(f"::{lvl}::전국 조류 격자 갱신 실패 — {reason} (이전 파일 유지{', 그 예보도 이미 끝남' if stale else ''})")
    sys.exit(0)


def t_day_kst(now):
    """실행일(KST) 00:00 의 epoch 초 — 계약 t0 기본"""
    return int(datetime(now.year, now.month, now.day, tzinfo=KST).timestamp())


GRID_META = {"minLat": MIN_LAT, "maxLat": MAX_LAT, "minLng": MIN_LNG, "maxLng": MAX_LNG, "rows": ROWS, "cols": COLS,
             "dDeg": round(D, 6),
             "order": "row-major, row0 = maxLat(북), col0 = minLng(서), 점 안은 시간순 → spd[(r*cols+c)*n+k] (앱 TidalFieldService·sampleFieldRaw 와 같음)"}


def write_outputs(now, prev_meta, t0, n, spd, dvals, filter_name, body):
    """계약 파일 + meta.json (두 출처 공통) — 키 순서 고정(앱 디스크 사본 검사: '{"minLat"' 로 시작, ']}' 로 끝).
    body = 출처별 meta(source·license·검증 …). (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)"""
    head = {"minLat": MIN_LAT, "maxLat": MAX_LAT, "minLng": MIN_LNG, "maxLng": MAX_LNG, "rows": ROWS, "cols": COLS,
            "t0": t0, "n": n, "src": SRC, "unit": "cm/s", "dirConv": "toward", "step": 3600,
            "generated": now.isoformat(timespec="seconds"), "filter": filter_name}
    text = (json.dumps(head, ensure_ascii=False, separators=(",", ":"))[:-1]
            + ',"spd":[' + ",".join(map(str, spd)) + '],"dir":[' + ",".join(map(str, dvals)) + "]}")
    prev = load_json(OUT_GRID, None)
    same = isinstance(prev, dict) and all(prev.get(k) == v for k, v in (("t0", t0), ("n", n), ("filter", filter_name),
                                                                        ("spd", spd), ("dir", dvals)))
    raw_bytes = len(text.encode("utf-8"))
    gz_bytes = len(gzip.compress(text.encode("utf-8"), 9))
    body = dict(body)
    grid = dict(GRID_META, **body.pop("grid_extra", {}))
    meta = {"src": SRC, **body,
            "generated": now.isoformat(timespec="seconds"),
            "changed": prev_meta.get("changed") if same and prev_meta.get("changed") else now.isoformat(timespec="seconds"),
            "t0": t0, "n": n, "step": 3600,
            "forecast_start": datetime.fromtimestamp(t0, KST).isoformat(timespec="minutes"),
            "forecast_end": datetime.fromtimestamp(t0 + 3600 * (n - 1), KST).isoformat(timespec="minutes"),
            "grid": grid,
            "file": {"path": "data/tidal/korea_tidal.json", "bytes": raw_bytes, "gzip9_bytes": gz_bytes},
            "last_attempt": {"at": now.isoformat(timespec="seconds"), "status": "published" if not same else "unchanged",
                             "source_path": body.get("source_path")}}
    if not same:
        write_atomic(OUT_GRID, text)
    write_atomic(OUT_META, json.dumps(meta, ensure_ascii=False, indent=1))
    gh_output(publish="publish" if not same else "unchanged")
    log(f"✅ {'저장' if not same else '자료 같음 — meta 만'}: {OUT_GRID} {raw_bytes / 1024:.0f} KB (gzip -9 {gz_bytes / 1024:.0f} KB) · "
        f"{ROWS}×{COLS}×{n}h · 출처 {body.get('source_path')} · {time.time() - _t0:.0f}s")


def log_check(check):
    rt, tt = check["raw_total"], check["tidal"]
    log(f"KHOA 대조({check['stations_used']}/{check['stations_total']}곳, {check['rule']}):")
    if rt.get("n"):
        log(f"  합성(raw)  n={rt.get('n')} · 45°내 {rt.get('agree45_pct')}% · 정반대 {rt.get('opposite135_pct')}% · 유속비 중앙 {rt.get('speed_ratio_med')}")
    log(f"  조석 성분  n={tt.get('n')} · 45°내 {tt.get('agree45_pct')}% · 정반대 {tt.get('opposite135_pct')}% · 유속비 중앙 {tt.get('speed_ratio_med')}"
        f" · 시차 최고 {check['tidal_best_lag_h']}h (점수 {check['tidal_lag_score'].get(check['tidal_best_lag_h'])}, lag0 {check['tidal_lag_score'].get(0)})")


# ── 출처 ① CMEMS 원파일 utide·vtide (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) ─────────────────────────

REGIONS = [("서해", lambda la, lo: lo < 126.6 and la > 34.6), ("남해", lambda la, lo: 33.9 < la < 34.8 and 126.3 < lo < 128.6),
           ("부산·대한해협", lambda la, lo: 34.3 < la < 35.6 and 128.4 < lo < 129.8), ("동해", lambda la, lo: lo > 129.6 and la > 35.6)]


def grid_checks(tu, tv, sea, n):
    """CMEMS 경로 점검 — 표본 지점 스펙트럼·영점 교차 주기, 해역별 유속 중앙값(동해가 1 cm/s 안팎이면 '조석만'이 맞다)"""
    spec = []
    for name, la, lo in SAMPLES:
        best, bd = None, 30.0
        for i in range(ROWS * COLS):
            if not sea[i]:
                continue
            pla, plo = point_latlon(i)
            if abs(pla - la) > 0.3 or abs(plo - lo) > 0.3:
                continue
            d = km(la, lo, pla, plo)
            if d < bd:
                best, bd = i, d
        if best is None:
            spec.append({"name": name, "cell": None})
            continue
        r, c = divmod(best, COLS)
        u = [float(x) for x in tu[r, c, :]]
        v = [float(x) for x in tv[r, c, :]]
        if any(math.isnan(x) for x in u + v):
            spec.append({"name": name, "cell": None, "why": "빈 시각"})
            continue
        bu, _ = dft_bands(u)
        bv, _ = dft_bands(v)
        per, ncross = zero_cross_period(u, v)
        sp = sorted(math.hypot(a, b) for a, b in zip(u, v))
        pla, plo = point_latlon(best)
        spec.append({"name": name, "cell": [round(pla, 4), round(plo, 4)], "hours": n, "tidal_u_bands": bu, "tidal_v_bands": bv,
                     "zero_cross_period_h": per, "zero_crossings": ncross,
                     "tidal_speed_p50_p95_cms": [round(sp[len(sp) // 2]), round(sp[int(0.95 * (len(sp) - 1))])]})
    regions = {}
    for rn, f in REGIONS:
        vals = []
        for i in range(ROWS * COLS):
            if not sea[i]:
                continue
            la, lo = point_latlon(i)
            if not f(la, lo):
                continue
            r, c = divmod(i, COLS)
            vals += [math.hypot(a, b) for a, b in zip(tu[r, c, :], tv[r, c, :]) if not (math.isnan(a) or math.isnan(b))]
        vals.sort()
        regions[rn] = {"cells_hours": len(vals), "p50_cms": round(vals[len(vals) // 2], 1) if vals else None,
                       "p95_cms": round(vals[int(0.95 * (len(vals) - 1))], 1) if vals else None}
    return spec, regions


def run_cmems(now, prev_meta):
    """CMEMS 원파일 → 계약 파일. 실패는 예외로 알린다(부른 쪽이 auto 면 Open-Meteo 로 넘어간다)"""
    import tidal_cmems  # numpy·h5py·requests — Open-Meteo 경로는 이것들 없이도 돈다
    t0, n = t_day_kst(now), N_OUT
    log(f"전국 조류(CMEMS utide·vtide 직접) — 격자 {ROWS}×{COLS} {MIN_LAT}–{MAX_LAT}N {MIN_LNG}–{MAX_LNG}E, "
        f"{datetime.fromtimestamp(t0, KST):%m-%d %H:%M} KST 부터 {n}시간")
    box = (MIN_LAT, MAX_LAT, MIN_LNG, MAX_LNG, ROWS, COLS)
    # (2026-10-09) 조팀장 무료 계정 생김 → 공식 도구(로그인)로 받는다. 원파일 직접 읽기(로그인 없음)는 TIDAL_SOURCE=cmems-native 일 때만.
    native = SOURCE == "cmems-native"
    res = tidal_cmems.build(t0, n, box) if native else tidal_cmems.build_toolbox(t0, n, box)
    spd, dvals, sea = res["spd"], res["dir"], res["sea"]
    sea_n = sum(sea)
    if not 3000 <= sea_n <= 6500:
        raise RuntimeError(f"바다 칸 {sea_n} — 상자 {ROWS}×{COLS} 에 이상한 수(Open-Meteo 마스크 4,955)")
    hole = sum(1 for i in range(ROWS * COLS) if sea[i] for k in range(n) if spd[i * n + k] < 0)
    if hole > MISSING_MAX * sea_n * n:
        raise RuntimeError(f"바다 칸·시각 {hole}개 빔({hole / (sea_n * n):.1%})")
    top = max(spd)
    if top > 600:
        raise RuntimeError(f"유속 {top} cm/s — 깨진 값")
    for i in range(ROWS * COLS):          # 육지·빈칸 규약: 둘 다 -1
        if not sea[i]:
            for k in range(n):
                spd[i * n + k] = dvals[i * n + k] = -1
    info = res["info"]
    if native:
        log(f"바다 칸 {sea_n:,} / {ROWS * COLS:,} · 빈 칸·시각 {hole} · 최대 {top} cm/s · R{info['bulletin_R']} · "
            f"조각 {info['chunks']}개 {info['chunk_bytes'] / 1e6:.0f} MB · {info['total_s']:.0f}s")
    else:
        log(f"바다 칸 {sea_n:,} / {ROWS * COLS:,} · 빈 칸·시각 {hole} · 최대 {top} cm/s · {info['via']} · {info['total_s']:.0f}s")
    check = compare(spd, dvals, None, sea, t0, n)
    log_check(check)
    spec, regions = grid_checks(res["tu"], res["tv"], sea, n)
    for s in spec:
        if s.get("cell"):
            log(f"  스펙트럼 {s['name']} {s['cell']}: 조석 u 반일주 {s['tidal_u_bands']['semidiurnal']:.0%}·일주 "
                f"{s['tidal_u_bands']['diurnal']:.0%} 우세 {s['tidal_u_bands']['dominant_period_h']}h · 영점교차 주기 {s['zero_cross_period_h']}h · "
                f"유속 p50/p95 {s['tidal_speed_p50_p95_cms']} cm/s")
    log("  해역별 유속 중앙값(cm/s): " + " · ".join(f"{k} {v['p50_cms']}" for k, v in regions.items()))
    body = {
        "source_path": "cmems-native" if native else "cmems",
        "source": ("CMEMS SMOC(GLOBAL_ANALYSISFORECAST_PHY_001_024, merged-uv 1시간) 원파일의 utide·vtide(조석 유속) 그대로 — "
                   "윈디 '조류(Tidal currents)'와 같은 변수. 원값 시각 HH:30 → HH:00 3차 가운데 보간") if native else
                  ("CMEMS SMOC(GLOBAL_ANALYSISFORECAST_PHY_001_024, merged-uv 1시간)의 utide·vtide(조석 유속) 그대로 — "
                   "윈디 '조류(Tidal currents)'와 같은 변수. 공식 도구(copernicusmarine, 로그인)로 받아 그 시각 표기 그대로"),
        "license": "E.U. Copernicus Marine Service Information — 무료·상업 사용 가능, 출처 표시 필수('Generated using E.U. Copernicus Marine "
                   "Service Information'). 조팀장 무료 계정(2026-10-09 가입)으로 로그인해 받는다(비밀값 CMEMS_USERNAME/CMEMS_PASSWORD)",
        "attribution": "Copernicus Marine Service (SMOC)",
        "cmems": info,
        "validation": check,
        "spectral_check": spec,
        "region_speed": regions,
        "points": {"sea": sea_n, "land": ROWS * COLS - sea_n, "empty_sea_hours": hole, "mask": "CMEMS 원파일 육지(채움값)"},
    }
    write_outputs(now, prev_meta, t0, n, spd, dvals, "none-cmems-utide-hh30mid" if native else "none-cmems-utide-arco", body)


# ── 출처 ② Open-Meteo 합성 − 저역통과 (대체 경로) ─────────────────────────────

def run_openmeteo(now, prev_meta, cmems_fail=None):
    mask = load_mask()
    all_idx = list(range(ROWS * COLS))
    todo = [i for i in all_idx if mask[i]] if mask else all_idx
    log(f"전국 조류(Open-Meteo 합성 − 저역통과) — 격자 {ROWS}×{COLS} {MIN_LAT}–{MAX_LAT}N {MIN_LNG}–{MAX_LNG}E, 필터 {FILTER_NAME}"
        f"(±{HALF}h) → past_days={PAST_DAYS}, forecast_days={FORECAST_DAYS}, 마스크 {'있음' if mask else '없음(전부 묻는다)'}")

    if RAW_LOAD:
        raw = load_json(RAW_LOAD, None)
        if not isinstance(raw, dict) or raw.get("past_days") != PAST_DAYS or raw.get("forecast_days") != FORECAST_DAYS:
            # 원자료가 더 길면(godin 용으로 받은 것을 a25 로) 그대로 쓴다 — 필터 구간만 맞으면 된다
            if not (isinstance(raw, dict) and raw.get("past_days", 0) >= PAST_DAYS and raw.get("forecast_days", 0) >= FORECAST_DAYS):
                raise SystemExit("TIDAL_RAW_LOAD 원자료의 past/forecast_days 가 이 필터에 모자람")
        times = raw["times"]
        got = {int(k): (v[0], v[1]) for k, v in raw["pts"].items()}
        mism, failed = raw.get("mismatch", 0), [int(x) for x in raw.get("failed", [])]
        _calls.update(raw.get("calls", {}))
        _peak.update(raw.get("peak", {}))
        _state["fetched"] = raw.get("fetched")
        log(f"원자료 읽음({RAW_LOAD}) — 호출 0(받을 때 {raw.get('calls', {}).get('locations')}호출)")
    else:
        got, times, mism, failed = fetch_all(todo)
        if RAW_SAVE:
            write_atomic(RAW_SAVE, json.dumps({"past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS, "times": times,
                                               "pts": {str(i): [vs, ds] for i, (vs, ds) in got.items()},
                                               "mismatch": mism, "failed": failed, "calls": dict(_calls), "peak": dict(_peak),
                                               "fetched": [datetime.fromtimestamp(_t0, KST).isoformat(timespec="seconds"),
                                                           datetime.now(KST).isoformat(timespec="seconds")]}))
    log(f"받음 {len(got):,}점 · 실패 {len(failed):,}점 · 라벨 불일치 {mism} · 호출 {_calls['locations']:,}"
        f"(요청 {_calls['requests']}, 429 {_calls['http429']}, 쉰 시간 {_calls['waited_s']:.0f}s, 최대 분 {_peak['min']}·시 {_peak['hour']})")
    why = f" (CMEMS 직접 실패: {cmems_fail})" if cmems_fail else ""
    if mism > 0.01 * max(1, len(got)):
        finish_keep(f"Open-Meteo 칸 라벨이 물은 곳과 다름 {mism}점 — SMOC 격자/반 칸 가정이 바뀜(OM_SHIFT 확인){why}", prev_meta, now)
    if not times:
        finish_keep(f"자료 0 — {_state['stop'] or '응답 없음'}{why}", prev_meta, now)

    # 바다 판정: 이번에 받은 점 중 값이 하나라도 있으면 바다
    has = {i: any(x is not None for x in vs) for i, (vs, ds) in got.items()}
    if mask:
        sea = mask
    else:
        sea = [has.get(i, False) for i in all_idx]
    sea_n = sum(sea)

    # 시간 축 — t0 = 실행일(KST) 00:00, 자료가 늦게 시작하면 그만큼 뒤로.
    #   (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) HH:30 보정이 라벨 t−2 … t+1 을 쓰므로 앞 2·뒤 1 시간 여유를 더 둔다
    t_day = t_day_kst(now)
    tdata0, tdataN = times[0], times[-1]
    t0 = max(t_day, tdata0 + 3600 * (HALF + 2))
    n = min(N_OUT, (tdataN - 3600 * (HALF + 1) - t0) // 3600 + 1)
    if n < 24:
        finish_keep(f"필터가 닿는 예보 {n}시간뿐(24시간 미만){why}", prev_meta, now)
    if t0 != t_day or n != N_OUT:
        log(f"⚠️ 시간 축 조정: t0 {datetime.fromtimestamp(t0, KST):%m-%d %H시} · {n}시간 (계약 기본 00시·{N_OUT}시간)")

    series = {i: uv_series(vs, ds) for i, (vs, ds) in got.items() if sea[i]}
    spd, dvals = [-1] * (ROWS * COLS * n), [-1] * (ROWS * COLS * n)
    missing = 0
    for i in all_idx:
        if not sea[i]:
            continue
        if i not in series:
            missing += 1
            continue
        u, v = series[i]
        bad = 0
        for k in range(n):
            j = (t0 + 3600 * k - tdata0) // 3600          # 라벨 t 의 자리(그 값은 실제 t+30분) — tidal_hh00 이 보정
            s = tidal_hh00(u, v, j)
            if s is None:
                bad += 1
                continue
            sp, dd = spd_dir(s[0], s[1])
            spd[i * n + k], dvals[i * n + k] = sp, dd
        if bad > 0.1 * n:
            missing += 1
    miss_pct = missing / max(1, sea_n)
    log(f"바다 칸 {sea_n:,} / {ROWS * COLS:,} · 빠짐 {missing}({miss_pct:.1%}) · {n}시간 "
        f"{datetime.fromtimestamp(t0, KST):%m-%d %H:%M} ~ {datetime.fromtimestamp(t0 + 3600 * (n - 1), KST):%m-%d %H:%M} KST")
    if failed and not mask:
        # 마스크를 배우는 실행인데 못 받은 점이 있으면 그 점은 바다인지 모른다 → 빠짐으로 센다
        missing += len(failed)
        miss_pct = missing / max(1, sea_n + len(failed))
    if _state["stop"]:
        log(f"⚠️ 받기가 중간에 멈췄음: {_state['stop']} — 빠진 비율로 판단")
    if miss_pct > MISSING_MAX:
        finish_keep(f"바다 칸 {miss_pct:.1%} 빠짐(상한 {MISSING_MAX:.0%}){' — ' + _state['stop'] if _state['stop'] else ''}{why}",
                    prev_meta, now, {"sea_points": sea_n, "missing_points": missing})
    if sea_n < 1000:
        finish_keep(f"바다 칸 {sea_n}뿐 — 이상한 응답{why}", prev_meta, now)

    # 검증
    def raw_at(i, k):
        """합성(raw total) 유속 cm/s·가는 쪽 — 대조용, 없으면 (-1, -1). 조석 성분과 같은 HH:30 보정(라벨 j−1·j 평균)"""
        vs, ds = got.get(i, ([], []))
        j = (t0 + 3600 * k - tdata0) // 3600
        uu = vv = 0.0
        for jj in (j - 1, j):
            if not (0 <= jj < len(vs)) or vs[jj] is None or ds[jj] is None:
                return -1, -1
            c, th = vs[jj] / 3.6 * 100.0, math.radians(ds[jj])
            uu += 0.5 * c * math.sin(th)
            vv += 0.5 * c * math.cos(th)
        return math.hypot(uu, vv), math.degrees(math.atan2(uu, vv)) % 360.0

    check = compare(spd, dvals, raw_at, sea, t0, n)
    log_check(check)
    spec = spectral_check(series, sea, times)
    for s in spec:
        if s.get("cell"):
            log(f"  스펙트럼 {s['name']} {s['cell']}: 조석 u 반일주 {s['tidal_u_bands']['semidiurnal']:.0%}·일주 "
                f"{s['tidal_u_bands']['diurnal']:.0%}·저 {s['tidal_u_bands']['low_gt36h']:.0%} 우세 {s['tidal_u_bands']['dominant_period_h']}h · "
                f"영점교차 주기 {s['zero_cross_period_h']}h · 저역통과에 남은 반일주 {s['lowpass_semidiurnal_vs_raw']} · "
                f"유속 p50/p95 {s['tidal_speed_p50_p95_cms']} cm/s")

    mask_learned = not mask
    if mask_learned and not failed:
        save_mask([has.get(i, False) for i in all_idx], now)
        log(f"바다 마스크 저장: 바다 {sea_n:,} · 육지 {ROWS * COLS - sea_n:,} → {OUT_MASK}")
    freq = {"M2_12.42h": 1 / 12.42, "S2_12h": 1 / 12.0, "K1_23.93h": 1 / 23.93, "O1_25.82h": 1 / 25.82,
            "inertial_35N_20.9h": 1 / 20.9, "2day_48h": 1 / 48.0, "3day_72h": 1 / 72.0}
    body = {
        "source_path": "openmeteo" + ("-fallback" if cmems_fail else ""),
        "cmems_fail": cmems_fail,
        "source": "CMEMS SMOC 합성 해류(utotal = 해류 + 조석 + 스토크스, 1/12°) — Open-Meteo Marine API(meteofrance_currents)로 받아 "
                  "시간 저역통과를 뺀 조석 성분만(대체 경로 — 동해처럼 조석이 약한 곳엔 관성진동·바람이 조금 남는다)",
        "license": "E.U. Copernicus Marine Service 자료(무료, 출처 표시: 'Generated using E.U. Copernicus Marine Service Information') · "
                   "Open-Meteo.com 경유(CC BY 4.0 출처 표시). ⚠️ Open-Meteo 무료 API 는 비상업 용도 조건 — 상업 앱이면 유료 API 키나 "
                   "CMEMS 직접(TIDAL_SOURCE=cmems)으로",
        "attribution": "Copernicus Marine Service (SMOC) · Open-Meteo.com",
        "fetched": _state.get("fetched") or [datetime.fromtimestamp(_t0, KST).isoformat(timespec="seconds"), now.isoformat(timespec="seconds")],
        "time_fix": "Open-Meteo 라벨 L 의 값 = SMOC 실제 L+30분(원값 HH:30 을 HH:00 으로 잘라 붙임) → 출력 t = 라벨 t−2…t+1 의 조석 성분 3차 가운데 보간 "
                    "(2026-10-09 검토: 원파일 time 672960.5 h = 00:30Z, 대조 rms 0.023 vs 0.368 m/s)",
        "data_window": [datetime.fromtimestamp(tdata0, KST).isoformat(timespec="minutes"),
                        datetime.fromtimestamp(tdataN, KST).isoformat(timespec="minutes")],
        "grid_extra": {"om_request_shift_deg": round(OM_SHIFT, 6),
                       "om_shift_evidence": "Open-Meteo 라벨 (j+.5)/12 의 값 = CMEMS 격자점 j/12 로 봄 — 해안선 대조: 다도해 216칸 일치 0.903(라벨 그대로 0.861), "
                                            "전국 7,081칸 brier 0.0200(0.0244)·일치 0.971(0.966). 경도는 해안칸만 세면 라벨 그대로가 0.766 vs 0.749 — ±1/24° 불확실 (2026-10-09)"},
        "points": {"sea": sea_n, "land": ROWS * COLS - sea_n, "missing": missing, "missing_pct": round(100 * miss_pct, 2),
                   "mask": "learned_this_run" if mask_learned else "sea_mask.json"},
        "requests": {"locations_called": _calls["locations"], "http_requests": _calls["requests"], "ok": _calls["ok"],
                     "fail": _calls["fail"], "http429": _calls["http429"], "waited_s": round(_calls["waited_s"]),
                     "peak_per_min": _peak["min"], "peak_per_hour": _peak["hour"],
                     "caps": {"min": MIN_CAP, "hour": HOUR_CAP, "run": RUN_BUDGET},
                     "free_limits": "분 600 · 시 5,000 · 일 10,000 (지점마다 1호출)",
                     "params": {"model": MODEL, "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS, "cell_selection": "nearest",
                                "timezone": "Asia/Seoul", "batch": BATCH}},
        "filter": {"name": FILTER_NAME, "half_width_h": HALF, "kernel_len": len(KER),
                   "pass_ratio": {k: round(response(f), 4) for k, f in freq.items()},
                   "why": ("조석 = 합성 − 가운데 맞춘 저역통과. Godin 24-24-25 는 조석 분리 표준 — M2·S2·K1·O1 이 저역통과에 거의 안 새서 "
                           "조석 성분(반일주+일주)이 온전히 남는다. 2026-10-09 같은 원자료로 a25 와 비교: KHOA 대조 같음(45°내 66.9% vs 66.8%), "
                           "저역통과에 남은 반일주 0.0 vs 0.0003 → Godin. 호출 수는 같다(past_days 2 vs 1 — 지점당 1호출). "
                           "2~3일 주기 바람 성분 일부와 관성진동(≈21h)은 조석 쪽에 남는다(필터 한계, 동해처럼 조석이 약한 곳에서 보임)."
                           if FILTER == "godin" else
                           "조석 = 합성 − 가운데 맞춘 25시간 평균. K1·O1·S2 가 3~4% 저역통과에 새서 조석 성분이 그만큼 작다. "
                           "2~3일 주기 바람 성분은 Godin 보다 덜 남는다.")},
        "validation": check,
        "spectral_check": spec,
    }
    write_outputs(now, prev_meta, t0, n, spd, dvals, FILTER_NAME + "-hh30mid", body)


def main():
    """출처 고르기 (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) — auto: CMEMS 직접 → 실패하면 Open-Meteo"""
    now = datetime.now(KST)
    prev_meta = load_json(OUT_META, {})
    cmems_fail = None
    if SOURCE in ("auto", "cmems", "cmems-native") and not RAW_LOAD:
        try:
            run_cmems(now, prev_meta)
            return
        except Exception as e:  # noqa: BLE001 — 원파일 못 찾음·꼴 바뀜·받기 실패·패키지 없음
            cmems_fail = f"{type(e).__name__}: {str(e)[:300]}"
            log(f"⚠️ CMEMS 직접 받기 실패 — {cmems_fail}")
            if SOURCE in ("cmems", "cmems-native"):
                finish_keep(f"CMEMS 직접 받기 실패 — {cmems_fail}", prev_meta, now)
            log("→ Open-Meteo(합성 − 저역통과) 대체 경로로 만든다")
    elif SOURCE not in ("auto", "cmems", "cmems-native", "openmeteo"):
        raise SystemExit(f"TIDAL_SOURCE={SOURCE} 모름 (auto|cmems|cmems-native|openmeteo)")
    run_openmeteo(now, prev_meta, cmems_fail)


if __name__ == "__main__":
    main()
