#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tidal_archive.py — 전국 조류(조석 성분) 일별 보관본  [2026-10-13]
(2026-10-13 조팀장 요청: 그날 바다 윈디 자료)

왜: 출조 기록 '그날 바다'의 조류를 윈디 '조류'(CMEMS SMOC utide·vtide)로 보여 주려면 지난 날짜 값이 있어야 한다.
  그런데 data/tidal/korea_tidal.json 은 실행일 00:00 KST 부터 96시간(과거 0시간)이고, 가지 tidal-tiles 도 직전 run 하나뿐이다
  → 10/12 21:55 출조는 10/13 아침 실행 뒤로는 서버 어디에서도 다시 받을 수 없었다. 그래서 하루치를 따로 남긴다.
  CMEMS 데이터셋(cmems_mod_glo_phy_anfc_merged-uv_PT1H-i)은 2020-11 부터 과거가 있어 빠진 날을 나중에 채울 수도 있다.

출력 (앱 TidalArchiveService 가 받는다 — Pages):
  data/tidal/archive/korea_YYYYMMDD.json — korea_tidal.json 과 **같은 계약**(build_tidal.write_grid 로 쓴다 — 키 순서 '{"minLat"' … ']}' 끝,
    core 32.0–39.5N·123.0–132.5E 1/12° 91×115, src "cmems-smoc-tide", unit cm/s, dirConv toward, step 3600, filter "none-cmems-utide-arco").
    다른 점은 **n = 24, t0 = 그날(D) 00:00 KST** 뿐. 시각 규칙도 같다: 출력 t = 공식 도구 라벨 t − SHOW_SHIFT(3600) 값(윈디 시각, 2026-10-11 결정).
    한 번 만든 날 파일은 다시 쓰지 않는다(불변). 머리·꼬리 검사에 실패한(깨진) 파일만 다시 만든다.
  data/tidal/archive/index.json — 진단용(앱은 안 읽는다): start(채울 시작일)·from·to·days·bytes·missing·keep_days·last_attempt.

매 실행 (update-tidal.yml '조류 일별 보관본' 단계 — continue-on-error):
  창 = [max(시작일, 오늘 − ARCHIVE_KEEP_DAYS) … 어제] (KST 날짜) 중 **없는 날만** 받는다 → 실패한 날은 다음 실행이 스스로 채운다.
  시작일 = ARCHIVE_FROM(환경변수 · --from · workflow_dispatch 입력 archive_from) 과 index.json 의 start 중 이른 것
           (둘 다 없으면 가장 이른 보관 파일 날짜, 그것도 없으면 어제). 시작일은 넓히기만 한다 — 좁히려면 index.json 을 고친다.
  받기: 빈 날을 이어진 덩어리로 묶어 최대 ARCHIVE_BLOCK_DAYS(31)일씩 공식 도구로 한 번에 받아(tidal_cmems._toolbox_fetch, core 상자) 날짜별로 자른다.
    2026-10-13 로컬 실측(맥, 31일 = 744시각): 열기 12.3 s · 읽기 11.5 s · 배열 62 MB · 최대 메모리 0.56 GB · 전체 ≈ 28 s.
    공식 도구가 시계열 조각(시각 4,272 × 위도 16 × 경도 8)을 골라 하루를 받든 31일을 받든 받는 양이 거의 같다 → 덩어리로 받는다.
    덩어리가 실패하면(그 안 하루가 아직 없음 등) 그 덩어리를 하루씩 다시 받는다. ARCHIVE_TIME_BUDGET(초)을 넘으면 멈추고 다음 실행으로.
  날마다 build_tidal.sanity(바다 칸 수·빈칸 5%·유속 600 cm/s)를 통과해야 쓴다.
정리: 오늘 − ARCHIVE_KEEP_DAYS(180)일보다 앞선 파일은 지운다. 커밋 단계(data_commit_push.sh)는 최신 origin/main 위에 data/tidal 을
  덮어 얹으므로(지운 파일이 되살아난다) 얹은 뒤 `--prune-only` 를 한 번 더 부른다(AFTER_RELAY) — 날짜 기준이라 엇갈려도 안전하다.
  용량: 하루 ≈ 1.5 MB(gzip ≈ 0.35 MB) × 180 ≈ 0.28 GB.

환경변수: COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD(공식 도구 로그인 — 워크플로가 비밀값 CMEMS_* 를 넘긴다),
  ARCHIVE_FROM(YYYY-MM-DD), ARCHIVE_KEEP_DAYS(180), ARCHIVE_BLOCK_DAYS(31), ARCHIVE_TIME_BUDGET(1500 s),
  TIDAL_ARCHIVE_OUT(출력 폴더 — 로컬 검사용, 기본 data/tidal/archive), TIDAL_SHOW_SHIFT(build_tidal·tidal_cmems 와 같은 값이어야 한다).
사용: python3 scripts/build_tidal_archive.py [--from YYYY-MM-DD] [--prune-only]
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

import build_tidal as bt   # 표준 라이브러리만 — --prune-only 는 numpy 없이 돈다

KEEP_DAYS = int(os.environ.get("ARCHIVE_KEEP_DAYS", "180"))
BLOCK_DAYS = max(1, int(os.environ.get("ARCHIVE_BLOCK_DAYS", "31")))
TIME_BUDGET = int(os.environ.get("ARCHIVE_TIME_BUDGET", "1500"))
OUT_DIR = os.environ.get("TIDAL_ARCHIVE_OUT", os.path.join(bt.ROOT, "data", "tidal", "archive"))
INDEX = os.path.join(OUT_DIR, "index.json")
N_DAY = 24
FILTER = "none-cmems-utide-arco"           # build_tidal.run_cmems 공식 도구 경로와 같은 이름
URL_PATTERN = "https://jojongkil123-commits.github.io/busan-wave/data/tidal/archive/korea_YYYYMMDD.json"
NAME_RE = re.compile(r"^korea_(\d{8})\.json$")
_t0 = time.time()


def log(*a):
    print(" ".join(str(x) for x in a), flush=True)


def path_of(d):
    return os.path.join(OUT_DIR, f"korea_{d:%Y%m%d}.json")


def ok_file(p):
    """계약 머리·꼬리만 본다(앱 디스크 사본 검사와 같은 규칙) — 통째 파싱 안 함"""
    try:
        size = os.path.getsize(p)
        if size < 1000:
            return False
        with open(p, "rb") as f:
            head = f.read(16)
            f.seek(size - 2)
            tail = f.read(2)
        return head.startswith(b'{"minLat"') and tail == b"]}"
    except OSError:
        return False


def files_on_disk():
    """{날짜: 경로} — 이름이 korea_YYYYMMDD.json 인 것만"""
    out = {}
    if os.path.isdir(OUT_DIR):
        for name in os.listdir(OUT_DIR):
            m = NAME_RE.match(name)
            if m:
                try:
                    out[datetime.strptime(m.group(1), "%Y%m%d").date()] = os.path.join(OUT_DIR, name)
                except ValueError:
                    pass
    return out


def today_kst():
    return datetime.now(bt.KST).date()


def day_t0(d):
    """그날 00:00 KST 의 epoch 초 — 계약 t0"""
    return int(datetime(d.year, d.month, d.day, tzinfo=bt.KST).timestamp())


def parse_day(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"archive_from 꼴이 YYYY-MM-DD 가 아님: {s!r}")


def prune(today):
    """오늘 − KEEP_DAYS 보다 앞선 파일과 남은 .tmp 를 지운다 → 지운 날짜 목록"""
    keep_from = today - timedelta(days=KEEP_DAYS)
    gone = []
    for d, p in sorted(files_on_disk().items()):
        if d < keep_from:
            os.remove(p)
            gone.append(d.isoformat())
    if os.path.isdir(OUT_DIR):
        for name in os.listdir(OUT_DIR):
            if name.endswith(".tmp"):
                os.remove(os.path.join(OUT_DIR, name))
    if gone:
        log(f"정리: {KEEP_DAYS}일 지난 보관본 {len(gone)}개 지움 ({gone[0]} … {gone[-1]})")
    return gone


def window(today, start):
    keep_from = today - timedelta(days=KEEP_DAYS)
    lo = max(start, keep_from)
    hi = today - timedelta(days=1)
    return [lo + timedelta(days=i) for i in range((hi - lo).days + 1)] if lo <= hi else []


def write_index(today, start, attempt=None):
    """index.json(진단용) — 디스크에 있는 파일 그대로 다시 센다. attempt 가 없으면 이전 last_attempt 를 둔다"""
    prev = bt.load_json(INDEX, {}) or {}
    have = files_on_disk()
    days = sorted(have)
    want = window(today, start) if start else []
    idx = {
        "what": "전국 조류(CMEMS SMOC 조석 성분) 일별 보관본 — 출조 기록 '그날 바다' 조류용. 진단용(앱은 이 파일을 안 읽는다) "
                "(2026-10-13 조팀장 요청: 그날 바다 윈디 자료)",
        "url_pattern": URL_PATTERN,
        "contract": "data/tidal/korea_tidal.json 과 같음 — 단 n=24, t0 = 그날 00:00 KST. 출력 t = 공식 도구 라벨 t − show_shift_s (윈디 시각)",
        "show_shift_s": bt.SHOW_SHIFT,
        "keep_days": KEEP_DAYS,
        "start": start.isoformat() if start else None,
        "from": days[0].isoformat() if days else None,
        "to": days[-1].isoformat() if days else None,
        "days": len(days),
        "bytes": sum(os.path.getsize(p) for p in have.values()),
        "missing": [d.isoformat() for d in want if d not in have],
        "updated": datetime.now(bt.KST).isoformat(timespec="seconds"),
        "last_attempt": attempt if attempt is not None else prev.get("last_attempt"),
    }
    # 'updated' 만 바뀌는 쓰기는 하지 않는다 — 커밋 단계가 다시 얹을 때(--prune-only) 바뀐 게 없으면 '이미 같음'으로 끝나게
    if {k: v for k, v in idx.items() if k != "updated"} != {k: v for k, v in prev.items() if k != "updated"}:
        bt.write_atomic(INDEX, json.dumps(idx, ensure_ascii=False, indent=1))
    return idx


def resolve_start(today, arg_from, have):
    """시작일 — 넓히기만(이른 쪽). 반환 (시작일, 까닭)"""
    prev = bt.load_json(INDEX, {}) or {}
    cands = []
    if arg_from:
        keep_from = today - timedelta(days=KEEP_DAYS)
        if arg_from < keep_from:
            log(f"⚠️ archive_from {arg_from} 이 {KEEP_DAYS}일 창 밖 — {keep_from} 부터만 채운다")
            arg_from = keep_from
        if arg_from >= today:
            log(f"⚠️ archive_from {arg_from} 이 오늘({today}) 이후 — 무시")
            arg_from = None
    if arg_from:
        cands.append((arg_from, "archive_from"))
    ps = None
    try:
        ps = parse_day(prev.get("start"))
    except SystemExit:
        ps = None
    if ps:
        cands.append((ps, "index.json start"))
    if cands:
        return min(cands)
    if have:
        return min(have), "가장 이른 보관 파일"
    return today - timedelta(days=1), "보관본 없음 → 어제부터"


def runs_of(days):
    """이어진 날짜 덩어리(최대 BLOCK_DAYS)로 나눈다"""
    out, cur = [], []
    for d in days:
        if cur and ((d - cur[-1]).days != 1 or len(cur) >= BLOCK_DAYS):
            out.append(cur)
            cur = []
        cur.append(d)
    if cur:
        out.append(cur)
    return out


def write_day(tc, d, su, sv, now):
    """하루치 (rows, cols, 24) cm/s → 검사 → 계약 파일. 반환 (raw_bytes, gzip9_bytes, sea_n, hole, top)"""
    sp, dr, sea = tc._contract(su, sv, N_DAY)
    res = {"spd": sp.reshape(-1).tolist(), "dir": dr.reshape(-1).tolist(), "sea": sea.reshape(-1).tolist()}
    sea_n, hole, top = bt.sanity(f"보관본 {d}", bt.CORE, res, N_DAY, bt.CORE_SEA_RANGE)
    _, raw_b, gz_b = bt.write_grid(path_of(d), bt.CORE, now, day_t0(d), N_DAY, res["spd"], res["dir"], FILTER)
    return raw_b, gz_b, sea_n, hole, top


def fetch_block(tc, block, now, added, failed, fetches):
    """덩어리 하나를 한 번에 받아 날짜별로 쓴다. 받기 자체가 실패하면 예외(부른 쪽이 하루씩 다시)"""
    t0, n = day_t0(block[0]), N_DAY * len(block)
    tu, tv, _, _, info = tc._toolbox_fetch(t0, n, bt.CORE.box())
    fetches.append({"days": [block[0].isoformat(), block[-1].isoformat()], "n": n, "open_s": info.get("open_s"),
                    "load_s": info.get("load_s"), "array_mb": info.get("array_mb"), "chunks": info.get("chunks"),
                    "total_s": info.get("total_s")})
    log(f"  받음 {block[0]}…{block[-1]} ({len(block)}일 {n}시각): 열기 {info.get('open_s')}s · 읽기 {info.get('load_s')}s · "
        f"배열 {info.get('array_mb')} MB · 조각 {info.get('chunks')}")
    for i, d in enumerate(block):
        sl = slice(N_DAY * i, N_DAY * (i + 1))
        try:
            raw_b, gz_b, sea_n, hole, top = write_day(tc, d, tu[:, :, sl], tv[:, :, sl], now)
            added.append({"day": d.isoformat(), "bytes": raw_b, "gzip9_bytes": gz_b, "sea": sea_n, "empty_sea_hours": hole, "max_cms": top})
            failed.pop(d.isoformat(), None)
            log(f"  ✅ {os.path.basename(path_of(d))} {raw_b / 1e6:.2f} MB (gzip -9 {gz_b / 1e6:.2f} MB) · 바다 칸 {sea_n:,} · "
                f"빈 칸·시각 {hole} · 최대 {top} cm/s")
        except Exception as e:  # noqa: BLE001 — 그날만 버린다(다음 실행이 다시)
            failed[d.isoformat()] = f"{type(e).__name__}: {str(e)[:200]}"
            log(f"  ⚠️ {d} 검사 실패 — {failed[d.isoformat()]}")


def run(arg_from):
    now = datetime.now(bt.KST)
    today = now.date()
    os.makedirs(OUT_DIR, exist_ok=True)
    prune(today)
    have = {d: p for d, p in files_on_disk().items() if ok_file(p)}
    broken = sorted(set(files_on_disk()) - set(have))
    if broken:
        log(f"⚠️ 머리·꼬리가 깨진 보관본 {len(broken)}개 → 다시 만든다: {', '.join(map(str, broken))}")
    start, why = resolve_start(today, arg_from, have)
    want = window(today, start)
    todo = [d for d in want if d not in have]
    log(f"조류 일별 보관본 — 시작일 {start}({why}) · 창 {want[0] if want else '-'} … {want[-1] if want else '-'} "
        f"({len(want)}일, 보관 {KEEP_DAYS}일) · 있음 {len(want) - len(todo)} · 받을 날 {len(todo)} · 출력 {OUT_DIR}")
    added, failed, fetches = [], {}, []
    status = "nothing_to_do"
    if todo:
        import tidal_cmems as tc  # numpy·copernicusmarine — 받을 날이 있을 때만
        if tc.SHOW_SHIFT != bt.SHOW_SHIFT:
            raise SystemExit(f"SHOW_SHIFT 가 다름 tidal_cmems {tc.SHOW_SHIFT} ≠ build_tidal {bt.SHOW_SHIFT}")
        for block in runs_of(todo):
            if time.time() - _t0 > TIME_BUDGET:
                for d in block:
                    failed.setdefault(d.isoformat(), f"시간 예산 {TIME_BUDGET}s 넘음 — 다음 실행에서")
                continue
            try:
                fetch_block(tc, block, now, added, failed, fetches)
            except Exception as e:  # noqa: BLE001 — 덩어리 받기 실패 → 하루씩 다시
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                log(f"  ⚠️ 덩어리 {block[0]}…{block[-1]} 받기 실패 — {msg}" + (" → 하루씩 다시" if len(block) > 1 else ""))
                if len(block) == 1:
                    failed[block[0].isoformat()] = msg
                    continue
                for d in block:
                    if time.time() - _t0 > TIME_BUDGET:
                        failed.setdefault(d.isoformat(), f"시간 예산 {TIME_BUDGET}s 넘음 — 다음 실행에서")
                        continue
                    try:
                        fetch_block(tc, [d], now, added, failed, fetches)
                    except Exception as e2:  # noqa: BLE001
                        failed[d.isoformat()] = f"{type(e2).__name__}: {str(e2)[:200]}"
                        log(f"  ⚠️ {d} 받기 실패 — {failed[d.isoformat()]}")
        status = "ok" if not failed else ("partial" if added else "failed")
    attempt = {"at": now.isoformat(timespec="seconds"), "status": status, "start_reason": why,
               "added": added, "failed": failed, "fetch": fetches, "elapsed_s": round(time.time() - _t0, 1)}
    idx = write_index(today, start, attempt)
    bt.gh_output(archive=status, archive_added=len(added), archive_missing=len(idx["missing"]))
    log(f"{'✅' if status in ('ok', 'nothing_to_do') else '⚠️'} 보관본 {status}: 새로 {len(added)}일 · 실패 {len(failed)}일 · "
        f"보관 {idx['days']}일 {idx['from']} … {idx['to']} · {idx['bytes'] / 1e6:.1f} MB · 빈 날 {len(idx['missing'])} · "
        f"{time.time() - _t0:.0f}s")
    if failed:
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning::조류 보관본 {len(failed)}일 못 만듦 — 다음 실행이 다시 채운다: "
                  + "; ".join(f"{k} {v[:80]}" for k, v in sorted(failed.items())[:5]))
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="전국 조류 일별 보관본 (2026-10-13 조팀장 요청: 그날 바다 윈디 자료)")
    ap.add_argument("--from", dest="from_", default=os.environ.get("ARCHIVE_FROM", ""), help="채울 시작일 YYYY-MM-DD (넓히기만)")
    ap.add_argument("--prune-only", action="store_true", help="받지 않고 오래된 파일 정리 + index.json 다시 쓰기만")
    a = ap.parse_args()
    if a.prune_only:
        today = today_kst()
        if not os.path.isdir(OUT_DIR):
            return 0
        prune(today)
        have = {d: p for d, p in files_on_disk().items() if ok_file(p)}
        start, _ = resolve_start(today, None, have)
        idx = write_index(today, start)
        log(f"보관본 정리·색인: {idx['days']}일 {idx['from']} … {idx['to']} · {idx['bytes'] / 1e6:.1f} MB · 빈 날 {len(idx['missing'])}")
        return 0
    return run(parse_day(a.from_))


if __name__ == "__main__":
    sys.exit(main())
