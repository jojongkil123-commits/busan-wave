# -*- coding: utf-8 -*-
"""
tidal_cmems.py — CMEMS SMOC 의 조석 유속(utide·vtide)을 원파일에서 바로 읽어 전국 격자로  [2026-10-09]
(2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국)

왜 (2026-10-09 검토 반영):
  윈디 '조류'(Tidal currents)는 CMEMS SMOC 의 조석 성분이다. 처음엔 Open-Meteo 가 주는 합성 해류(utotal)에서 저역통과로 느린 흐름을
  빼 조석을 추정했는데, 검토에서 두 가지가 실제로 확인됐다(같은 날 원파일 대조):
    ① 시각이 30분 밀림 — SMOC 시간값은 HH:30(예: 672960.5 h = 00:30Z)인데 Open-Meteo 가 HH:00 으로 잘라 붙인다(rms 0.023 vs 0.368 m/s).
    ② 조석이 약한 곳에 조석 아닌 흐름이 남음 — 동해 utide 중앙값 0.9 cm/s 인데 추정치는 9.0 cm/s(관성진동·바람·5 cm/s 양자화).
  원파일의 utide·vtide 를 그대로 쓰면 둘 다 없어지고(윈디와 같은 변수), Open-Meteo 호출 4,955번·62분 실행도 없어진다.

어디서 (키·로그인 없이 읽히는 CMEMS 공개 저장소 — 공식 copernicusmarine 도구가 쓰는 곳):
  STAC  https://stac.marine.copernicus.eu/metadata/GLOBAL_ANALYSISFORECAST_PHY_001_024/product.stac.json
        → 'cmems_mod_glo_phy_anfc_merged-uv_PT1H-i_*' 데이터셋 → assets.native.href (버킷 번호·버전이 바뀌어도 따라간다)
  원파일 <native>/YYYY/MM/SMOC_YYYYMMDD_RYYYYMMDD.nc — 하루 24시각(00:30Z … 23:30Z), 1/12° 전 지구(2041×4320), float32,
        조각(chunk) = (1,1,1021,2160) gzip+shuffle. 한반도 상자(32.75–38.75N, 124–132E)는 시각·변수마다 조각 1개(≈0.73 MB)에 들어간다.
  같은 날짜 파일이 여러 R(발표일)이면 가장 늦은 R 을 쓴다. 발표는 하루 1번(≈08:15Z), 예보는 약 10일.

어떻게 (작게 받기):
  h5py 로 파일 머리·조각 색인만 HTTP Range 로 읽고(파일당 수 MB), 필요한 조각의 바이트 범위만 병렬로 받아 zlib 풀기 + shuffle 되돌리기.
  96시간 × 2변수 + 앞뒤 여유 ≈ 200조각 ≈ 150 MB.

시각 맞추기 (HH:30 → HH:00, 계약 t0 는 00:00 KST 정각 — 앱이 t0 % 3600 == 0 을 검사한다):
  출력 시각 t 의 값 = (−a + 9b + 9c − d)/16, a·b·c·d = t−1.5h·t−0.5h·t+0.5h·t+1.5h 의 원값(3차 라그랑주 가운데 보간).
  M2 진폭 손실 0.15%(단순 평균 (b+c)/2 는 3.2%). 바깥 두 값이 없으면 단순 평균.

출력은 build_tidal.py 가 계약 꼴로 쓴다(이 모듈은 격자 값만 만든다). 필요한 것: numpy, h5py, requests.
"""
import json
import math
import os
import re
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import h5py
import numpy as np
import requests

UTC = timezone.utc
STAC_PRODUCT = "https://stac.marine.copernicus.eu/metadata/GLOBAL_ANALYSISFORECAST_PHY_001_024/product.stac.json"
DATASET_PREFIX = "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"
NATIVE_FALLBACK = ("https://s3.waw3-1.cloudferro.com/mdl-native-14/native/GLOBAL_ANALYSISFORECAST_PHY_001_024/"
                   "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i_202211")
UA = {"User-Agent": "busan-wave-tidal/2.0 (+https://github.com/jojongkil123-commits/busan-wave)"}
EPOCH1950 = datetime(1950, 1, 1, tzinfo=UTC)
WORKERS = 8


def _log(*a):
    print(" ".join(str(x) for x in a), flush=True)


_tls = threading.local()


def _session():
    s = getattr(_tls, "s", None)
    if s is None:
        s = _tls.s = requests.Session()
        s.headers.update(UA)
    return s


def _get(url, timeout=60, tries=4, **kw):
    """GET + 재시도(5xx·연결 실패). 4xx 는 바로 예외"""
    last = None
    for t in range(tries):
        try:
            r = _session().get(url, timeout=timeout, **kw)
            if r.status_code < 500:
                r.raise_for_status()
                return r
            last = f"HTTP {r.status_code}"
        except requests.HTTPError:
            raise
        except Exception as e:  # noqa: BLE001 — 타임아웃·연결
            last = f"{type(e).__name__}: {str(e)[:120]}"
        time.sleep(2 + 3 * t)
    raise RuntimeError(f"받기 실패 {url[-80:]} — {last}")


# ── 어디 있나 ──────────────────────────────────────────────────────────────

def native_base():
    """STAC 에서 SMOC(merged-uv, 1시간) 원파일 위치 — 실패하면 2026-10-09 확인한 주소"""
    try:
        prod = _get(STAC_PRODUCT, timeout=30).json()
        items = sorted(l["href"] for l in prod.get("links", []) if l.get("rel") == "item"
                       and l.get("href", "").startswith(DATASET_PREFIX + "_"))
        if items:
            ds_url = STAC_PRODUCT.rsplit("/", 1)[0] + "/" + items[-1]     # 버전(_YYYYMM)이 가장 늦은 것
            href = (_get(ds_url, timeout=30).json().get("assets", {}).get("native", {}) or {}).get("href")
            if href and href.startswith("https://"):
                return href.rstrip("/"), "stac"
    except Exception as e:  # noqa: BLE001
        _log(f"  STAC 못 읽음({type(e).__name__}: {str(e)[:100]}) → 고정 주소")
    return NATIVE_FALLBACK, "fallback"


def list_files(base, months):
    """{날짜 'YYYYMMDD': (R 'YYYYMMDD', url, 크기)} — 날짜마다 가장 늦은 R"""
    m = re.match(r"(https://[^/]+/[^/]+)/(.+)$", base)
    if not m:
        raise RuntimeError(f"원파일 주소 꼴 모름: {base}")
    endpoint, prefix0 = m.group(1), m.group(2)
    out = {}
    for ym in months:
        prefix, token = f"{prefix0}/{ym}/", None
        while True:
            q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                q["continuation-token"] = token
            t = _get(endpoint, params=q, timeout=30).text
            for key, size in re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", t, flags=re.S):
                f = re.search(r"SMOC_(\d{8})_R(\d{8})\.nc$", key)
                if f and (f.group(1) not in out or f.group(2) > out[f.group(1)][0]):
                    out[f.group(1)] = (f.group(2), f"{endpoint}/{key}", int(size))
            nxt = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", t)
            if "<IsTruncated>true</IsTruncated>" in t and nxt:
                token = nxt.group(1)
                continue
            break
    return out


class RangeFile:
    """h5py 가 파일 머리·조각 색인을 읽게 하는 HTTP Range 파일(1 MB 블록 캐시, 읽기 전용)"""

    def __init__(self, url, size, block=1 << 20):
        self.url, self.size, self.block, self.pos, self.cache, self.fetched = url, size, block, 0, {}, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return False

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def tell(self):
        return self.pos

    def _blk(self, b):
        if b not in self.cache:
            a = b * self.block
            e = min(self.size, a + self.block) - 1
            r = _get(self.url, timeout=60, headers={"Range": f"bytes={a}-{e}"})
            if len(r.content) != e - a + 1:
                raise RuntimeError(f"Range 응답 길이 {len(r.content)} ≠ {e - a + 1}")
            self.cache[b] = r.content
            self.fetched += len(r.content)
        return self.cache[b]

    def readinto(self, buf):
        if self.pos >= self.size:
            return 0
        n = min(len(buf), self.size - self.pos)
        got = 0
        while got < n:
            b, o = divmod(self.pos + got, self.block)
            d = self._blk(b)[o:o + n - got]
            buf[got:got + len(d)] = d
            got += len(d)
        self.pos += n
        return n

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        buf = bytearray(max(0, min(n, self.size - self.pos)))
        k = self.readinto(memoryview(buf))
        return bytes(buf[:k])

    def close(self):
        self.cache.clear()


# ── 읽기 ───────────────────────────────────────────────────────────────────

def _decode(raw, shuffle, shape):
    a = np.frombuffer(zlib.decompress(raw), dtype=np.uint8)
    if a.size != int(np.prod(shape)) * 4:
        raise RuntimeError(f"조각 크기 {a.size} ≠ {int(np.prod(shape)) * 4}")
    if shuffle:   # HDF5 shuffle: 1바이트째끼리·2바이트째끼리… 모아 둔 것 → 값마다 4바이트로 되돌린다
        a = a.reshape(4, -1).T.copy().reshape(-1)
    return a.view("<f4").reshape(shape)


def build(t0, n, box, workers=WORKERS):
    """CMEMS utide·vtide → 계약 격자 값.
    box = (minLat, maxLat, minLng, maxLng, rows, cols) — 1/12° 격자점(정확히 j/12).
    돌려줌: dict(spd, dir: 길이 rows*cols*n 정수 목록(row0=북, (r*cols+c)*n+k), sea: [bool], tu, tv: (rows, cols, n) cm/s float(육지 nan),
               info: meta 용)"""
    min_lat, max_lat, min_lng, max_lng, rows, cols = box
    t_start = time.time()
    base, how = native_base()
    _log(f"CMEMS 원파일 위치({how}): {base}")
    # 필요한 원값 시각(HH:30Z): 출력 t 마다 t−1.5h … t+1.5h
    t_need = list(range(t0 - 5400, t0 + 3600 * (n - 1) + 5400 + 1, 3600))
    days = sorted({datetime.fromtimestamp(t, UTC).strftime("%Y%m%d") for t in t_need})
    months = sorted({d[:4] + "/" + d[4:6] for d in days})
    files = list_files(base, months)
    have = [d for d in days if d in files]
    if not have:
        raise RuntimeError(f"원파일 없음 {days[0]}–{days[-1]} ({base})")
    _log(f"  원파일 {len(have)}/{len(days)}일: " + ", ".join(f"{d}(R{files[d][0]})" for d in have))

    # ① 파일마다 머리·좌표·조각 색인
    jobs = []            # (시각 t, 변수, url, 오프셋, 크기, shuffle, 조각모양, (lat 조각 시작, lon 조각 시작), 상자 안 자리)
    meta_bytes, fill, grid_ok = 0, None, None
    for d in have:
        _, url, size = files[d]
        rf = RangeFile(url, size)
        with h5py.File(rf, "r") as h:
            for v in ("utide", "vtide", "time", "latitude", "longitude"):
                if v not in h:
                    raise RuntimeError(f"{d}: 변수 {v} 없음")
            lat = h["latitude"][:].astype(float)
            lon = h["longitude"][:].astype(float)
            i0 = int(np.argmin(np.abs(lat - min_lat)))
            j0 = int(np.argmin(np.abs(lon - min_lng)))
            i1, j1 = i0 + rows - 1, j0 + cols - 1
            ok = (abs(lat[i0] - min_lat) < 1e-3 and abs(lat[i1] - max_lat) < 1e-3
                  and abs(lon[j0] - min_lng) < 1e-3 and abs(lon[j1] - max_lng) < 1e-3)
            if not ok:
                raise RuntimeError(f"{d}: 격자가 1/12° 계약점과 다름 lat {lat[i0]:.4f}–{lat[i1]:.4f} lon {lon[j0]:.4f}–{lon[j1]:.4f}")
            grid_ok = (round(float(lat[i0]), 4), round(float(lat[i1]), 4), round(float(lon[j0]), 4), round(float(lon[j1]), 4))
            tt = h["time"][:].astype(float)
            tunits = h["time"].attrs.get("units")
            tunits = tunits.decode() if isinstance(tunits, bytes) else str(tunits)
            if not tunits.startswith("hours since 1950-01-01"):
                raise RuntimeError(f"{d}: 시간 단위 {tunits}")
            tsec = [int(round((EPOCH1950 + timedelta(hours=x)).timestamp())) for x in tt]
            for name in ("utide", "vtide"):
                ds = h[name]
                if (ds.dtype != np.dtype("<f4") or ds.ndim != 4 or ds.compression != "gzip" or ds.fletcher32
                        or ds.scaleoffset is not None or ds.chunks is None or ds.chunks[0] != 1 or ds.chunks[1] != 1):
                    raise RuntimeError(f"{d}/{name}: 저장 꼴이 다름 {ds.dtype} {ds.chunks} {ds.compression}")
                fv = ds.attrs.get("_FillValue")
                fv = float(np.asarray(fv).ravel()[0]) if fv is not None else None
                fill = fv if fill is None else fill
                ch = ds.chunks
                lat_chunks = range((i0 // ch[2]) * ch[2], i1 + 1, ch[2])
                lon_chunks = range((j0 // ch[3]) * ch[3], j1 + 1, ch[3])
                for ti, t in enumerate(tsec):
                    if t not in t_need:
                        continue
                    for la0 in lat_chunks:
                        for lo0 in lon_chunks:
                            ci = ds.id.get_chunk_info_by_coord((ti, 0, la0, lo0))
                            if ci.filter_mask != 0:
                                raise RuntimeError(f"{d}/{name}: 일부 필터를 건너뛴 조각(filter_mask {ci.filter_mask})")
                            jobs.append((t, name, url, ci.byte_offset, ci.size, bool(ds.shuffle), (ch[2], ch[3]),
                                         (la0, lo0), (i0, i1, j0, j1)))
        meta_bytes += rf.fetched
    if not jobs:
        raise RuntimeError("받을 조각 없음")
    got_t = sorted({j[0] for j in jobs})
    _log(f"  조각 {len(jobs)}개(시각 {len(got_t)} × 2변수) · 색인 읽기 {meta_bytes / 1e6:.1f} MB · {time.time() - t_start:.0f}s")

    # ② 조각 바이트만 병렬로 받기
    U = {t: np.full((rows, cols), np.nan) for t in got_t}
    V = {t: np.full((rows, cols), np.nan) for t in got_t}
    lock = threading.Lock()
    nbytes = [0]

    def work(job):
        t, name, url, off, size, shuf, cshape, (la0, lo0), (i0, i1, j0, j1) = job
        r = _get(url, timeout=120, headers={"Range": f"bytes={off}-{off + size - 1}"})
        if len(r.content) != size:
            raise RuntimeError(f"조각 길이 {len(r.content)} ≠ {size}")
        a = _decode(r.content, shuf, cshape)
        # 이 조각이 덮는 상자 부분
        ra, rb = max(i0, la0), min(i1, la0 + cshape[0] - 1)
        ca, cb = max(j0, lo0), min(j1, lo0 + cshape[1] - 1)
        if ra > rb or ca > cb:
            return
        blk = a[ra - la0:rb - la0 + 1, ca - lo0:cb - lo0 + 1].astype(float)
        if fill is not None:
            blk[np.abs(blk) > 1e30] = np.nan
        blk[~np.isfinite(blk)] = np.nan
        dst = U[t] if name == "utide" else V[t]
        with lock:
            dst[ra - i0:rb - i0 + 1, ca - j0:cb - j0 + 1] = blk
            nbytes[0] += size

    t_dl = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, jobs))
    dl_s = time.time() - t_dl
    _log(f"  조각 받기 {nbytes[0] / 1e6:.1f} MB · {dl_s:.0f}s ({workers}갈래)")

    # ③ HH:30 → HH:00 (3차 가운데 보간, 바깥 값이 없으면 단순 평균) · cm/s · 북쪽 행부터
    tu = np.full((rows, cols, n), np.nan)
    tv = np.full((rows, cols, n), np.nan)
    linear_k = 0
    for k in range(n):
        t = t0 + 3600 * k
        if SHOW_SHIFT:   # (2026-10-11 조팀장 결정: 윈디와 같은 시각 +1시간) 윈디 표기 = 원파일 (t − SHOW_SHIFT + 30분) 값 그대로(보간 없음)
            src = t - SHOW_SHIFT + 1800
            if src in U:
                tu[:, :, k] = U[src][::-1, :] * 100.0
                tv[:, :, k] = V[src][::-1, :] * 100.0
            continue
        a, b, c, e = (t - 5400, t - 1800, t + 1800, t + 5400)
        if b not in U or c not in U:
            continue
        if a in U and e in U:
            cu = (-U[a] + 9 * U[b] + 9 * U[c] - U[e]) / 16.0
            cv = (-V[a] + 9 * V[b] + 9 * V[c] - V[e]) / 16.0
            lu, lv = (U[b] + U[c]) / 2.0, (V[b] + V[c]) / 2.0
            uu = np.where(np.isfinite(cu), cu, lu)        # 바깥 칸만 육지인 해안 칸은 단순 평균
            vv = np.where(np.isfinite(cv), cv, lv)
        else:
            uu, vv = (U[b] + U[c]) / 2.0, (V[b] + V[c]) / 2.0
            linear_k += 1
        tu[:, :, k] = uu[::-1, :] * 100.0                 # 원파일은 남→북 — 계약은 row0 = 북
        tv[:, :, k] = vv[::-1, :] * 100.0
    sea = np.isfinite(tu).sum(axis=2) >= 0.9 * n          # 육지·자료 없는 칸은 -1
    valid = np.isfinite(tu) & np.isfinite(tv) & sea[:, :, None]
    sp = np.where(valid, np.rint(np.hypot(tu, tv)), -1).astype(int)
    # (2026-10-10 조팀장 요청: 확대 시 방사형 흐름·약한 곳 멈춤 버그 — 윈디처럼) 0 인 성분은 부호를 살려 ±1/4 단위로 — 원자료가 1/1024 m/s 로
    #   반올림돼 동해 한가운데는 칸의 62% 가 정확히 ±0 벡터다. 그대로 atan2 하면 −0 은 180°, +0 은 0° 로 찍혀 방향이 남·북 둘로만 갈렸다.
    #   반올림돼 0 이 된 값의 평균 크기(단위의 1/4)를 부호대로 넣는다. 세기(spd)는 그대로라 1 cm/s 이상 칸 방향은 거의 안 바뀐다.
    q4 = (100.0 / 1024) / 4
    du = np.where(tu == 0, np.copysign(q4, tu), tu)
    dv = np.where(tv == 0, np.copysign(q4, tv), tv)
    dr = np.where(valid, np.rint(np.degrees(np.arctan2(du, dv))) % 360, -1).astype(int)
    dr[valid & (dr == 360)] = 0
    hours_missing = int((~np.isfinite(tu[sea])).sum()) if sea.any() else 0
    info = {
        "native_base": base, "native_found_by": how,
        "files": {d: {"R": files[d][0], "bytes": files[d][2]} for d in have},
        "bulletin_R": max(files[d][0] for d in have),
        "grid_check": {"lat": [grid_ok[0], grid_ok[1]], "lon": [grid_ok[2], grid_ok[3]]},
        "source_times": [datetime.fromtimestamp(got_t[0], UTC).isoformat(timespec="minutes"),
                         datetime.fromtimestamp(got_t[-1], UTC).isoformat(timespec="minutes")],
        "chunks": len(jobs), "chunk_bytes": nbytes[0], "index_bytes": meta_bytes,
        "download_s": round(dl_s, 1), "total_s": round(time.time() - t_start, 1), "workers": workers,
        "hh30_to_hh00": "3차 가운데 보간 (−a+9b+9c−d)/16, a..d = t−1.5h, t−0.5h, t+0.5h, t+1.5h (M2 손실 0.15%)",
        "hours_linear_only": linear_k, "sea_hours_missing": hours_missing,
    }
    return {"spd": sp.reshape(-1).tolist(), "dir": dr.reshape(-1).tolist(), "sea": sea.reshape(-1).tolist(),
            "tu": tu, "tv": tv, "info": info}


# ── 로그인 경로: 공식 copernicusmarine 도구(ARCO) ─────────────────────────────
# (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) 조팀장이 코페르니쿠스 마린 무료 계정을 만들었다 → 약관대로 로그인해서 받는다.
#   비밀값 CMEMS_USERNAME/CMEMS_PASSWORD → 워크플로가 COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD 로 넘긴다(도구가 환경변수를 읽는다).
#   ⚠️ 시각: 공식 도구(ARCO)는 원파일의 HH:30 값을 HH:00 으로 붙여 준다(같은 날 대조: ARCO HH:00 = 원파일 HH:30, rms 0.015 m/s).
#     어느 쪽이 맞나 — KHOA 조류예보 29곳(유속 ≥20 cm/s, 2,700시각)과 맞대 보니 ARCO 표기 그대로가 더 맞았다
#     (45° 안 71.1% · 반대 4.1%, 원파일 HH:30 기준 보간은 69.1% · 5.9%). 그래서 공식 도구 시각을 **그대로** 쓴다(보간 없음).
#     공식 도구로 받는 이용자(윈디 포함일 가능성이 크다)와 같은 시각 표기다.
# ⭐ 화면 시각 = 윈디 표기 (2026-10-11 조팀장 결정: 윈디와 같은 시각 +1시간)
#   10/10 윈디 캡처 대조(2,581점·두 날짜): 윈디 'T시' 그림 = 우리 예전 'T−1시' 그림(공식 도구 ARCO 라벨 T−1시 = 원파일 T−30분 값).
#   국립해양조사원 조류예보와는 예전 표기(이동 0)가 더 맞았지만(점수 0.785 vs 0.691) 조팀장이 '윈디와 똑같이'를 골랐다.
#   → 출력 시각 t 의 값 = ARCO 라벨 (t − SHOW_SHIFT) 값. 계약 t0(00:00 KST)·n 은 그대로. 되돌리려면 환경변수 TIDAL_SHOW_SHIFT=0.
SHOW_SHIFT = int(os.environ.get("TIDAL_SHOW_SHIFT", "3600"))
DATASET_ID = "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"


def _contract(tu, tv, n):
    """(rows, cols, n) cm/s 배열 → 계약 값(spd·dir 정수 목록, -1 = 육지·빈칸) + 바다 칸. build_toolbox·build_toolbox_multi 공통"""
    sea = np.isfinite(tu).sum(axis=2) >= 0.9 * n
    valid = np.isfinite(tu) & np.isfinite(tv) & sea[:, :, None]
    sp = np.where(valid, np.rint(np.hypot(tu, tv)), -1).astype(int)
    # (2026-10-10 조팀장 요청: 확대 시 방사형 흐름·약한 곳 멈춤 버그 — 윈디처럼) 0 인 성분은 부호를 살려 ±1/4 단위로 — 원자료가 1/1024 m/s 로
    #   반올림돼 동해 한가운데는 칸의 62% 가 정확히 ±0 벡터다. 그대로 atan2 하면 −0 은 180°, +0 은 0° 로 찍혀 방향이 남·북 둘로만 갈렸다.
    #   반올림돼 0 이 된 값의 평균 크기(단위의 1/4)를 부호대로 넣는다. 세기(spd)는 그대로라 1 cm/s 이상 칸 방향은 거의 안 바뀐다.
    q4 = (100.0 / 1024) / 4
    du = np.where(tu == 0, np.copysign(q4, tu), tu)
    dv = np.where(tv == 0, np.copysign(q4, tv), tv)
    dr = np.where(valid, np.rint(np.degrees(np.arctan2(du, dv))) % 360, -1).astype(int)
    dr[valid & (dr == 360)] = 0
    return sp, dr, sea


def _toolbox_fetch(t0, n, box):
    """공식 도구로 box(1/12° 격자점) 의 utide·vtide 를 계약 시각 그대로 → (tu, tv: (rows, cols, n) cm/s 북쪽 행부터, 육지 nan), info"""
    import copernicusmarine  # 워크플로에서 pip 설치. 없으면 ImportError → 부른 쪽이 다음 경로로
    if not (os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") and os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")):
        raise RuntimeError("코페르니쿠스 계정 환경변수 없음(CMEMS_USERNAME/CMEMS_PASSWORD 비밀값)")
    min_lat, max_lat, min_lng, max_lng, rows, cols = box
    t_start = time.time()
    src0 = t0 - SHOW_SHIFT                                  # (2026-10-11 조팀장 결정: 윈디와 같은 시각 +1시간) 출력 k = ARCO 라벨 src0 + k시간
    start = datetime.fromtimestamp(src0, UTC)
    end = datetime.fromtimestamp(src0 + 3600 * (n - 1), UTC)
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET_ID, variables=["utide", "vtide"],
        minimum_longitude=min_lng, maximum_longitude=max_lng, minimum_latitude=min_lat, maximum_latitude=max_lat,
        start_datetime=start.strftime("%Y-%m-%dT%H:%M:%S"), end_datetime=end.strftime("%Y-%m-%dT%H:%M:%S"))
    t_open = time.time() - t_start
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    lat = ds["latitude"].values.astype(float)
    lon = ds["longitude"].values.astype(float)
    if len(lat) != rows or len(lon) != cols or abs(lat.min() - min_lat) > 1e-3 or abs(lat.max() - max_lat) > 1e-3 \
            or abs(lon.min() - min_lng) > 1e-3 or abs(lon.max() - max_lng) > 1e-3:
        raise RuntimeError(f"격자가 계약과 다름 {len(lat)}×{len(lon)} lat {lat.min():.4f}–{lat.max():.4f} lon {lon.min():.4f}–{lon.max():.4f}")
    times = (ds["time"].values.astype("datetime64[s]").astype("int64")).tolist()
    want = [src0 + 3600 * k for k in range(n)]
    pos = {t: i for i, t in enumerate(times)}
    t_load0 = time.time()
    U = ds["utide"].transpose("time", "latitude", "longitude").values
    V = ds["vtide"].transpose("time", "latitude", "longitude").values
    t_load = time.time() - t_load0
    north_first = lat[0] > lat[-1]
    tu = np.full((rows, cols, n), np.nan)               # float64 — 예전 build_toolbox 와 같은 반올림(유속·방향 정수값이 바이트까지 같게)
    tv = np.full((rows, cols, n), np.nan)
    got = 0
    for k, t in enumerate(want):
        i = pos.get(t)
        if i is None:
            continue
        u, v = U[i], V[i]
        if not north_first:                               # ARCO 는 남→북 — 계약은 row0 = 북
            u, v = u[::-1, :], v[::-1, :]
        tu[:, :, k] = u * 100.0
        tv[:, :, k] = v * 100.0
        got += 1
    if got < n:
        raise RuntimeError(f"시각 {got}/{n}개만 있음 ({start:%m-%d %H}Z–{end:%m-%d %H}Z) — 예보가 아직 그만큼 안 나왔을 수 있음")
    lat_n = lat[::-1] if not north_first else lat                 # 북쪽 행부터의 위도(격자 맞춤 검사용)
    info = {
        "via": "copernicusmarine " + getattr(copernicusmarine, "__version__", "?") + " open_dataset (ARCO, 로그인)",
        "dataset_id": DATASET_ID,
        "source_times": [start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")],
        "time_label": "공식 도구 표기 그대로(HH:00) — 원파일 HH:30 값과 같은 값. KHOA 대조로 이쪽이 더 맞아 보간하지 않음",
        "request_box": {"minLat": min_lat, "maxLat": max_lat, "minLng": min_lng, "maxLng": max_lng, "rows": rows, "cols": cols},
        "chunks": str(ds["utide"].encoding.get("preferred_chunks") or ds["utide"].encoding.get("chunks") or "?"),
        "open_s": round(t_open, 1), "load_s": round(t_load, 1),
        "array_mb": round((U.nbytes + V.nbytes) / 1e6, 1),
        "total_s": round(time.time() - t_start, 1),
    }
    return tu, tv, lat_n, lon, info


def build_toolbox(t0, n, box):
    """공식 도구로 utide·vtide 를 계약 격자·시각 그대로 받는다. 돌려줌은 build() 와 같은 꼴."""
    tu, tv, _, _, info = _toolbox_fetch(t0, n, box)
    sp, dr, sea = _contract(tu, tv, n)
    info["sea_hours_missing"] = int((~np.isfinite(tu[sea])).sum()) if sea.any() else 0
    return {"spd": sp.reshape(-1).tolist(), "dir": dr.reshape(-1).tolist(), "sea": sea.reshape(-1).tolist(),
            "tu": tu, "tv": tv, "info": info}


# ── 한 번 받아 두 격자로 (2026-10-09 조팀장 요청: 최대한 윈디와 같게 — 가장자리 없이 전국) ─────────────────
# 왜: 전국 화면에서 색이 사각 상자(124–132E·32.75–38.75N)에서 뚝 끊겼다 — 윈디는 모든 바다를 칠한다.
#   ① 촘촘한 전국(core) 32.0–39.5N·123.0–132.5E 1/12° 91×115 — 앱이 부산·전국을 그리는 주 격자(KHOA 대조도 이것)
#   ② 넓은 동아시아(wide) 18–52N·115–150E 0.25° 137×141 — core 밖(중국·일본·대만·동해 끝·태평양)을 칠하는 성긴 격자
#      (검토 반영: 처음 24–44N·117–141E 는 동해 44N·태평양 141E 바다 한가운데에서 직선으로 끊겼다).
#      1/12° 격자점에서 세 칸마다(0.25° 의 정수배 위경도) 그대로 뽑는다 — 값을 섞거나 평균 내지 않는다.
# 받기: ARCO 조각이 (시각 1, 위도 512, 경도 2048) — 위도 5.33–47.92N 이 한 조각, 48.0N 부터 다음 조각, 경도 −9.33–161.25E 가 한 조각.
#   넓은 상자(18–52N)는 위도 조각 두 줄에 걸쳐 core 만 받을 때의 약 2배를 받는다(2026-10-09 실측: 1/12° 409×421×96h 를 한 번에 —
#   열기 7.8 s · 읽기 35 s · 받은 양 ≈ 0.24 GB · 배열 132 MB · 최대 메모리 ≈ 1.5 GB). 그래도 한 번만 받아 둘로 자른다.
def build_toolbox_multi(t0, n, fetch_box, outs):
    """fetch_box(1/12°)를 한 번 받아 outs 의 격자로 자른다.
    outs = {이름: (minLat, maxLat, minLng, maxLng, rows, cols, 몇 칸마다)} — 격자점이 1/12° 격자에 정확히 있어야 한다(아니면 예외).
    돌려줌 = {이름: build_toolbox 와 같은 꼴}, 받기 info"""
    tu, tv, lat_n, lon, info = _toolbox_fetch(t0, n, fetch_box)
    res = {}
    for name, (min_lat, max_lat, min_lng, max_lng, rows, cols, step) in outs.items():
        r0 = int(np.argmin(np.abs(lat_n - max_lat)))
        c0 = int(np.argmin(np.abs(lon - min_lng)))
        rs = slice(r0, r0 + (rows - 1) * step + 1, step)
        cs = slice(c0, c0 + (cols - 1) * step + 1, step)
        la, lo = lat_n[rs], lon[cs]
        if (len(la) != rows or len(lo) != cols or abs(la[0] - max_lat) > 1e-3 or abs(la[-1] - min_lat) > 1e-3
                or abs(lo[0] - min_lng) > 1e-3 or abs(lo[-1] - max_lng) > 1e-3
                or np.abs(np.diff(la) + step / 12.0).max() > 1e-3 or np.abs(np.diff(lo) - step / 12.0).max() > 1e-3):
            raise RuntimeError(f"{name}: 격자점이 1/12° 격자와 안 맞음 {len(la)}×{len(lo)} lat {la[0]:.4f}…{la[-1]:.4f} lon {lo[0]:.4f}…{lo[-1]:.4f}")
        su, sv = tu[rs, cs, :].astype(float), tv[rs, cs, :].astype(float)
        sp, dr, sea = _contract(su, sv, n)
        sub = dict(info, grid_check={"lat": [round(float(la[0]), 4), round(float(la[-1]), 4)],
                                     "lon": [round(float(lo[0]), 4), round(float(lo[-1]), 4)], "every": step},
                   sea_hours_missing=int((~np.isfinite(su[sea])).sum()) if sea.any() else 0)
        res[name] = {"spd": sp.reshape(-1).tolist(), "dir": dr.reshape(-1).tolist(), "sea": sea.reshape(-1).tolist(),
                     "tu": su, "tv": sv, "info": sub}
    return res, info
