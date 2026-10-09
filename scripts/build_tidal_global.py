#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tidal_global.py — 전 세계 조류(조석 성분 utide·vtide) 2단계 격자  [2026-10-10]
(2026-10-10 조팀장 요청: 전 세계 조류 · 윈디처럼 부드럽게)

왜: 앱 '조류'는 한반도(korea_tidal.json, 1/12°)·동아시아(east_asia_tidal.json, 0.25°)만 칠한다. 조팀장 기준 화면(윈디 '조류')은
  전 세계 바다를 칠하고 흐른다 → 같은 변수(CMEMS SMOC utide·vtide)를 전 지구로 받아 화면 줌에 맞춰 골라 받게 2단계로 나눈다.
  korea/east_asia 두 파일은 지금 그대로 build_tidal.py 가 만든다(설치된 앱이 쓴다) — 이 스크립트는 그것들을 건드리지 않는다.

출처: build_tidal.py 와 같은 CMEMS 데이터셋 cmems_mod_glo_phy_anfc_merged-uv_PT1H-i 의 utide·vtide, 공식 도구(copernicusmarine,
  로그인 — 비밀값 CMEMS_USERNAME/PASSWORD → COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD), ARCO 시각 표기 그대로(KHOA 대조로 이쪽이 맞음).
  원격자 1/12° 전 지구 2041×4320(−80…90N, −180…179.917E). 시각 t0 = 실행일(KST) 00:00, 1시간 간격 96개 — korea/east_asia 와 같다.

받기 (흘려 읽기 — 메모리를 묶음 하나로 묶어 둔다):
  ARCO 조각 = (시각 1, 위도 512, 경도 2048) → 한 시각·한 변수 = 12조각. BATCH(6)시각씩 두 변수를 dask 스레드 WORKERS(32)갈래로 읽고
  곧바로 줄여(L0·L1) 버린다.
  ⚠️ open_dataset(chunk_size_limit=1) 필수 — 기본값(-1)은 dask 덩어리를 시각 50개로 묶어 한 시각만 읽어도 덩어리 통째를 받는다
     (2026-10-10 로컬 실측: 기본 483 MB·72 s·메모리 4.1 GB / 시각 → chunk_size_limit=1 은 9.4 MB·14 s·0.37 GB / 시각).
  2026-10-10 로컬 실측(한국 → 코페르니쿠스 저장소, 96시각 전체): 열기 14 s · 읽기 155–162 s · 줄이기 18–25 s · 받은 양 ≈ 880 MB · 최대 메모리 1.79 GB.
  2026-10-10 깃허브 러너 실측(첫 실행): 열기 4 s · 읽기 62 s · 줄이기 26 s · 파일 쓰기 16 s · 최대 메모리 2.34 GB(받은 양은 같은 ≈ 0.88 GB).

만드는 것 — 가지 'tidal-tiles'(main 과 이어지지 않는 부모 없는 커밋 하나, 실행마다 강제 푸시 — main 에는 안 넣는다)에
  index.json + <run>/L0.bin + <run>/L1/<key>.bin. 앱은 raw.githubusercontent.com 에서 받는다(키 없음·CORS *·ETag/304·Range·max-age 300).
  이번 run + 바로 전 run 폴더만 둔다(어제 index 를 5분 캐시로 막 받은 앱도 타일을 받게). 실행마다 새로 생기는 객체 ≈ 28–31 MB
  (항목이 이미 DEFLATE 라 git 이 더 못 누른다). 같은 날 다시 돌려 자료가 같으면 같은 블롭이라 거의 안 는다.
  ⚠️ 버려진 옛 커밋을 GitHub 가 언제 치우는지는 **보장이 없다**(2026-10-10 검토: 9분 뒤 바뀐 첫 커밋 baf37b62 가 아직 sha 주소로 200).
     자료는 매일 바뀌니 안 치워지면 실행마다 ≈ 31 MB(1년 ≈ 11 GB)가 이미 ≈ 6.4 GB 인 저장소에 쌓인다 → check-live 가 매일 저장소 크기(API .size)를
     남기고 기준(REPO_SIZE_BASE_KB)보다 REPO_SIZE_WARN_MB 넘게 늘면 경고한다. 1~2주 보고 줄곧 늘면 타일을 지웠다 다시 만들 수 있는
     데이터 전용 저장소(예: busan-wave-tidal)로 옮긴다 — 앱은 index 주소 하나만 바꾸면 된다. (GitHub Release 자산도 검토했으나 로컬에서 새 공개
  Release 를 만드는 것이 막혀 이쪽으로 — 조각 수백 개를 자산으로 올리면 API 한도에도 걸린다.)
  L0 overview  1° 전 지구 171×361 (행0 = 90N … −80N, 열0 = −180E … 180E — 마지막 열은 첫 열 복사라 경도 끝에서 보간이 이어진다)
               1° 점 = 원격자 12×12칸(그 점 ±0.5°, 위도·경도 각각 −6…+5칸) 중 바다 칸 평균 — 바다 칸이 하나라도 있으면 바다.
               점 하나만 뽑으면 해안·해협 값이 들쭉날쭉해(2026-10-10: 1° 점뽑기 vs 평균 상관 0.92) 줌아웃 화면이 거칠다. 줌 ≤ 3 용.
               (0.5° 는 압축 ≈ 10.6 MB 로 3배 — 줌 3 에서 1° 가 ≈ 11 px 라 1° 로 충분, 줌 4 부터는 L1)
  L1 tiles     0.25° 10°×10° 타일 41×41점(가장자리 행·열은 이웃 타일과 공유 — 타일 하나로 그 상자 안 어디든 보간 가능), 원격자 세 칸마다
               그대로 뽑는다 = east_asia_tidal.json 과 같은 점·같은 값(값을 섞지 않음). 위도 −80…90 17줄 × 경도 −180…180 36칸 = 612,
               전부 육지인 타일은 뺀다(2026-10-10: 바다 있는 타일 545). 줌 ≥ 4 용.
  값: u(동쪽+)·v(북쪽+) cm/s 를 0.5 cm/s 단위 int16 LE(반올림 오차 ≤ 0.25 cm/s), −32768 = 육지·빈칸.
      왜 0.5: 바다 유속 중앙값이 1.6 cm/s(2026-10-10, 0.25° 점)라 1 cm/s 단위는 약한 흐름의 방향이 ±20°쯤 흔들리고,
      0.1 단위는 압축 크기가 2배 넘게 큼(6시각 표본으로 96시각 환산 75 MB). 0.5 실측(96시각): 실행당 31.0 MB = L0 3.0 MB + 타일 545개 평균 51 KB(중앙 36·최대 276).
  저장: 항목(L0 하나 + L1 타일들)마다 파일 하나, raw DEFLATE(zlib wbits −15, 머리·꼬리 없음) — 앱은 화면에 걸친 타일만 받는다.
      항목 안(풀면): 32바이트 머리 + u 블록 + v 블록, 각 블록 int16 LE (r*cols+c)*n+k
      (korea/east_asia 계약과 같은 순서, 행0 = 북). 형식 상세는 FORMAT_DOC.

검사(올리기 전): 시각 96개 다 있음 · 격자 = 1/12° 전 지구 · 바다 점 수 범위 · 빈 바다 시각 ≤ 0.5% · 최대 유속 < 600 cm/s ·
  같은 실행에서 build_tidal.py 가 만든 east_asia_tidal.json·korea_tidal.json(t0 같을 때)과 겹치는 0.25° 점의 바다/육지 100% 일치,
  유속 차 ≤ 1 cm/s(정수 반올림 차) — 어긋나면 올리지 않는다(이전 것 유지).
실패·묵음: 만들기·올리기가 실패해도 korea/east_asia 는 이미 올라간 뒤다(워크플로 순서). 남은 전 세계 index 가 2일 이상 묵었거나·없거나·
  예보가 끝났으면 check-live 가 global=stale → 워크플로 마지막 단계가 실패로 끝나 메일이 간다(넓은 격자 묵음 알림과 같은 방식).

사용:
  python3 scripts/build_tidal_global.py build   --out DIR [--hours N]   # 받기 + 파일·index 만들기 (N: 개발용 시각 수 — 올리기 거부)
  python3 scripts/build_tidal_global.py publish --out DIR               # 가지 'tidal-tiles' 에 강제 푸시(이전 run 하나 유지) + 공개 주소로 검사
  python3 scripts/build_tidal_global.py check-live                      # 공개 index 확인 → GITHUB_OUTPUT global_state=ok|kept|stale
필요: numpy, copernicusmarine(xarray·dask), git(origin 에 푸시 권한 — 워크플로 checkout 자격).
"""
import argparse
import json
import os
import resource
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np

KST = timezone(timedelta(hours=9))
UTC = timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TIDAL_DIR = os.environ.get("TIDAL_GLOBAL_COMPARE_DIR") or os.path.join(ROOT, "data", "tidal")   # korea/east_asia 대조용(로컬 시험은 다른 곳)
DATASET_ID = "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"
SRC = "cmems-smoc-tide"
REPO = os.environ.get("GITHUB_REPOSITORY", "jojongkil123-commits/busan-wave")
BRANCH = "tidal-tiles"          # 데이터 가지(부모 없는 커밋 하나 — 실행마다 강제 푸시). main 에는 안 넣는다
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
INDEX_NAME = "index.json"
UA = {"User-Agent": "busan-wave-tidal-global/1.0 (+https://github.com/jojongkil123-commits/busan-wave)"}

N_OUT = 96                     # 시각 수(1시간 간격) — korea/east_asia 와 같다
BATCH = int(os.environ.get("TIDAL_GLOBAL_BATCH", "6"))        # 한 번에 읽는 시각 수(메모리 ≈ 0.2 GB/시각)
WORKERS = int(os.environ.get("TIDAL_GLOBAL_WORKERS", "32"))   # dask 스레드(조각 동시 받기)
SCALE = 0.5                    # cm/s per count
NODATA = -32768
MAGIC = b"TGT1"
HEAD_FMT = "<4sBBHHHIiiiHH"    # 32바이트 — FORMAT_DOC 참고
HEAD_LEN = struct.calcsize(HEAD_FMT)
STALE_DAYS = 2                 # 공개 index 가 이 날수 이상 묵으면 stale(이틀 연속 못 올림) — 넓은 격자와 같은 규칙
# (2026-10-10 검토 반영) 저장소 크기 감시 — 기준 = 2026-10-10 06:30 KST `gh api repos/... --jq .size`(전 세계 조류 실행 3번 뒤).
#   GitHub 의 .size 는 실시간이 아니라 몇 시간~며칠 늦게 다시 잰 값이다. main 의 날마다 자료 커밋도 같이 늘리므로 경고는 '들여다볼 때'라는 뜻.
REPO_SIZE_BASE_KB = 6_438_555
REPO_SIZE_WARN_MB = 500

# 원격자(1/12°) — 2026-10-10 open_dataset 확인: 위도 −80…90 2041점, 경도 −180…179.9167 4320점, 남→북
NAT_ROWS, NAT_COLS, NAT_D = 2041, 4320, 1.0 / 12.0
# L1: 0.25° 전 지구(원격자 세 칸마다) 681×1440, 행0 = 90N
G1_ROWS, G1_COLS, G1_D = 681, 1440, 0.25
TILE_DEG, TILE_PTS = 10, 41                     # 10°×10°, 41×41점(가장자리 공유)
TILE_LATS = list(range(80, -90, -TILE_DEG))     # 타일 minLat: 80(80–90N) … −80(−80–−70N) — 북쪽부터
TILE_LNGS = list(range(-180, 180, TILE_DEG))    # 타일 minLng: −180 … 170
# L0: 1° 전 지구 171×361, 행0 = 90N, 열0 = −180E, 열360 = 180E(= 열0 복사)
G0_ROWS, G0_COLS, G0_D = 171, 361, 1.0
L0_HALF = 6                                     # 1° 점 ±0.5° = 원격자 −6…+5칸(12칸)
# 바다 점 수 기대 범위(2026-10-10 실측 L1 686,754 / 980,640 · L0 46,020 / 61,731)
L1_SEA_RANGE = (620_000, 750_000)
L0_SEA_RANGE = (40_000, 52_000)
MAX_CMS = 600                  # 이보다 크면 깨진 값(2026-10-10 원격자 최대 470 cm/s, 0.25° 점 최대 348)
MISSING_MAX = 0.005            # 바다 점·시각 중 빈 비율 상한

FORMAT_DOC = {
    "container": "항목 하나 = 파일 하나(L0: <run>/L0.bin, L1: <run>/L1/<key>.bin). 파일 = raw DEFLATE(RFC 1951, zlib wbits=-15, 머리·꼬리 없음). "
                 "HTTP 는 그 바이트 그대로(Content-Encoding 없음) — 받은 바이트를 raw inflate 하면 payload",
    "compression": "deflate-raw",
    "payload": "풀면: 32바이트 머리 + u 블록 + v 블록. 블록 = int16 little-endian rows*cols*n 개, 순서 (r*cols+c)*n+k (행0 = 북, 열0 = 서, 점 안은 시간순 — "
               "korea/east_asia 계약과 같은 순서)",
    "header": "little-endian, 빈틈 없음: [0] char[4] magic 'TGT1' · [4] u8 version(1) · [5] u8 level(0|1) · [6] u16 rows · [8] u16 cols · "
              "[10] u16 n · [12] u32 t0(epoch s) · [16] i32 minLat×1000 · [20] i32 minLng×1000 · [24] i32 dDeg×1e6 · "
              "[28] u16 scale×1000(cm/s per count) · [30] u16 0(예약). maxLat = minLat + (rows−1)·dDeg, 점 (r,c) = (maxLat − r·dDeg, minLng + c·dDeg)",
    "value": "u = 동쪽(+), v = 북쪽(+), cm/s = count × scale (scale 0.5, 반올림 오차 ≤ 0.25 cm/s). -32768 = 육지·빈칸(그 점·시각 없음). "
             "유속 = hypot(u,v), 가는 쪽 = atan2(u, v) (도, 0 = 북, 시계방향 — korea/east_asia 의 dir 과 같은 뜻)",
    "time": "시각 k = t0 + k·step 초(step 3600). t0 = 실행일 KST 00:00 — korea/east_asia 와 같은 t0·n",
    "wrap": "경도는 −180…180 을 넘어가면 360 을 빼거나 더해 맞춘다. L0 마지막 열(180E)은 첫 열(−180E) 복사. L1 경도 170–180 타일의 마지막 열(180E)도 −180E 값",
}


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


def gh_annot(level, msg):
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{msg}", flush=True)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def t_day_kst(now):
    """실행일(KST) 00:00 의 epoch 초 — 계약 t0"""
    return int(datetime(now.year, now.month, now.day, tzinfo=KST).timestamp())


def max_rss_gb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1e9 if sys.platform == "darwin" else r * 1024 / 1e9      # macOS 바이트 · 리눅스 KB


def net_rx_bytes():
    """받은 바이트(기본 경로 네트워크 하나) — 리눅스 /proc/net/dev, macOS netstat. 못 읽으면 None
    (2026-10-10 실측) 깃허브 러너(Azure)는 eth0 와 가속 네트워크 VF(enP…)가 같은 흐름을 둘 다 세서 전부 더하면 2배(1.72 GB)로 나왔다
    → 기본 경로(/proc/net/route 목적지 0)의 장치 하나만 센다."""
    try:
        if os.path.exists("/proc/net/dev"):
            dev = None
            with open("/proc/net/route") as f:
                for line in f.readlines()[1:]:
                    p = line.split()
                    if len(p) > 1 and p[1] == "00000000":
                        dev = p[0]
                        break
            tot = 0
            with open("/proc/net/dev") as f:
                for line in f.readlines()[2:]:
                    name, rest = line.split(":", 1)
                    name = name.strip()
                    if (name == dev) if dev else name != "lo":
                        tot += int(rest.split()[0])
            return tot
        out = subprocess.run(["netstat", "-ib"], capture_output=True, text=True, timeout=10).stdout.splitlines()
        return sum(int(l.split()[6]) for l in out[1:] if l.split() and l.split()[0].startswith("en") and "<Link#" in l)
    except Exception:  # noqa: BLE001
        return None


# ── 받기 + 줄이기 (흘려 읽기) ─────────────────────────────────────────────────

def quant(a):
    """cm/s float → int16 count (0.5 cm/s), NaN → NODATA"""
    q = np.rint(np.nan_to_num(a, nan=0.0) / SCALE)
    np.clip(q, -32767, 32767, out=q)
    q = q.astype(np.int16)
    q[~np.isfinite(a)] = NODATA
    return q


def overview_1deg(F):
    """원격자 한 시각 F (2041, 4320) cm/s 남→북, 육지 NaN → L0 (171, 361) 북→남, 1° 점 ±0.5° 바다 칸 평균(바다 칸 0 이면 NaN)"""
    sea = np.isfinite(F)
    X = np.where(sea, F, 0.0).astype(np.float64)
    S = sea.astype(np.int32)
    # 위도: 1° 점 P 의 원격자 행 i = (P+80)·12 → 창 i−6 … i+5. 앞에 6줄, 뒤에 171·12 − 2041 − 6 = 5줄 덧대 (171, 12) 로 접는다
    pad_b = G0_ROWS * 12 - NAT_ROWS - L0_HALF
    X = np.pad(X, ((L0_HALF, pad_b), (0, 0)))
    S = np.pad(S, ((L0_HALF, pad_b), (0, 0)))
    # 경도: 점 Q 의 열 j = (Q+180)·12 → 창 j−6 … j+5. 6칸 굴려(감아 돌기) (360, 12) 로 접는다
    X = np.roll(X, L0_HALF, axis=1)
    S = np.roll(S, L0_HALF, axis=1)
    sx = X.reshape(G0_ROWS, 12, 360, 12).sum(axis=(1, 3))
    ss = S.reshape(G0_ROWS, 12, 360, 12).sum(axis=(1, 3))
    m = np.where(ss > 0, sx / np.maximum(ss, 1), np.nan)[::-1]         # 북→남
    return np.concatenate([m, m[:, :1]], axis=1).astype(np.float32)     # 180E = −180E 복사


def fetch_and_reduce(t0, n):
    """CMEMS 전 지구 utide·vtide 를 BATCH 시각씩 받아 L1(0.25° int16)·L0(1° float) 로 줄인다.
    돌려줌: L1u, L1v (681, 1440, n) int16 · L0u, L0v (171, 361, n) float32 cm/s(육지 NaN) · info"""
    import copernicusmarine  # noqa: WPS433 — 워크플로에서 pip 설치
    import dask

    if not (os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") and os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")):
        raise RuntimeError("코페르니쿠스 계정 환경변수 없음(CMEMS_USERNAME/CMEMS_PASSWORD 비밀값)")
    t_start = time.time()
    rx0 = net_rx_bytes()
    start = datetime.fromtimestamp(t0, UTC)
    end = datetime.fromtimestamp(t0 + 3600 * (n - 1), UTC)
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET_ID, variables=["utide", "vtide"],
        start_datetime=start.strftime("%Y-%m-%dT%H:%M:%S"), end_datetime=end.strftime("%Y-%m-%dT%H:%M:%S"),
        chunk_size_limit=1)            # ⚠️ dask 덩어리 = ARCO 조각(시각 1) — 위 머리말 참고
    t_open = time.time() - t_start
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    lat = ds["latitude"].values.astype(float)
    lon = ds["longitude"].values.astype(float)
    if (len(lat) != NAT_ROWS or len(lon) != NAT_COLS or abs(lat[0] + 80) > 1e-3 or abs(lat[-1] - 90) > 1e-3
            or abs(lon[0] + 180) > 1e-3 or abs(lon[-1] - (180 - NAT_D)) > 1e-3
            or np.abs(np.diff(lat) - NAT_D).max() > 1e-3 or np.abs(np.diff(lon) - NAT_D).max() > 1e-3):
        raise RuntimeError(f"원격자가 1/12° 전 지구(2041×4320, 남→북)와 다름: {len(lat)}×{len(lon)} lat {lat[0]:.4f}…{lat[-1]:.4f} "
                           f"lon {lon[0]:.4f}…{lon[-1]:.4f}")
    tchunk = ds["utide"].chunks[0] if ds["utide"].chunks else None
    if tchunk is None or max(tchunk) != 1:
        raise RuntimeError(f"dask 시각 덩어리가 1 이 아님({None if tchunk is None else max(tchunk)}) — 한 시각에 덩어리 통째를 받게 된다")
    times = ds["time"].values.astype("datetime64[s]").astype("int64").tolist()
    pos = {t: i for i, t in enumerate(times)}
    want = [t0 + 3600 * k for k in range(n)]
    miss = [k for k, t in enumerate(want) if t not in pos]
    if miss:
        raise RuntimeError(f"시각 {n - len(miss)}/{n}개만 있음(첫 빈 시각 k={miss[0]}) — 예보가 아직 그만큼 안 나왔을 수 있음")

    L1u = np.empty((G1_ROWS, G1_COLS, n), np.int16)
    L1v = np.empty((G1_ROWS, G1_COLS, n), np.int16)
    L0u = np.empty((G0_ROWS, G0_COLS, n), np.float32)
    L0v = np.empty((G0_ROWS, G0_COLS, n), np.float32)
    t_load = t_reduce = 0.0
    retries = 0
    for b0 in range(0, n, BATCH):
        ks = list(range(b0, min(n, b0 + BATCH)))
        idx = [pos[want[k]] for k in ks]
        for attempt in range(4):
            try:
                tl = time.time()
                with dask.config.set(scheduler="threads", num_workers=WORKERS):
                    sub = ds[["utide", "vtide"]].isel(time=idx).load()
                t_load += time.time() - tl
                break
            except Exception as e:  # noqa: BLE001 — 끊김·타임아웃은 그 묶음만 다시
                retries += 1
                if attempt == 3:
                    raise RuntimeError(f"시각 {ks[0]}–{ks[-1]} 받기 4번 실패 — {type(e).__name__}: {str(e)[:200]}") from e
                log(f"  ⚠️ 시각 {ks[0]}–{ks[-1]} 받기 실패({type(e).__name__}: {str(e)[:120]}) — {5 * (attempt + 1)}s 뒤 다시")
                time.sleep(5 * (attempt + 1))
        tr = time.time()
        U = sub["utide"].transpose("time", "latitude", "longitude").values
        V = sub["vtide"].transpose("time", "latitude", "longitude").values
        del sub
        for j, k in enumerate(ks):
            u, v = U[j], V[j]
            bad = ~(np.isfinite(u) & np.isfinite(v) & (np.abs(u) < 1e30) & (np.abs(v) < 1e30))   # 채움값 9.97e36 → 육지
            with np.errstate(over="ignore", invalid="ignore"):
                u = np.where(bad, np.nan, u * np.float32(100.0))
                v = np.where(bad, np.nan, v * np.float32(100.0))
            L1u[:, :, k] = quant(u[::3, ::3][::-1])        # 세 칸마다 = 0.25° 정수배 위경도 → 북→남
            L1v[:, :, k] = quant(v[::3, ::3][::-1])
            L0u[:, :, k] = overview_1deg(u)
            L0v[:, :, k] = overview_1deg(v)
        del U, V
        t_reduce += time.time() - tr
        done = ks[-1] + 1
        el = time.time() - t_start
        rx = net_rx_bytes()
        rx_mb = None if (rx is None or rx0 is None) else (rx - rx0) / 1e6
        log(f"  시각 {done}/{n} · {el:.0f}s · 받음 {'?' if rx_mb is None else f'{rx_mb:.0f} MB'} · 최대 메모리 {max_rss_gb():.2f} GB")
    rx = net_rx_bytes()
    info = {
        "via": "copernicusmarine " + getattr(copernicusmarine, "__version__", "?") + " open_dataset (ARCO, 로그인, chunk_size_limit=1)",
        "dataset_id": DATASET_ID,
        "source_times": [start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")],
        "time_label": "공식 도구 표기 그대로(HH:00) — korea/east_asia 와 같음",
        "chunks": str(ds["utide"].encoding.get("preferred_chunks") or "?"),
        "batch_hours": BATCH, "workers": WORKERS, "retries": retries,
        "open_s": round(t_open, 1), "load_s": round(t_load, 1), "reduce_s": round(t_reduce, 1),
        "total_s": round(time.time() - t_start, 1),
        "download_mb": None if (rx is None or rx0 is None) else round((rx - rx0) / 1e6, 1),
        "download_note": "기본 경로 장치가 받은 바이트(리눅스 /proc/net/dev·macOS netstat en*) — 다른 받기가 겹치면 조금 크게 잡힌다",
        "max_rss_gb": round(max_rss_gb(), 2),
    }
    return L1u, L1v, L0u, L0v, info


# ── 항목·index ────────────────────────────────────────────────────────────────

def payload(level, rows, cols, n, t0, min_lat, min_lng, d, qu, qv):
    """항목 하나(풀린 모양) = 32바이트 머리 + u·v int16 LE 블록 ((r*cols+c)*n+k)"""
    head = struct.pack(HEAD_FMT, MAGIC, 1, level, rows, cols, n, t0, round(min_lat * 1000), round(min_lng * 1000),
                       round(d * 1e6), round(SCALE * 1000), 0)
    assert len(head) == HEAD_LEN == 32
    return head + np.ascontiguousarray(qu, dtype="<i2").tobytes() + np.ascontiguousarray(qv, dtype="<i2").tobytes()


def deflate_raw(b):
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
    return c.compress(b) + c.flush()


def inflate_raw(b):
    return zlib.decompress(b, -15)


def parse_payload(raw):
    """앱이 할 일의 참고 구현 — (머리 dict, u, v: (rows, cols, n) int16)"""
    magic, ver, level, rows, cols, n, t0, la, lo, d, sc, _ = struct.unpack(HEAD_FMT, raw[:HEAD_LEN])
    if magic != MAGIC or ver != 1:
        raise ValueError(f"머리 다름 {magic} v{ver}")
    cnt = rows * cols * n
    if len(raw) != HEAD_LEN + 4 * cnt:
        raise ValueError(f"길이 {len(raw)} ≠ {HEAD_LEN + 4 * cnt}")
    a = np.frombuffer(raw, dtype="<i2", offset=HEAD_LEN)
    head = {"level": level, "rows": rows, "cols": cols, "n": n, "t0": t0, "minLat": la / 1000, "minLng": lo / 1000,
            "dDeg": d / 1e6, "scale": sc / 1000}
    return head, a[:cnt].reshape(rows, cols, n), a[cnt:].reshape(rows, cols, n)


def tile_view(L, min_lat, min_lng):
    """L1 전 지구 (681, 1440, n) 에서 타일 (41, 41, n) — 경도 180 넘는 열은 감아 돈다"""
    r0 = int(round((90 - (min_lat + TILE_DEG)) / G1_D))
    c0 = int(round((min_lng + 180) / G1_D))
    cols = [(c0 + c) % G1_COLS for c in range(TILE_PTS)]
    return L[r0:r0 + TILE_PTS][:, cols, :]


def build(out_dir, hours):
    now = datetime.now(KST)
    t0 = t_day_kst(now)
    n = hours or N_OUT
    run = datetime.fromtimestamp(t0, KST).strftime("%Y%m%d") + "-" + datetime.now(UTC).strftime("%H%M")
    log(f"전 세계 조류(CMEMS utide·vtide) — {datetime.fromtimestamp(t0, KST):%m-%d %H:%M} KST 부터 {n}시간 · run {run}"
        f"{' (개발용 — 올리기 거부)' if hours else ''}")
    cache = os.environ.get("TIDAL_GLOBAL_DEV_CACHE")       # 개발용: 받은(줄인) 배열을 저장·재사용(.npz) — 워크플로에선 안 쓴다
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=False)
        if int(z["t0"]) != t0 or int(z["n"]) != n:
            raise RuntimeError(f"개발 캐시 t0/n 다름 — {cache} 지울 것")
        L1u, L1v, L0u, L0v, info = z["L1u"], z["L1v"], z["L0u"], z["L0v"], json.loads(str(z["info"]))
        log(f"개발 캐시 읽음 {cache}")
    else:
        L1u, L1v, L0u, L0v, info = fetch_and_reduce(t0, n)
        if cache:
            np.savez(cache, L1u=L1u, L1v=L1v, L0u=L0u, L0v=L0v, info=json.dumps(info), t0=t0, n=n)
    log(f"받기 끝: 열기 {info['open_s']}s · 읽기 {info['load_s']}s · 줄이기 {info['reduce_s']}s · 받음 {info['download_mb']} MB · "
        f"최대 메모리 {info['max_rss_gb']} GB")

    # ── 검사 ──
    t_enc = time.time()
    # L1: 바다 점 = 90% 이상 시각에 값. 그보다 적으면 그 점은 전부 빈칸
    have1 = (L1u != NODATA).sum(axis=2)
    sea1 = have1 >= 0.9 * n
    L1u[~sea1] = NODATA
    L1v[~sea1] = NODATA
    sea1_n = int(sea1.sum())
    miss1 = int(((L1u == NODATA) & sea1[:, :, None]).sum())
    sea0 = np.isfinite(L0u).sum(axis=2) >= 0.9 * n
    sea0_n = int(sea0.sum())
    qL0u, qL0v = quant(L0u), quant(L0v)
    qL0u[~sea0] = NODATA
    qL0v[~sea0] = NODATA
    del L0u, L0v
    top1 = 0.0
    for k in range(n):                                   # 시각마다(메모리 아끼기) 최대 유속
        su, sv = L1u[:, :, k], L1v[:, :, k]
        ok = su != NODATA
        if ok.any():
            top1 = max(top1, float(np.hypot(su[ok].astype(np.float32), sv[ok].astype(np.float32)).max()) * SCALE)
    ks6 = list(range(0, n, 6))                           # 분포는 6시간마다 표본
    su, sv = L1u[:, :, ks6], L1v[:, :, ks6]
    ok = su != NODATA
    sp = np.hypot(su[ok].astype(np.float32), sv[ok].astype(np.float32)) * SCALE
    p50, p90, p99 = (float(x) for x in np.percentile(sp, [50, 90, 99]))
    del su, sv, ok, sp
    problems = []
    if not L1_SEA_RANGE[0] <= sea1_n <= L1_SEA_RANGE[1]:
        problems.append(f"L1 바다 점 {sea1_n:,} (기대 {L1_SEA_RANGE[0]:,}–{L1_SEA_RANGE[1]:,})")
    if not L0_SEA_RANGE[0] <= sea0_n <= L0_SEA_RANGE[1]:
        problems.append(f"L0 바다 점 {sea0_n:,} (기대 {L0_SEA_RANGE[0]:,}–{L0_SEA_RANGE[1]:,})")
    if miss1 > MISSING_MAX * sea1_n * n:
        problems.append(f"L1 빈 바다 점·시각 {miss1:,} ({miss1 / max(1, sea1_n * n):.2%})")
    if top1 > MAX_CMS:
        problems.append(f"L1 유속 {top1:.0f} cm/s — 깨진 값")
    log(f"L1 0.25° 바다 점 {sea1_n:,}/{G1_ROWS * G1_COLS:,} · 빈 시각 {miss1} · 유속 중앙 {p50:.1f} · 90% {p90:.1f} · 99% {p99:.1f} · "
        f"최대 {top1:.0f} cm/s · L0 1° 바다 점 {sea0_n:,}/{G0_ROWS * G0_COLS:,}")

    # korea/east_asia 와 겹치는 점 대조(같은 실행·같은 t0 일 때) — 어긋나면 올리지 않는다
    check = {}
    for name in ("east_asia_tidal.json", "korea_tidal.json"):
        c = compare_contract(os.path.join(TIDAL_DIR, name), t0, n, lambda R, C: (L1u[R, C], L1v[R, C]))
        check[name] = c
        log(f"대조 {name}: {json.dumps(c, ensure_ascii=False)}")
        if c.get("status") == "compared" and not c.get("ok"):
            problems.append(f"{name} 와 겹치는 점이 다름 — {c.get('why')}")
    if problems:
        raise RuntimeError("검사 실패: " + " · ".join(problems))

    # ── 파일 쓰기: <run>/L0.bin · <run>/L1/<key>.bin (항목마다 raw DEFLATE) · index.json · README.md ──
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)          # 지난 실행 찌꺼기가 섞여 올라가지 않게
    os.makedirs(os.path.join(out_dir, run, "L1"))
    raw_tile_bytes = HEAD_LEN + 4 * TILE_PTS * TILE_PTS * n
    raw_ov_bytes = HEAD_LEN + 4 * G0_ROWS * G0_COLS * n

    def put(rel, raw):
        z = deflate_raw(raw)
        with open(os.path.join(out_dir, rel), "wb") as f:
            f.write(z)
        return len(z), zlib.crc32(raw) & 0xFFFFFFFF

    ov_rel = f"{run}/L0.bin"

    def one_tile(la_lo):
        la, lo = la_lo
        tu, tv = tile_view(L1u, la, lo), tile_view(L1v, la, lo)
        sea_pts = int((tu != NODATA).any(axis=2).sum())
        if sea_pts == 0:
            return la, lo, 0, None
        return la, lo, sea_pts, put(f"{run}/L1/{la}_{lo}.bin", payload(1, TILE_PTS, TILE_PTS, n, t0, float(la), float(lo), G1_D, tu, tv))

    # zlib 은 GIL 을 놓는다 → 타일 누르기를 코어 수만큼 나란히(2026-10-10 로컬: 한 줄 109 s)
    with ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2)) as ex:
        f_ov = ex.submit(put, ov_rel, payload(0, G0_ROWS, G0_COLS, n, t0, -80.0, -180.0, G0_D, qL0u, qL0v))
        done = list(ex.map(one_tile, [(la, lo) for la in TILE_LATS for lo in TILE_LNGS]))
        ov_len, ov_crc = f_ov.result()
    tiles, land_tiles = {}, 0
    for la, lo, sea_pts, r in done:                   # 북쪽 줄부터·서쪽부터 순서 그대로
        if r is None:
            land_tiles += 1
            continue
        tiles[f"{la}_{lo}"] = [r[0], sea_pts, r[1]]    # [바이트(눌린 파일), 바다 점 수(1–1681), crc32(풀린 항목)]
    ts = sorted(v[0] for v in tiles.values())
    total = ov_len + sum(ts)
    log(f"파일 {run}/: 모두 {total / 1e6:.1f} MB · L0 {ov_len / 1e6:.2f} MB(풀면 {raw_ov_bytes / 1e6:.1f}) · L1 타일 {len(tiles)}개(육지 {land_tiles}개 뺌) "
        f"평균 {sum(ts) / len(ts) / 1e3:.0f} KB · 중앙 {ts[len(ts) // 2] / 1e3:.0f} · 최대 {ts[-1] / 1e3:.0f} KB(풀면 {raw_tile_bytes / 1e3:.0f} KB) · "
        f"{time.time() - t_enc:.0f}s")

    index = {
        "format": "busan-wave-tidal-global", "version": 1,
        "run": run, "generated": now.isoformat(timespec="seconds"),
        "src": SRC, "unit": "cm/s", "dirConv": "toward", "components": "u=east(+), v=north(+)",
        "t0": t0, "n": n, "step": 3600,
        "forecast_start": datetime.fromtimestamp(t0, KST).isoformat(timespec="minutes"),
        "forecast_end": datetime.fromtimestamp(t0 + 3600 * (n - 1), KST).isoformat(timespec="minutes"),
        "dev": bool(hours),
        "host": f"raw.githubusercontent.com — 가지 '{BRANCH}'(부모 없는 커밋 하나를 실행마다 강제 푸시, 이번 run + 바로 전 run 폴더만 둔다)",
        "base": RAW_BASE,
        "indexUrl": RAW_BASE + INDEX_NAME,
        "bytesTotal": total,
        "encoding": dict(FORMAT_DOC, scale=SCALE, nodata=NODATA, headerBytes=HEAD_LEN, magic="TGT1", byteOrder="little-endian"),
        "levels": [
            {"level": 0, "name": "overview", "useBelowZoom": 4, "dDeg": G0_D, "minLat": -80.0, "maxLat": 90.0, "minLng": -180.0,
             "maxLng": 180.0, "rows": G0_ROWS, "cols": G0_COLS, "payloadBytes": raw_ov_bytes, "seaPoints": sea0_n,
             "how": "1° 점 ±0.5°(원격자 12×12칸) 바다 칸 평균, 바다 칸 하나라도 있으면 바다. 마지막 열(180E) = 첫 열(−180E)",
             "file": ov_rel, "url": RAW_BASE + ov_rel, "bytes": ov_len, "crc32": ov_crc},
            {"level": 1, "name": "tiles", "useFromZoom": 4, "dDeg": G1_D, "tileDeg": TILE_DEG, "rows": TILE_PTS, "cols": TILE_PTS,
             "payloadBytes": raw_tile_bytes, "seaPoints": sea1_n,
             "how": "원격자(1/12°) 세 칸마다 그대로 = east_asia_tidal.json 과 같은 점. 타일 = minLat…minLat+10, minLng…minLng+10 (41×41, 가장자리 공유)",
             "key": "'{minLat}_{minLng}' 정수 — minLat = floor(lat/10)*10 ∈ {−80,…,80}(lat 90 은 80), minLng = floor(lng/10)*10 ∈ {−180,…,170}. "
                    "tiles 에 없는 키 = 전부 육지(받지 않는다)",
             "urlTemplate": RAW_BASE + run + "/L1/{key}.bin",
             "tileCount": len(tiles), "landTiles": land_tiles,
             "tileEntry": "[bytes(눌린 파일), seaPoints(1–1681), crc32(풀린 항목, zlib CRC-32)]",
             "tiles": tiles},
        ],
        "speed_cms": {"p50": round(p50, 1), "p90": round(p90, 1), "p99": round(p99, 1), "max": round(top1)},
        "check": check,
        "cmems": info,
        "license": "E.U. Copernicus Marine Service Information — 무료·상업 사용 가능, 출처 표시 필수('Generated using E.U. Copernicus Marine "
                   "Service Information')",
        "attribution": "Copernicus Marine Service (SMOC)",
    }
    with open(os.path.join(out_dir, INDEX_NAME), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(BRANCH_README)
    log(f"✅ index {os.path.getsize(os.path.join(out_dir, INDEX_NAME)) / 1e3:.0f} KB · 모두 {total / 1e6:.1f} MB → {out_dir}")
    gh_output(global_build="ok", global_run=run)
    return index


BRANCH_README = """# tidal-tiles — 전 세계 조류 격자 (자동 · 매 실행 강제 푸시)

(2026-10-10 조팀장 요청: 전 세계 조류 · 윈디처럼 부드럽게)

이 가지는 main 과 이어지지 않는 **부모 없는 커밋 하나**다. update-tidal 워크플로가 매일 새로 만들어 강제 푸시한다(역사가 쌓이지 않게).
코드·형식 설명은 main 의 `scripts/build_tidal_global.py` (FORMAT_DOC).

- `index.json` — 지금 run, t0·n, 두 단계(L0 1° 전 지구 · L1 0.25° 10°×10° 타일) 목록·주소·형식
- `<run>/L0.bin`, `<run>/L1/<minLat>_<minLng>.bin` — raw DEFLATE 로 누른 int16 u·v (0.5 cm/s 단위)
- 이번 run 과 바로 전 run 폴더만 둔다(어제 index 를 막 받은 앱이 타일을 마저 받을 수 있게).

Generated using E.U. Copernicus Marine Service Information.
"""


def compare_contract(path, t0, n, get_uv):
    """korea/east_asia 계약 파일(spd·dir 정수, -1 육지)과 겹치는 0.25° 점을 맞대 본다. get_uv(R, C) → (u, v) int16 n개"""
    g = load_json(path, None)
    if not isinstance(g, dict) or "spd" not in g:
        return {"status": "skipped", "why": "파일 없음"}
    if g.get("t0") != t0 or g.get("n") != n:
        return {"status": "skipped", "why": f"t0/n 다름(그 파일 t0 {g.get('t0')} n {g.get('n')} — 오늘 못 만들었거나 개발용 시각 수)"}
    rows, cols, gn = g["rows"], g["cols"], g["n"]
    d = (g["maxLat"] - g["minLat"]) / (rows - 1)
    spd, dr = g["spd"], g["dir"]
    pts = land_ok = sea_ok = mism_mask = 0
    dsp_max = 0
    dir_big = dir_n = 0
    for r in range(rows):
        la = g["maxLat"] - r * d
        R = (90 - la) / G1_D
        if abs(R - round(R)) > 1e-6:
            continue
        for c in range(cols):
            lo = g["minLng"] + c * d
            C = (lo + 180) / G1_D
            if abs(C - round(C)) > 1e-6:
                continue
            u, v = get_uv(int(round(R)), int(round(C)) % G1_COLS)
            i = (r * cols + c) * gn
            s_c, d_c = spd[i:i + gn], dr[i:i + gn]
            pts += 1
            land_c = all(x < 0 for x in s_c)
            land_g = bool((u == NODATA).all())
            if land_c and land_g:
                land_ok += 1
                continue
            if land_c != land_g:
                mism_mask += 1
                continue
            sea_ok += 1
            uf, vf = u.astype(float) * SCALE, v.astype(float) * SCALE
            sg = np.rint(np.hypot(uf, vf)).astype(int)
            dg = np.degrees(np.arctan2(uf, vf)) % 360
            for k in range(gn):
                if s_c[k] < 0 or u[k] == NODATA:
                    continue
                dsp_max = max(dsp_max, abs(int(sg[k]) - s_c[k]))
                if s_c[k] >= 5:
                    dd = abs((float(dg[k]) - d_c[k] + 180) % 360 - 180)
                    dir_n += 1
                    dir_big += int(dd > 5)
    ok = bool(pts > 0 and mism_mask == 0 and dsp_max <= 1 and dir_big <= 0.001 * max(1, dir_n))
    why = None if ok else f"바다/육지 다름 {mism_mask}점 · 유속 차 최대 {dsp_max} · 방향 5° 넘게 다름 {dir_big}/{dir_n}"
    return {"status": "compared", "ok": ok, "why": why, "points": pts, "sea": sea_ok, "land": land_ok, "mask_mismatch": mism_mask,
            "max_abs_dspd_cms": dsp_max, "dir_gt5deg": dir_big, "dir_checked_ge5cms": dir_n}


# ── 올리기 (가지 'tidal-tiles' — 부모 없는 커밋 하나, 강제 푸시) ─────────────────

def git(args, env=None, check=True, timeout=900):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(["git"] + args, cwd=ROOT, env=e, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} 실패: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def http_get(url, timeout=120):
    req = urllib.request.Request(url, headers=dict(UA))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def remote_head():
    """원격 가지 커밋 sha (없으면 None)"""
    r = git(["ls-remote", "origin", f"refs/heads/{BRANCH}"], check=False, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-remote 실패: {r.stderr.strip()[:200]}")
    line = r.stdout.strip().split("\n")[0] if r.stdout.strip() else ""
    return line.split()[0] if line else None


def publish(out_dir):
    index = load_json(os.path.join(out_dir, INDEX_NAME), None)
    if not isinstance(index, dict) or index.get("format") != "busan-wave-tidal-global":
        raise RuntimeError(f"{out_dir}/{INDEX_NAME} 없음 — build 가 실패했다")
    if index.get("dev") or index.get("n") != N_OUT:
        raise RuntimeError("개발용(시각 수 줄인) 빌드는 올리지 않는다")
    run = index["run"]
    t = time.time()
    # ① 지금 가지(있으면)에서 바로 전 run 폴더를 이어 둔다 — 그 index 를 막 받은 앱이 타일을 마저 받게
    old = remote_head()
    prev_run = None
    if old:
        git(["fetch", "-q", "--depth=1", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}"], timeout=600)
        r = git(["show", f"refs/remotes/origin/{BRANCH}:{INDEX_NAME}"], check=False)
        try:
            prev_run = json.loads(r.stdout).get("run") if r.returncode == 0 else None
        except ValueError:
            prev_run = None
        if prev_run == run or (prev_run and git(["cat-file", "-e", f"refs/remotes/origin/{BRANCH}:{prev_run}"], check=False).returncode):
            prev_run = None
    # ② 임시 index 로 나무 만들기(작업 폴더·main 은 안 건드림): 전 run 폴더 + 이번 run 폴더 + index.json + README.md
    idx_file = os.path.join(out_dir, ".git_index_tmp")
    if os.path.exists(idx_file):
        os.remove(idx_file)
    env = {"GIT_INDEX_FILE": idx_file,
           "GIT_AUTHOR_NAME": "github-actions", "GIT_AUTHOR_EMAIL": "actions@github.com",
           "GIT_COMMITTER_NAME": "github-actions", "GIT_COMMITTER_EMAIL": "actions@github.com"}
    git(["read-tree", "--empty"], env=env)
    if prev_run:
        git(["read-tree", f"--prefix={prev_run}/", f"refs/remotes/origin/{BRANCH}:{prev_run}"], env=env)
    git(["--work-tree", out_dir, "add", "-f", "--", run, INDEX_NAME, "README.md"], env=env)
    tree = git(["write-tree"], env=env).stdout.strip()
    msg = (f"전 세계 조류 격자 run {run} (t0 {index['forecast_start']}, {index['n']}시간)"
           f"{' — 이전 run ' + prev_run + ' 함께 둠' if prev_run else ''} (2026-10-10 조팀장 요청: 전 세계 조류 · 윈디처럼 부드럽게)")
    commit = git(["commit-tree", tree, "-m", msg], env=env).stdout.strip()         # 부모 없음 → 역사가 쌓이지 않는다
    os.remove(idx_file)
    # ③ 데이터 가지만 강제 푸시 (main 은 절대 아님). 가지가 그새 바뀌었으면(다른 실행) lease 로 거절된다 → 실패로 알림
    lease = f"--force-with-lease=refs/heads/{BRANCH}:{old}" if old else f"--force-with-lease=refs/heads/{BRANCH}:"
    git(["push", "-q", lease, "origin", f"{commit}:refs/heads/{BRANCH}"], timeout=900)
    push_s = round(time.time() - t, 1)
    log(f"✅ 가지 '{BRANCH}' ← {commit[:10]} (run {run}{', 이전 run ' + prev_run + ' 유지' if prev_run else ''}) · {push_s}s")
    v = verify_live(out_dir, index, commit)
    v["push_s"] = push_s
    log(f"✅ 공개 주소 검사: {json.dumps(v, ensure_ascii=False)}")
    gh_output(global_publish="ok", global_commit=commit)
    return v


def verify_live(out_dir, index, commit):
    """올린 커밋(sha 주소 — 캐시 없음)으로 index·L0·타일 몇 개를 받아 로컬과 바이트까지 같은지 + 풀어 crc·머리 확인,
    그다음 가지 주소(index.json, raw 캐시 max-age 300)가 새 run 을 보일 때까지 기다린 시간"""
    t = time.time()
    sha_base = f"https://raw.githubusercontent.com/{REPO}/{commit}/"
    res = {"commit": commit, "entries": []}
    for attempt in range(8):                       # 푸시 직후 raw 가 새 커밋을 아직 모를 수 있다
        try:
            st, hd, body = http_get(sha_base + INDEX_NAME, timeout=60)
            if json.loads(body).get("run") == index["run"]:
                break
        except Exception as e:  # noqa: BLE001
            log(f"  sha 주소 index 아직({type(e).__name__}) — 다시")
        time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError("올린 커밋의 index 를 raw 에서 못 받음")
    lv1 = index["levels"][1]
    picks = [("L0", index["levels"][0]["file"], index["levels"][0]["crc32"], index["levels"][0]["bytes"])]
    for key in ("30_120", "30_130", "20_120", "40_-80", "-40_140", "0_-30", "50_170", "50_-180"):
        if key in lv1["tiles"]:
            e = lv1["tiles"][key]
            picks.append((key, f"{index['run']}/L1/{key}.bin", e[2], e[0]))
    for key, rel, crc, ln in picks:
        st, hd, z = http_get(sha_base + rel)
        with open(os.path.join(out_dir, rel), "rb") as f:
            same_local = f.read() == z
        raw = inflate_raw(z)
        head, _, _ = parse_payload(raw)
        ok = st == 200 and len(z) == ln and same_local and (zlib.crc32(raw) & 0xFFFFFFFF) == crc and head["t0"] == index["t0"]
        res["entries"].append({"key": key, "http": st, "bytes": len(z), "ok": ok})
        if not ok:
            raise RuntimeError(f"올린 {rel} 다름: HTTP {st} · {len(z)}/{ln} 바이트 · 로컬과 같음 {same_local}")
    res["headers_sample"] = {k: v for k, v in hd.items() if k.lower() in ("content-type", "content-encoding", "etag", "cache-control",
                                                                          "access-control-allow-origin", "accept-ranges", "x-cache")}
    # 가지 주소(앱이 쓰는 곳)가 새 run 을 보일 때까지(raw 캐시 max-age=300)
    tb = time.time()
    seen = None
    while time.time() - tb < 420:
        try:
            _, _, body = http_get(RAW_BASE + INDEX_NAME, timeout=60)
            seen = json.loads(body).get("run")
            if seen == index["run"]:
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(20)
    res["branch_index_run"] = seen
    res["branch_index_visible_after_s"] = round(time.time() - tb, 1) if seen == index["run"] else None
    if seen != index["run"]:
        gh_annot("warning", f"가지 주소 index 가 7분 안에 새 run 으로 안 바뀜(보이는 run {seen}) — raw 캐시. 다음 확인 때 다시 본다")
    res["seconds"] = round(time.time() - t, 1)
    return res


def fetch_index_live():
    """지금 가지의 index — 커밋 sha 주소(캐시 없음)로, 못 하면 가지 주소로"""
    try:
        sha = remote_head()
        if sha:
            _, _, body = http_get(f"https://raw.githubusercontent.com/{REPO}/{sha}/{INDEX_NAME}", timeout=60)
            return json.loads(body)
    except Exception as e:  # noqa: BLE001
        log(f"  sha 주소로 못 읽음({type(e).__name__}) — 가지 주소로")
    _, _, body = http_get(RAW_BASE + INDEX_NAME, timeout=60)
    return json.loads(body)


def repo_size_check():
    """저장소 크기(GitHub API .size, KB)를 남긴다 — 가지 tidal-tiles 를 강제 푸시하며 버린 옛 커밋을 GitHub 가 실제로 치우는지 이 숫자로 본다.
    기준보다 REPO_SIZE_WARN_MB 넘게 늘었으면 경고(워크플로는 실패시키지 않음). 못 읽으면 건너뛴다."""
    hdr = dict(UA)
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        hdr["Authorization"] = f"Bearer {tok}"
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}", headers=hdr)
        with urllib.request.urlopen(req, timeout=30) as r:
            size_kb = int(json.loads(r.read())["size"])
    except Exception as e:  # noqa: BLE001
        log(f"  저장소 크기 못 읽음({type(e).__name__}: {str(e)[:120]}) — 건너뜀")
        return None
    grow_mb = (size_kb - REPO_SIZE_BASE_KB) / 1024
    msg = (f"저장소 크기 {size_kb / 1048576:.2f} GB (API .size {size_kb:,} KB) — 기준 {REPO_SIZE_BASE_KB / 1048576:.2f} GB(2026-10-10) 대비 {grow_mb:+,.0f} MB")
    log(("⚠️ " if grow_mb > REPO_SIZE_WARN_MB else "📦 ") + msg)
    gh_output(repo_size_kb=size_kb, repo_grow_mb=round(grow_mb))
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        try:
            with open(summ, "a", encoding="utf-8") as f:
                f.write(f"- {msg}\n")
        except OSError:
            pass
    if grow_mb > REPO_SIZE_WARN_MB:
        gh_annot("warning", msg + f" — {REPO_SIZE_WARN_MB} MB 넘게 늘었다. 가지 {BRANCH} 의 버린 커밋이 안 치워지는 듯하면 "
                 "타일을 지웠다 다시 만들 수 있는 데이터 전용 저장소로 옮길 때(build_tidal_global.py 머리 참고)")
    return size_kb


def check_live():
    """공개 index 가 묵었나 — stale(2일 이상·없음·예보 끝남)이면 GITHUB_OUTPUT global_state=stale (워크플로가 실패로 끝내 메일)"""
    repo_size_check()
    now = datetime.now(KST)
    try:
        live = fetch_index_live()
        t0, n = int(live["t0"]), int(live["n"])
    except Exception as e:  # noqa: BLE001
        msg = f"공개 전 세계 조류 index 를 못 읽음({type(e).__name__}: {str(e)[:150]}) — {RAW_BASE}{INDEX_NAME}"
        log("⚠️ " + msg)
        gh_output(global_state="stale", global_reason=msg)
        return "stale"
    age_d = (t_day_kst(now) - t0) // 86400
    left_h = (t0 + 3600 * (n - 1) - now.timestamp()) / 3600
    stale = age_d >= STALE_DAYS or left_h < 0
    state = "stale" if stale else ("ok" if age_d <= 0 else "kept")
    msg = f"공개 index run {live.get('run')} · t0 {datetime.fromtimestamp(t0, KST):%m-%d %H:%M} KST · {age_d}일 묵음 · 남은 예보 {left_h:.0f}시간"
    log(("⚠️ " if state != "ok" else "✅ ") + msg)
    gh_output(global_state=state, global_reason=msg)
    if state == "kept":
        gh_annot("warning", f"전 세계 조류 격자 오늘 못 바꿈 — 어제 것 유지({msg})")
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "publish", "check-live"])
    ap.add_argument("--out", default=os.environ.get("TIDAL_GLOBAL_OUT") or os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "tidal_global"))
    ap.add_argument("--hours", type=int, default=0, help="개발용: 시각 수 줄이기(올리기 거부)")
    a = ap.parse_args()
    if a.cmd == "build":
        try:
            build(a.out, a.hours)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:400]}"
            log(f"⚠️ 전 세계 조류 만들기 실패 — {msg} (공개된 이전 것 유지)")
            gh_annot("warning", f"전 세계 조류 격자 만들기 실패 — {msg} (이전 것 유지)")
            gh_output(global_build="fail")
            sys.exit(1)
    elif a.cmd == "publish":
        try:
            publish(a.out)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:400]}"
            log(f"⚠️ 전 세계 조류 올리기 실패 — {msg}")
            gh_annot("warning", f"전 세계 조류 격자 올리기 실패 — {msg}")
            gh_output(global_publish="fail")
            sys.exit(1)
    else:
        check_live()


if __name__ == "__main__":
    main()
