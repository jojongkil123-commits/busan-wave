#!/usr/bin/env python3
"""
부산 파고 — Phase 2: NOAA GFS-Wave GRIB2 → u/v PNG 텍스처 변환 (키 불필요·퍼블릭도메인·상업가능)

흐름: NOMADS grib filter로 최신 GFS-Wave 서브셋(swh 파고 + dirpw 파향) 다운로드
      → eccodes로 파싱 → u/v 성분 → PNG(R=u, G=v, A=바다/육지) + wave_meta.json

필요: pip install eccodes cfgrib numpy pillow   (eccodes C라이브러리 번들 wheel)
사용: python3 build_wave_texture.py            # 최신 런 자동 다운로드+변환
      python3 build_wave_texture.py <grib파일> # 기존 파일 변환

출력: ../data/wave.png, ../data/wave_meta.json
자동화(Phase 2): 이 스크립트를 GitHub Actions cron(6시간)으로 돌려 결과를 Pages/R2에 커밋·업로드.
(주의: Cloudflare Worker는 eccodes 실행 불가 → GRIB 파싱은 GitHub Actions/서버에서. Worker는 정적 PNG 서빙만.)
"""
import sys, os, json, math, urllib.request
import numpy as np
import eccodes as ec
from PIL import Image

REGION = dict(top=90, left=0, right=360, bottom=-90)   # ⭐ 전세계 (2026-07-04, 해루질앱 글로벌 뷰)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# 예보 스텝: 0~72h는 3시간, 그 뒤 168h(7일)까지는 6시간 간격 (윈디식 시간 슬라이더)
# 최대 연장(2026-07-28 조팀장): 0~72h는 3h, ~168h(7일)는 6h, ~384h(16일)는 12h 스텝.
# GFS/GFS-Wave가 제공하는 전체 범위. 먼 미래일수록 성긴 스텝(윈디와 같은 방식).
# ⭐ 2026-09-06 조팀장 "윈디처럼 시간 간격도 맞춰라": 0~72h 를 **1시간** 스텝으로(GFS·GFS-Wave 둘 다
#    f000~f120 은 매시간 파일이 있다) → 재생 때 3시간 보간이 아니라 실제 매시간 예보로 색·바람이 움직인다.
#    그 뒤는 3h(~120h) → 6h(~168h) → 12h(~384h). 스텝 115개(전 59개), 데이터 약 2배.
STEP_HOURS = list(range(0, 73, 1)) + list(range(75, 121, 3)) + list(range(126, 169, 6)) + list(range(180, 385, 12))

def _dl(url, tries=2):
    import time
    for t in range(tries):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url), timeout=90).read()
            if len(data) > 2000 and data[:4] == b"GRIB":
                return data
        except Exception:
            pass
        time.sleep(2)
    return None

def wave_url(d, cc, fh):
    return (f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfswave.pl?dir=%2Fgfs.{d}%2F{cc}"
            f"%2Fwave%2Fgridded&file=gfswave.t{cc}z.global.0p25.f{fh:03d}.grib2"
            f"&var_HTSGW=on&var_DIRPW=on&subregion=&toplat={REGION['top']}"
            f"&leftlon={REGION['left']}&rightlon={REGION['right']}&bottomlat={REGION['bottom']}")

def wave16_url(d, cc, fh):
    """GFS-Wave **0.1667°(18.5km)** 격자 — 파도 모델이 실제로 계산된 더 촘촘한 격자.
    범위는 남위 15°~북위 52.5°(전 경도)라 한국·일본·동남아·지중해를 덮는다.
    ⭐ 2026-09-06: 0.25°(28km)에서는 해안 가까운 칸이 육지에 먹혀 값이 없었다 —
       실측: 강릉 최근접 바다칸 25.9km→8.3km, 제주 17.8km→9.0km.
       (같은 파일의 UGRD/VGRD는 파도모델 구동용 바람을 옮겨 심은 것이라 바람은 이득 없음 → 안 쓴다)"""
    return (f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfswave.pl?dir=%2Fgfs.{d}%2F{cc}"
            f"%2Fwave%2Fgridded&file=gfswave.t{cc}z.global.0p16.f{fh:03d}.grib2"
            f"&var_HTSGW=on&var_DIRPW=on&subregion=&toplat=90"
            f"&leftlon=0&rightlon=360&bottomlat=-90")

def sst_url(d, cc, fh):
    # GFS TMP:surface — 바다 셀에서는 해수면 온도(전세계). 육지는 앱이 해안선 마스크로 지움.
    return (f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.{d}%2F{cc}%2Fatmos"
            f"&file=gfs.t{cc}z.pgrb2.0p25.f{fh:03d}"
            f"&var_TMP=on&lev_surface=on&subregion=&toplat={REGION['top']}"
            f"&leftlon={REGION['left']}&rightlon={REGION['right']}&bottomlat={REGION['bottom']}")

def atmos_url(d, cc, fh):
    # GFS 대기모델 10m 바람(UGRD/VGRD) — 파도모델과 달리 육지 포함 전 지구
    return (f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.{d}%2F{cc}%2Fatmos"
            f"&file=gfs.t{cc}z.pgrb2.0p25.f{fh:03d}"
            f"&var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on&subregion=&toplat={REGION['top']}"
            f"&leftlon={REGION['left']}&rightlon={REGION['right']}&bottomlat={REGION['bottom']}")

def latest_run():
    """가용한 최신 GFS 런(날짜, 사이클)을 찾는다 — **마지막 스텝(f384)까지 완비된** 런만.
    (예전엔 f000만 확인해서, 갓 발표돼 뒷부분이 아직 업로드 안 된 런을 골라
     66h쯤에서 스텝이 끊기던 문제가 있었다 — 2026-07-28 수정. 완비 런은 한 사이클(6h) 뒤라도 16일 전체가 나온다.)"""
    form = urllib.request.urlopen(
        "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfswave.pl", timeout=30).read().decode("utf8", "ignore")
    import re
    dates = sorted(set(re.findall(r"gfs\.(\d{8})", form)))
    last_fh = STEP_HOURS[-1]
    for d in reversed(dates):
        for cc in ("18", "12", "06", "00"):
            # 마지막 스텝이 있어야 런 완비 → 그때 f000도 받는다
            if _dl(wave_url(d, cc, last_fh), tries=1):
                data = _dl(wave_url(d, cc, 0), tries=1)
                if data:
                    return d, cc, data
    raise RuntimeError("가용한 GFS-Wave 런을 못 찾음")

def read_grib(path_or_bytes):
    if isinstance(path_or_bytes, bytes):
        tmp = "/tmp/_gfswave_dl.grib2"; open(tmp, "wb").write(path_or_bytes); path = tmp
    else:
        path = path_or_bytes
    fields = {}; meta = {}
    f = open(path, "rb")
    while True:
        gid = ec.codes_grib_new_from_file(f)
        if gid is None: break
        sn = ec.codes_get(gid, "shortName")
        Ni = ec.codes_get(gid, "Ni"); Nj = ec.codes_get(gid, "Nj")
        miss = ec.codes_get(gid, "missingValue")
        jpos = ec.codes_get(gid, "jScansPositively")
        vals = ec.codes_get_values(gid).reshape(Nj, Ni)
        vals = np.where(vals == miss, np.nan, vals)
        if jpos == 1:   # 남→북 스캔이면 뒤집어 북쪽이 위로
            vals = vals[::-1, :]
        fields[sn] = vals
        meta.update(width=Ni, height=Nj,
                    west=ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees"),
                    east=ec.codes_get(gid, "longitudeOfLastGridPointInDegrees"),
                    south=min(ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees"),
                              ec.codes_get(gid, "latitudeOfLastGridPointInDegrees")),
                    north=max(ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees"),
                              ec.codes_get(gid, "latitudeOfLastGridPointInDegrees")))
        ec.codes_release(gid)
    f.close()
    # 전세계(경도 0~360) 격자는 -180~180으로 돌려놓는다(지도 좌표계와 일치, JS 랩 처리 불필요)
    if meta.get("west", 0) == 0 and meta.get("east", 0) > 350:
        w = meta["width"]
        half = w // 2
        for k in fields:
            fields[k] = np.concatenate([fields[k][:, half:], fields[k][:, :half]], axis=1)
        meta["west"] = -180.0
        meta["east"] = -180.0 + (w - 1) * (360.0 / w)   # 0.25°면 179.75
    return fields, meta

def _shift(a, dy, dx, fill=0.0):
    """wrap 없는 2D 시프트 (np.roll은 반대편 끝 값이 새어 들어와 부적합)."""
    h, w = a.shape
    out = np.full_like(a, fill)
    out[max(dy,0):h+min(dy,0), max(dx,0):w+min(dx,0)] = \
        a[max(-dy,0):h+min(-dy,0), max(-dx,0):w+min(-dx,0)]
    return out

def fill_coastal(u, v, ok, iters=5):   # 전세계라 5회(≈125km)만 — 해안 공백 메우되 내륙 번짐 최소
    """유효(바다) 값을 육지 쪽으로 반복 확산 — NOAA 0.25° 육지마스크 탓에 해안 앞바다가
    뚝 끊기는 공백을 없앤다. 실제 해안 경계는 앱이 벡터 해안선으로 잘라낸다."""
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
        u[new] = su[new] / cnt[new]; v[new] = sv[new] / cnt[new]
        ok = ok | new
    return u, v, ok

def save_texture(u, v, ok, meta, name, extra_meta):
    """u/v(실단위) → R=u, G=v, A=유효 인코딩 PNG + meta JSON."""
    h, w = u.shape
    umin, umax = float(np.min(u[ok])), float(np.max(u[ok]))
    vmin, vmax = float(np.min(v[ok])), float(np.max(v[ok]))
    ur = (u - umin) / (umax - umin + 1e-6)
    vr = (v - vmin) / (vmax - vmin + 1e-6)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(ur * 255, 0, 255).astype(np.uint8)
    rgba[..., 1] = np.clip(vr * 255, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(ok, 255, 0).astype(np.uint8)
    os.makedirs(OUT_DIR, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(os.path.join(OUT_DIR, f"{name}.png"))
    out_meta = dict(width=w, height=h, uMin=umin, uMax=umax, vMin=vmin, vMax=vmax,
                    west=meta["west"], east=meta["east"], south=meta["south"], north=meta["north"],
                    **extra_meta)
    json.dump(out_meta, open(os.path.join(OUT_DIR, f"{name}_meta.json"), "w"), ensure_ascii=False, indent=1)
    return out_meta

def build_wave_step(fields, meta, fh, run="?"):
    """GFS-Wave 한 스텝 → wave_fill_tHHH.png (+f000이면 레거시 wave.png도)."""
    swh = fields.get("swh"); dirp = fields.get("dirpw")
    if swh is None or dirp is None:
        raise RuntimeError(f"swh/dirpw 누락: {list(fields)}")
    sea = ~np.isnan(swh) & ~np.isnan(dirp)
    # 파향(°, 파도가 '오는' 방향) → 진행 방향 단위벡터. 화면 좌표(동+x, 남+y).
    th = np.deg2rad(np.nan_to_num(dirp))
    u = np.where(sea, np.nan_to_num(swh) * -np.sin(th), 0.0)
    v = np.where(sea, np.nan_to_num(swh) *  np.cos(th), 0.0)
    uf, vf, okf = fill_coastal(u, v, sea)
    m = save_texture(uf, vf, okf, meta, f"wave_fill_t{fh:03d}",
                     dict(maxWaveM=float(np.nanmax(swh)), run=run, filled=True, fh=fh,
                          source="NOAA GFS-Wave (public domain)"))
    print(f"  wave t+{fh:02d}h 파고최대 {m['maxWaveM']:.2f}m")
    return (u, v, sea, uf, vf, okf, float(np.nanmax(swh)))

def build_wave_fine_step(fields, meta, fh, run="?"):
    """0.1667° 파도 → wave_fine_tHHH.png. 앱은 화면이 이 범위 안이면 이걸 먼저 쓴다."""
    swh = fields.get("swh"); dirp = fields.get("dirpw")
    if swh is None or dirp is None:
        return None
    sea = ~np.isnan(swh) & ~np.isnan(dirp)
    th = np.deg2rad(np.nan_to_num(dirp))
    u = np.where(sea, np.nan_to_num(swh) * -np.sin(th), 0.0)
    v = np.where(sea, np.nan_to_num(swh) *  np.cos(th), 0.0)
    uf, vf, okf = fill_coastal(u, v, sea)
    m = save_texture(uf, vf, okf, meta, f"wave_fine_t{fh:03d}",
                     dict(maxWaveM=float(np.nanmax(swh)), run=run, filled=True, fh=fh, fine=True,
                          source="NOAA GFS-Wave 0.1667deg (public domain)"))
    print(f"  wave16 t+{fh:02d}h 격자 {m['width']}x{m['height']} 파고최대 {m['maxWaveM']:.2f}m")
    return m

def build_wind_step(fields, meta, fh, run="?"):
    """GFS 대기모델 10m 바람 한 스텝 → wind_tHHH.png (육지 포함 전 지구).
    GRIB u=동+, v=북+ → 화면좌표(v=남+)로 부호 반전."""
    ug = fields.get("10u"); vg = fields.get("10v")
    if ug is None or vg is None:
        raise RuntimeError(f"10u/10v 누락: {list(fields)}")
    ok = ~np.isnan(ug) & ~np.isnan(vg)
    u = np.nan_to_num(ug)
    v = -np.nan_to_num(vg)   # 북+ → 남+ (화면 좌표)
    ws = np.sqrt(u*u + v*v)
    m = save_texture(u, v, ok, meta, f"wind_t{fh:03d}",
                     dict(maxWindMs=float(np.nanmax(ws)), run=run, landOk=True, fh=fh,
                          source="NOAA GFS 10m wind (public domain)"))
    print(f"  wind t+{fh:02d}h 풍속최대 {m['maxWindMs']:.1f}m/s")

def build_sst_step(fields, meta, fh, run="?"):
    """GFS TMP:surface 한 스텝 → sst_tHHH.png. 스칼라(수온°C)를 u에 넣고 v=0.
    JS는 m=|u|/domain(32°C)로 값 복원, 입자 애니 없이 색면만 그린다."""
    t = fields.get("t")
    if t is None:
        raise RuntimeError(f"TMP:surface 누락: {list(fields)}")
    c = t - 273.15                       # K → °C
    ok = ~np.isnan(c) & (c > -5) & (c < 45)   # 바다 수온 범위만 유효(극지 빙점 이하 등 제외)
    u = np.where(ok, np.clip(c, 0, 32), 0.0)
    v = np.zeros_like(u)
    m = save_texture(u, v, ok, meta, f"sst_t{fh:03d}",
                     dict(maxSstC=float(np.nanmax(np.where(ok, c, np.nan))), run=run, fh=fh, sst=True,
                          source="NOAA GFS surface temperature (public domain)"))
    print(f"  sst  t+{fh:02d}h 수온최대 {m['maxSstC']:.1f}°C")

def run_all():
    import datetime, shutil, time
    d, cc, first = latest_run()
    run = f"{d} {cc}Z"
    run_dt = datetime.datetime.strptime(d + cc, "%Y%m%d%H").replace(tzinfo=datetime.timezone.utc)
    print("런:", run)
    ok_hours = []
    wave_first = None
    for fh in STEP_HOURS:
        wdata = first if fh == 0 else _dl(wave_url(d, cc, fh))
        adata = _dl(atmos_url(d, cc, fh))
        sdata = _dl(sst_url(d, cc, fh))
        if not wdata or not adata:
            print(f"  ⚠️ t+{fh}h 데이터 미가용 — 이 스텝 건너뜀")
            continue
        wf, wm = read_grib(wdata)
        af, am = read_grib(adata)
        res = build_wave_step(wf, wm, fh, run)
        build_wind_step(af, am, fh, run)
        # 고해상 파도(0.1667°)는 f120 까지만 제공된다. 없으면 조용히 건너뛴다(전세계 0.25°가 폴백).
        if fh <= 120:
            w16 = _dl(wave16_url(d, cc, fh), tries=1)
            if w16:
                try:
                    f16, m16 = read_grib(w16)
                    build_wave_fine_step(f16, m16, fh, run)
                except Exception as e:
                    print(f"  ⚠️ wave16 t+{fh}h 변환 실패: {e}")
        if sdata:
            sf, sm = read_grib(sdata)
            build_sst_step(sf, sm, fh, run)
        if fh == 0:
            wave_first = (wf, wm, res)
        ok_hours.append(fh)
        time.sleep(0.5)   # NOMADS 매너
    if not ok_hours:
        raise RuntimeError("모든 스텝 다운로드 실패")

    # '지금'에 가장 가까운 스텝 → 레거시 파일명(wave_fill.png/wind.png)으로 복사 (구버전 앱·PWA 호환)
    now = datetime.datetime.now(datetime.timezone.utc)
    now_idx = min(range(len(ok_hours)),
                  key=lambda i: abs((run_dt + datetime.timedelta(hours=ok_hours[i]) - now).total_seconds()))
    nh = ok_hours[now_idx]
    for src, dst in ((f"wave_fill_t{nh:03d}", "wave_fill"), (f"wind_t{nh:03d}", "wind"),
                     (f"sst_t{nh:03d}", "sst")):
        if not os.path.exists(os.path.join(OUT_DIR, src + ".png")):
            continue   # sst는 일부 스텝 실패 가능
        shutil.copy(os.path.join(OUT_DIR, src + ".png"), os.path.join(OUT_DIR, dst + ".png"))
        mm = json.load(open(os.path.join(OUT_DIR, src + "_meta.json")))
        json.dump(mm, open(os.path.join(OUT_DIR, dst + "_meta.json"), "w"), ensure_ascii=False, indent=1)
    print(f"기본본(now) = t+{nh}h")

    # 레거시 wave.png (PWA 부산파고 — 원본 바다마스크판, f000)
    if wave_first:
        wf, wm, (u, v, sea, uf, vf, okf, mx) = wave_first
        save_texture(u, v, sea, wm, "wave", dict(maxWaveM=mx, run=run,
                     source="NOAA GFS-Wave (public domain)"))

    # 스텝 매니페스트
    valid = [(run_dt + datetime.timedelta(hours=h)).isoformat().replace("+00:00", "Z") for h in ok_hours]
    json.dump(dict(run=run, runIso=run_dt.isoformat().replace("+00:00", "Z"),
                   stepHours=ok_hours, valid=valid, nowIdx=now_idx),
              open(os.path.join(OUT_DIR, "wx_steps.json"), "w"), ensure_ascii=False, indent=1)
    print(f"✅ wx_steps.json 스텝 {len(ok_hours)}개, nowIdx={now_idx}")

if __name__ == "__main__":
    run_all()
