#!/usr/bin/env python3
"""
지도 바람·파도·수온 텍스처 — **ECMWF open data (IFS 0.25°, CC BY 4.0)** → u/v PNG 텍스처 + 메타 JSON.

(2026-10-14 조팀장 요청: 지도 바람·파도·수온을 윈디처럼 ECMWF 로) 예전 원본은 NOAA GFS · GFS-Wave(NOMADS) 였다.
  되돌리기: _backup/ecmwf1014/build_wave_texture.py.orig (또는 git 이력) 를 이 자리에 다시 두면 된다 — 파일 이름·형식이 같다.

자료: https://data.ecmwf.int/forecasts/<YYYYMMDD>/<HH>z/ifs/0p25/{oper,wave}/  (키 불필요, CC BY 4.0 — 출처 'ECMWF' 표기 의무)
  · oper(대기): 10u·10v(10m 바람), skt(표면 온도 — 바다 칸 = 수온), lsm(육지 비율, 수온 육지 칸 지우기)
  · wave(파도 모델 WAM): swh(유의파고), mwd(평균 파향, 오는 쪽)
  · 00/12Z 런: 0~144h 3시간 + 150~360h 6시간 · 06/18Z 런: 0~144h 3시간뿐
  · 파일 한 개가 140MB 라 통째로 받지 않는다 — 같은 이름의 .index(JSON 줄)에서 필요한 변수의 바이트 구간만 Range 로 받는다.

출력(앱·PWA 가 읽는 형식 — **예전과 이름·필드 그대로**, 아이폰 1.3.0·안드로이드 1.0.14/1.0.16 이 그대로 읽는다):
  data/wind_tHHH.png·_meta.json      R=u, G=v(화면좌표 남+), A=유효   (landOk=true, 육지 포함)
  data/wave_fill_tHHH.png·_meta.json R/G=파고×진행방향, A=바다(해안 5겹 채움 — 범위는 예전 그대로, 값은 해안 2겹 채움 위에서)
  data/sst_tHHH.png·_meta.json       R=수온°C(0~32), G=0, A=바다(해안 2겹 채움)
  data/wx_steps.json                 {run, runIso, stepHours, valid, nowIdx}
  data/wind.png·wave_fill.png·sst.png(+meta) = '지금'에 가장 가까운 스텝 (구버전 앱), data/wave.png = f000 (PWA, 해안 2겹 채움까지만)
  (2026-10-15 조팀장 결정: 해안 칸 채우기) 파도 모델(WAM)이 육지로 치는 해안 칸(기장 대변·서귀포 앞 등)을 이웃 바다 칸 평균으로 2겹 채운다
     — 물이 1/4 넘는 칸(lsm<0.75)만. 내륙 호수·반도 안쪽은 안 채운다. WAVE_COAST_* WHY 참고.
  ⚠️ 바뀐 것: 스텝이 1시간 → **3시간**(0~144h) · 6시간(150~354h). 앱은 wx_steps.json 의 stepHours 를 그대로 따른다
     (아이폰 WxTimelineBar·안드로이드 MapScreen 모두 목록을 읽어 쓰고, 지도는 스텝 사이를 연속 보간한다 — 2026-10-14 하네스로 확인).
  ⚠️ 고해상 파도(wave_fine_tHHH, GFS-Wave 0.1667°)는 ECMWF 에 없다 → 만들지 않고 지운다. 앱은 404 를 보면 전세계본(wave_fill)으로
     바로 넘어간다(kakao_map.html loadWeatherTexture, 2026-09-16~ 모든 판에 있음).

런 고르기: 발표가 끝난(마지막 스텝까지 올라온) 가장 최근 런. 06/18Z 런이면 0~144h 는 그 런, 150h~ 는 6시간 앞 00/12Z 런의
  같은 시각(그 런의 +6h 스텝)으로 이어 붙여 늘 15일(354h)을 채운다 — 모든 파일의 meta.run 은 기준 런 하나(앱의 런 비교 MAP-9 가 헷갈리지 않게),
  이어 붙인 칸은 srcRun·srcStep 으로 남긴다.

사용:
  python3 build_wave_texture.py                 # 최신 런 → data/ (이미 같은 런이면 건너뜀)
  python3 build_wave_texture.py --check          # 받을 런만 확인(JSON 한 줄): {"run":..,"published":..,"need":true|false}
  python3 build_wave_texture.py --force --out DIR --max-steps N   # 시험(다른 폴더·스텝 N개만)
필요: pip install eccodes numpy pillow   (eccodes wheel 에 CCSDS 압축 해제 포함)
"""
import sys, os, json, math, time, argparse, datetime as dt, urllib.request, urllib.error, shutil, re
from concurrent.futures import ThreadPoolExecutor

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

# (2026-10-14 조팀장 요청: ECMWF) 스텝 — ECMWF open data 가 주는 그대로. 06/18Z 런도 같은 목록이 되게 354h 에서 끊는다
#   (00/12Z 의 360h 하나를 버리는 대신 파일 이름이 매 런 같아서, 런마다 생겼다 지워졌다 하는 파일이 없다).
STEP_HOURS = list(range(0, 145, 3)) + list(range(150, 355, 6))      # 49 + 35 = 84 스텝
TAIL_FROM = 150                                                     # 06/18Z 런에서 앞 런으로 이어 붙이는 첫 시각

# 받는 곳 — 원본(data.ecmwf.int)이 제일 빠르고, 막히면 같은 경로의 클라우드 사본으로 (ECMWF 공식 사본: AWS·Google)
SOURCES = [s for s in os.environ.get("ECMWF_SOURCES",
           "https://data.ecmwf.int/forecasts,"
           "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com,"
           "https://storage.googleapis.com/ecmwf-open-data").split(",") if s]
UA = {"User-Agent": "busan-wave (Skindive map textures; github.com/jojongkil123-commits/busan-wave)"}
ATTR = "ECMWF (CC BY 4.0)"
OPER_PARAMS = ("10u", "10v", "skt")
WAVE_PARAMS = ("swh", "mwd")
SST_SEA_LSM_MAX = 0.15          # 수온: 이 육지 비율 미만만 바다 칸 (build_sst_step WHY)
# (2026-10-15 조팀장 결정: 해안 칸 채우기) 파도 해안 채우기 — WAM 이 육지로 친 칸 중 육지 비율(IFS lsm)이 이 미만인 칸만,
#   바다 칸에서 이 겹 수까지 이웃 평균으로 채운다(수온 채우기와 같은 방식, 단 물이 있는 칸만 → 육지 안쪽·내륙 호수로 안 번진다).
#   WHY 0.75·2겹 (2026-10-14 12Z f000, 0.5/0.75/0.85/0.95 × 1/2겹 비교): 가장 가까운 파도 칸 해운대 18.9→13.1km · 기장 대변 24.5→3.8 ·
#     서귀포 26.1→6.0 · 강릉 25.9→4.9 (목포 5.6·포항 10.9 그대로), 부산·기장 앞 PWA 표시 21.0→38.5%(옛 GFS 38.5%와 같음).
#     0.5 면 서귀포가 17.8km 로 남고, 0.85 이상은 부산은 같고 남해 섬 사이 육지 많은 칸(PWA 는 해안선으로 안 자른다)까지 들어간다.
#     육지 비율 1.0(문턱 없음)이면 부산 앞 80~100% 지만 시내·반도 위까지 파도가 그려진다 → 안 씀.
WAVE_COAST_LSM_MAX = 0.75
WAVE_COAST_ITERS = 2
STEP_RE = re.compile(r"^(wind|wave_fill|wave_fine|sst)_t(\d{3})(\.png|_meta\.json)$")


# ---------------------------------------------------------------- 받기
def _get(url, headers=None, timeout=90):
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    return urllib.request.urlopen(req, timeout=timeout).read()

def _path(run, stream, step, ext):
    d = run.strftime("%Y%m%d"); hh = run.strftime("%H")
    return f"{d}/{hh}z/ifs/0p25/{stream}/{d}{hh}0000-{step}h-{stream}-fc.{ext}"

def _exists(url, timeout=10):
    # (2026-10-14 조팀장 요청: ECMWF — 리뷰 수정) HEAD 는 10초만 기다린다 — 멈춘 곳 하나가 확인을 12×30초씩 늘리지 않게
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        return urllib.request.urlopen(req, timeout=timeout).status == 200
    except Exception:
        return False

def last_step(run):
    return 360 if run.hour in (0, 12) else 144

def run_complete(run, sources=None):
    """이 런의 oper·wave 마지막 스텝 .index 가 올라왔나 (ECMWF 는 스텝 순서로 올린다 → 마지막이 있으면 전부 있다)."""
    for base in (sources or SOURCES[:1]):
        if all(_exists(f"{base}/{_path(run, s, last_step(run), 'index')}") for s in ("oper", "wave")):
            return True
    return False

def latest_complete_run(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    t = now.replace(minute=0, second=0, microsecond=0)
    t -= dt.timedelta(hours=t.hour % 6)
    for _ in range(12):                      # 최대 3일 전까지
        # (2026-10-14 조팀장 요청: ECMWF — 리뷰 수정) 원본만 보지 않고 사본(AWS·Google)까지 — 원본이 막혀도 새 런을 찾는다
        if run_complete(t, SOURCES):
            return t
        t -= dt.timedelta(hours=6)
    raise RuntimeError("발표가 끝난 ECMWF 런을 3일 안에서 못 찾음")

def fetch_fields(run, stream, step, params, tries=3):
    """.index 에서 params 의 바이트 구간만 받아 GRIB2 바이트로 (원본 → 사본 순서로, 구간마다 재시도)."""
    last = None
    for attempt in range(tries):
        for base in SOURCES:
            try:
                idx = [json.loads(l) for l in _get(f"{base}/{_path(run, stream, step, 'index')}", timeout=60)
                       .decode().splitlines() if l.strip()]
                recs = [r for r in idx if r.get("param") in params and r.get("levtype", "sfc") == "sfc"]
                got = {r["param"] for r in recs}
                if got != set(params):
                    raise RuntimeError(f"{stream} +{step}h 변수 빠짐: {sorted(set(params) - got)}")
                url = f"{base}/{_path(run, stream, step, 'grib2')}"
                out = b""
                for r in sorted(recs, key=lambda r: r["_offset"]):
                    a, n = r["_offset"], r["_length"]
                    chunk = _get(url, {"Range": f"bytes={a}-{a + n - 1}"})
                    if len(chunk) != n or chunk[:4] != b"GRIB":
                        raise RuntimeError(f"구간 길이/머리 이상 {len(chunk)}/{n}")
                    out += chunk
                return out
            except Exception as e:
                last = f"{base}: {e}"
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{stream} +{step}h 받기 실패 — {last}")


# ---------------------------------------------------------------- GRIB → 배열
def read_grib(data):
    import eccodes as ec
    import numpy as np
    tmp = os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", f"_ecmwf_{os.getpid()}_{id(data)}.grib2")
    with open(tmp, "wb") as fh:
        fh.write(data)
    fields = {}; meta = {}
    try:
        with open(tmp, "rb") as f:
            while True:
                gid = ec.codes_grib_new_from_file(f)
                if gid is None:
                    break
                sn = ec.codes_get(gid, "shortName")
                Ni = ec.codes_get(gid, "Ni"); Nj = ec.codes_get(gid, "Nj")
                miss = ec.codes_get(gid, "missingValue")
                vals = ec.codes_get_values(gid).reshape(Nj, Ni).astype("float64")
                vals[vals == miss] = float("nan")
                if ec.codes_get(gid, "jScansPositively") == 1:     # 남→북이면 뒤집어 북쪽이 위로
                    vals = vals[::-1, :]
                lo1 = ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
                la1 = ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
                la2 = ec.codes_get(gid, "latitudeOfLastGridPointInDegrees")
                dx = 360.0 / Ni
                fields[sn] = vals
                meta.update(width=Ni, height=Nj, lon0=lo1, dx=dx,
                            south=min(la1, la2), north=max(la1, la2))
                ec.codes_release(gid)
    finally:
        try: os.remove(tmp)
        except OSError: pass
    # 경도를 -180 부터로 맞춘다. ECMWF 는 첫 칸이 180°(= -180°)라 그대로, 0° 시작(GFS 식)이면 반 바퀴 돌린다.
    lon0 = ((meta["lon0"] + 180.0) % 360.0) - 180.0          # 180 → -180, 0 → 0
    if abs(lon0 - 0.0) < 1e-6:
        half = meta["width"] // 2
        for k in fields:
            fields[k] = np.concatenate([fields[k][:, half:], fields[k][:, :half]], axis=1)
        lon0 = -180.0
    if abs(lon0 + 180.0) > 1e-6:
        raise RuntimeError(f"예상 밖 격자 시작 경도 {meta['lon0']}")
    meta["west"] = -180.0
    meta["east"] = -180.0 + (meta["width"] - 1) * meta["dx"]   # 0.25° → 179.75 (예전 GFS 메타와 같은 값)
    return fields, meta


# ---------------------------------------------------------------- 텍스처
def _shift(a, dy, dx, fill=0.0):
    """wrap 없는 2D 시프트 (np.roll은 반대편 끝 값이 새어 들어와 부적합)."""
    import numpy as np
    h, w = a.shape
    out = np.full_like(a, fill)
    out[max(dy,0):h+min(dy,0), max(dx,0):w+min(dx,0)] = \
        a[max(-dy,0):h+min(-dy,0), max(-dx,0):w+min(-dx,0)]
    return out

def fill_coastal(u, v, ok, iters=5, allow=None):   # 전세계라 5회(≈125km)만 — 해안 공백 메우되 내륙 번짐 최소
    """유효(바다) 값을 육지 쪽으로 반복 확산 — 0.25° 격자의 육지 칸 탓에 해안 앞바다가
    뚝 끊기는 공백을 없앤다. 실제 해안 경계는 앱이 벡터 해안선으로 잘라낸다.
    allow(불리언 격자)를 주면 그 칸으로만 번진다(파도 해안 채우기: 물이 있는 칸만, 2026-10-15)."""
    import numpy as np
    u = u.copy(); v = v.copy(); ok = ok.copy()
    for _ in range(iters):
        if ok.all():
            break
        cnt = np.zeros(ok.shape); su = np.zeros(ok.shape); sv = np.zeros(ok.shape)
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            so = _shift(ok.astype(float), dy, dx)
            cnt += so
            su += _shift(u, dy, dx) * so
            sv += _shift(v, dy, dx) * so
        new = (~ok) & (cnt > 0)
        if allow is not None:
            new &= allow
        u[new] = su[new] / cnt[new]; v[new] = sv[new] / cnt[new]
        ok = ok | new
    return u, v, ok

def _dilate(ok, iters):
    """불리언 격자를 8방향으로 iters 칸 넓힌다 (fill_coastal 이 닿는 범위와 같다 — 값 없이 범위만)."""
    out = ok.copy()
    for _ in range(iters):
        nb = out.copy()
        for dy, dx in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            nb |= _shift(out, dy, dx, fill=False)
        out = nb
    return out

def save_texture(out_dir, u, v, ok, meta, name, extra_meta):
    """u/v(실단위) → R=u, G=v, A=유효 인코딩 PNG + meta JSON. (형식은 예전 GFS 판과 한 글자도 같게)"""
    import numpy as np
    from PIL import Image
    h, w = u.shape
    umin, umax = float(np.min(u[ok])), float(np.max(u[ok]))
    vmin, vmax = float(np.min(v[ok])), float(np.max(v[ok]))
    ur = (u - umin) / (umax - umin + 1e-6)
    vr = (v - vmin) / (vmax - vmin + 1e-6)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    # (2026-10-14 조팀장 요청: ECMWF) 반올림 — 예전엔 버림(astype)이라 값이 반 칸(바람 ≈0.1m/s·파고 ≈0.03m)씩 늘 작게 나왔다
    #   (Open-Meteo 같은 격자점 대조 평균 −0.08m/s·−0.03m). 앱 복원식(uMin + R·폭/255)은 그대로라 옛 앱도 그대로 읽는다.
    rgba[..., 0] = np.clip(np.rint(ur * 255), 0, 255).astype(np.uint8)
    rgba[..., 1] = np.clip(np.rint(vr * 255), 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(ok, 255, 0).astype(np.uint8)
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(os.path.join(out_dir, f"{name}.png"), optimize=True)   # 최대 압축(6 대비 −8%, 장당 +0.5초) — 저장소·앱 데이터 절약
    out_meta = dict(width=w, height=h, uMin=umin, uMax=umax, vMin=vmin, vMax=vmax,
                    west=meta["west"], east=meta["east"], south=meta["south"], north=meta["north"],
                    **extra_meta)
    with open(os.path.join(out_dir, f"{name}_meta.json"), "w") as fh:
        json.dump(out_meta, fh, ensure_ascii=False, indent=1)
    return out_meta

def wave_uv(fields):
    """swh·mwd(오는 쪽, 도) → 진행 방향 × 파고. 화면 좌표(동+x, 남+y) — 예전 GFS dirpw 와 같은 규약."""
    import numpy as np
    swh = fields.get("swh"); mwd = fields.get("mwd")
    if swh is None or mwd is None:
        raise RuntimeError(f"swh/mwd 누락: {list(fields)}")
    sea = ~np.isnan(swh) & ~np.isnan(mwd)
    th = np.deg2rad(np.nan_to_num(mwd))
    u = np.where(sea, np.nan_to_num(swh) * -np.sin(th), 0.0)
    v = np.where(sea, np.nan_to_num(swh) *  np.cos(th), 0.0)
    return u, v, sea, float(np.nanmax(swh))

def wave_coast_fill(u, v, sea, lsm):
    """(2026-10-15 조팀장 결정: 해안 칸 채우기) WAM 바다 칸 → 해안 쪽 WAVE_COAST_ITERS 겹, 육지 비율 < WAVE_COAST_LSM_MAX 칸만.
    lsm 이 없거나 격자가 다르면 채우지 않는다(예전과 같음)."""
    if lsm is None or lsm.shape != sea.shape:
        if lsm is not None:
            print(f"  ⚠️ lsm 격자 {lsm.shape} ≠ 파도 격자 {sea.shape} — 해안 채우기 건너뜀")
        return u, v, sea
    import numpy as np
    allow = np.nan_to_num(lsm, nan=1.0) < WAVE_COAST_LSM_MAX
    return fill_coastal(u, v, sea, iters=WAVE_COAST_ITERS, allow=allow)

def build_wave_step(out_dir, fields, meta, fh, extra, lsm=None):
    u, v, sea0, mx = wave_uv(fields)
    u, v, sea = wave_coast_fill(u, v, sea0, lsm)          # 해안 2겹(물 있는 칸만) — wave.png(PWA)·wave_fill 공통 바탕
    cf = dict(coastFill=dict(iters=WAVE_COAST_ITERS, lsmMax=WAVE_COAST_LSM_MAX, cells=int((sea & ~sea0).sum()))) if lsm is not None else {}
    uf, vf, okf = fill_coastal(u, v, sea)
    okf &= _dilate(sea0, 5)   # 앱이 그리는 칸(5겹)은 예전과 똑같이 — 해안 2겹 덕에 더 안쪽(내륙·호수)까지 번지지 않게. 값만 해안 채움을 따른다
    save_texture(out_dir, uf, vf, okf, meta, f"wave_fill_t{fh:03d}",
                 dict(maxWaveM=mx, filled=True, fh=fh, source=f"{ATTR} IFS-WAM swh+mwd", **cf, **extra))
    return (u, v, sea, mx, cf)

def build_wind_step(out_dir, fields, meta, fh, extra):
    """10m 바람(육지 포함 전 지구). GRIB u=동+, v=북+ → 화면좌표(v=남+)로 부호 반전."""
    import numpy as np
    ug = fields.get("10u"); vg = fields.get("10v")
    if ug is None or vg is None:
        raise RuntimeError(f"10u/10v 누락: {list(fields)}")
    ok = ~np.isnan(ug) & ~np.isnan(vg)
    u = np.nan_to_num(ug); v = -np.nan_to_num(vg)
    ws = np.sqrt(u * u + v * v)
    save_texture(out_dir, u, v, ok, meta, f"wind_t{fh:03d}",
                 dict(maxWindMs=float(np.nanmax(ws)), landOk=True, fh=fh, source=f"{ATTR} IFS 10m wind", **extra))

def build_sst_step(out_dir, fields, meta, lsm, fh, extra):
    """skt(표면 온도) 의 바다 칸 = 수온. 스칼라(°C)를 u 에, v=0. 앱은 m=|u|/32 로 값 복원.
    (2026-10-14 조팀장 요청: ECMWF) 육지 비율 15% 이상 칸은 지우고 해안 쪽 2겹만 이웃 바다 칸 평균으로 채운다
    → 해안 앞 픽셀에 육지 온도(낮 30°C·밤 15°C)가 섞이던 GFS 판의 띠가 없다 (9/24 감사 MAP-3 과 같은 처리).
    WHY 15%: skt 는 칸 안 육지·바다 타일의 평균이라 해안 칸에 육지 낮밤이 섞인다. 2026-10-13 12Z 런 한반도 주변(30~45N·118~135E)
      15시−03시(KST) skt 차: 육지비율 0 → −0.2°C, 0.05~0.15 → 0.0(±0.7), 0.15~0.3 → +0.7(최대 +5.8), 0.3~0.5 → +3.2(최대 +12.5).
      앱 sstStripLand 가 GFS 로 고른 문턱(0.15)과 같다."""
    import numpy as np
    t = fields.get("skt")
    if t is None:
        raise RuntimeError(f"skt 누락: {list(fields)}")
    c = t - 273.15
    ok = ~np.isnan(c) & (c > -5) & (c < 45)
    sea = ok & (lsm < SST_SEA_LSM_MAX)
    max_c = float(np.nanmax(np.where(sea, c, np.nan)))
    u = np.where(sea, np.clip(c, 0, 32), 0.0)
    v = np.zeros_like(u)
    u, v, sea2 = fill_coastal(u, v, sea, iters=2)
    save_texture(out_dir, u, v, sea2, meta, f"sst_t{fh:03d}",
                 dict(maxSstC=max_c, fh=fh, sst=True, landMasked=True,
                      source=f"{ATTR} IFS skin temperature over sea (lsm<{SST_SEA_LSM_MAX})", **extra))


# ---------------------------------------------------------------- 실행
def run_str(run):
    return run.strftime("%Y%m%d %HZ")

def parse_run(rs):
    """'20261013 18Z' → UTC datetime (모르면 None)"""
    try:
        return dt.datetime.strptime(rs, "%Y%m%d %HZ").replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None

def need_build(run, pub, pub_src, force=False):
    """(2026-10-14 조팀장 요청: ECMWF — 리뷰 수정) 새로 만들지: 올라간 것보다 **더 새로운** 런일 때만.
    확인 한 번이 실패해 더 옛 런을 '최신'으로 잡아도, 올라간 새 자료를 옛 자료로 덮지 않는다(그때는 건너뛴다).
    올라간 것이 ECMWF 가 아니거나(옛 GFS) 런을 모르면 만든다."""
    if force:
        return True
    p = parse_run(pub) if pub else None
    if p is None or not (pub_src or "").startswith("ECMWF"):
        return True
    return run > p

def published_run(path):
    """올라가 있는 wx_steps.json(파일 경로)의 (run, source). 없으면 (None, '')."""
    try:
        with open(path) as fh:
            j = json.load(fh)
        return j.get("run"), j.get("source", "")
    except Exception:
        return None, ""

def plan(run):
    """기준 런의 스텝마다 (받을 런, 받을 스텝). 06/18Z 는 150h~ 를 6시간 앞 00/12Z 런에서."""
    prev = run - dt.timedelta(hours=6) if run.hour in (6, 18) else None
    out = []
    for fh in STEP_HOURS:
        if prev is not None and fh >= TAIL_FROM:
            out.append((fh, prev, fh + 6))
        else:
            out.append((fh, run, fh))
    return prev, out

def run_all(out_dir, force=False, max_steps=None, workers=6):
    import numpy as np
    t_start = time.time()
    run = latest_complete_run()
    rs = run_str(run)
    pub, pub_src = published_run(os.path.join(out_dir, "wx_steps.json"))
    if not need_build(run, pub, pub_src, force):
        print(f"올라간 런({pub})이 찾은 런({rs})과 같거나 더 새로움 — 건너뜀")
        return False
    prev, steps = plan(run)
    if prev is not None and not run_complete(prev, SOURCES):
        raise RuntimeError(f"이어 붙일 앞 런 {run_str(prev)} 이 없다")
    if max_steps:
        steps = steps[:max_steps]
    print(f"런: {rs}" + (f" (150h~ 는 {run_str(prev)} +6h 스텝)" if prev else "") + f" · 스텝 {len(steps)}개 · 받는 곳 {SOURCES[0]}")

    # 육지 비율(lsm, 고정장) — 기준 런 f000 에서 한 번
    lf, _ = read_grib(fetch_fields(run, "oper", 0, ("lsm",)))
    lsm = lf["lsm"]

    def dl(item):
        fh, r, s = item
        t0 = time.time()
        try:
            return fh, r, s, fetch_fields(r, "oper", s, OPER_PARAMS), fetch_fields(r, "wave", s, WAVE_PARAMS), time.time() - t0, None
        except Exception as e:
            return fh, r, s, None, None, time.time() - t0, e

    ok_hours = []; wave_first = None; nbytes = 0; failed = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fh, r, s, od, wd, sec, err in ex.map(dl, steps):     # 결과는 스텝 순서대로(받기는 workers 개씩 앞서 간다, 스텝당 ≈4MB)
            if err is not None:
                print(f"  ⚠️ t+{fh}h 받기 실패 — 건너뜀: {err}")
                failed.append(fh)
                continue
            nbytes += len(od) + len(wd)
            of, om = read_grib(od); wf, wm = read_grib(wd)
            extra = dict(run=rs)
            if r != run:
                extra.update(srcRun=run_str(r), srcStep=s)
            res = build_wave_step(out_dir, wf, wm, fh, extra, lsm)
            build_wind_step(out_dir, of, om, fh, extra)
            build_sst_step(out_dir, of, om, lsm, fh, extra)
            if fh == 0:
                wave_first = (wm, res)
            ok_hours.append(fh)
            print(f"  t+{fh:3d}h ({run_str(r)} +{s}h) 받기 {sec:4.1f}s · 파고최대 {res[3]:.1f}m · 해안 채움 {res[4].get('coastFill', {}).get('cells', 0)}칸")
    if not ok_hours or (not max_steps and len(ok_hours) < 0.9 * len(steps)):
        raise RuntimeError(f"스텝이 너무 많이 빠짐 ({len(ok_hours)}/{len(steps)}) — 이번 런은 올리지 않는다(예전 파일 그대로)")

    # '지금'에 가장 가까운 스텝 → 레거시 파일명(wave_fill/wind/sst) (구버전 앱·PWA 호환)
    now = dt.datetime.now(dt.timezone.utc)
    now_idx = min(range(len(ok_hours)), key=lambda i: abs((run + dt.timedelta(hours=ok_hours[i]) - now).total_seconds()))
    nh = ok_hours[now_idx]
    for src, dst in ((f"wave_fill_t{nh:03d}", "wave_fill"), (f"wind_t{nh:03d}", "wind"), (f"sst_t{nh:03d}", "sst")):
        shutil.copy(os.path.join(out_dir, src + ".png"), os.path.join(out_dir, dst + ".png"))
        shutil.copy(os.path.join(out_dir, src + "_meta.json"), os.path.join(out_dir, dst + "_meta.json"))
    print(f"기본본(now) = t+{nh}h")

    # 레거시 wave.png (PWA 부산파고 — 5겹 채움 없는 바다 마스크판, f000. 2026-10-15~ 해안 2겹 채움은 들어간다 — PWA 는 해안선으로 안 자르므로 물 있는 칸만)
    if wave_first:
        wm, (u, v, sea, mx, cf) = wave_first
        save_texture(out_dir, u, v, sea, wm, "wave", dict(maxWaveM=mx, run=rs, source=f"{ATTR} IFS-WAM swh+mwd", **cf))

    # 이번 목록에 없는 스텝 파일(옛 1시간 스텝·GFS 고해상 wave_fine·실패한 스텝의 옛 것)은 지운다 — 다른 런 격자가 섞이지 않게
    keep = set(ok_hours); removed = 0
    for fn in os.listdir(out_dir):
        m = STEP_RE.match(fn)
        if m and (m.group(1) == "wave_fine" or int(m.group(2)) not in keep):
            os.remove(os.path.join(out_dir, fn)); removed += 1

    valid = [(run + dt.timedelta(hours=h)).isoformat().replace("+00:00", "Z") for h in ok_hours]
    man = dict(run=rs, runIso=run.isoformat().replace("+00:00", "Z"),
               stepHours=ok_hours, valid=valid, nowIdx=now_idx,
               source=ATTR, model="ECMWF IFS 0.25° (oper 10u/10v/skt+lsm, wave swh/mwd)")
    if prev is not None:
        man["tail"] = dict(fromHour=TAIL_FROM, srcRun=run_str(prev))
    if failed:
        man["missing"] = failed
    with open(os.path.join(out_dir, "wx_steps.json"), "w") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    print(f"✅ wx_steps.json 스텝 {len(ok_hours)}개, nowIdx={now_idx}, 받은 양 {nbytes/1e6:.0f}MB, "
          f"지운 옛 파일 {removed}개, {time.time() - t_start:.0f}초")
    return True

def check(published_path):
    run = latest_complete_run()
    pub, src = published_run(published_path)
    p = parse_run(pub) if pub else None
    print(json.dumps(dict(run=run_str(run), published=pub, publishedSource=src,
                          older=bool(p and src.startswith("ECMWF") and run < p),
                          need=need_build(run, pub, src)), ensure_ascii=False))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--published", help="--check 때 비교할 wx_steps.json 경로(없으면 --out 의 것)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if a.check:
        check(a.published or os.path.join(a.out, "wx_steps.json"))
    else:
        built = run_all(a.out, force=a.force, max_steps=a.max_steps, workers=a.workers)
        go = os.environ.get("GITHUB_OUTPUT")
        if go:
            with open(go, "a") as fh:
                fh.write(f"built={'yes' if built else 'no'}\n")
