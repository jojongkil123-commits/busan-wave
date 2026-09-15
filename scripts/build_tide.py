#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_tide.py — 부산 오늘 물때(고저조) 빌더  [Phase 4]

data.go.kr 신규 바다누리 조석예보(고저조) API → data/tide_busan.json
- 엔드포인트: apis.data.go.kr/1192136/tideFcstHghLw (조석예보 고저조)
- 관측소: 부산 = DT_0005  (해루질앱 KHOATideService와 동일)
- 응답 필드: predcDt(예측일시 "yyyy-MM-dd HH:mm"), predcTdlvVl(조위 cm), extrSe(1·3=만조/고조, 2·4=간조/저조)

키는 환경변수 KHOA_KEY 로 주입한다(공개 정적 웹앱이라 키를 클라이언트에 넣지 않고,
GitHub Actions 비밀값으로만 서버에서 호출 → 결과 JSON만 커밋). 키가 없으면 아무것도
하지 않고 정상 종료 → 프론트는 물때 패널을 그냥 숨긴다(graceful).

사용:  KHOA_KEY=<data.go.kr 인증키> python3 scripts/build_tide.py
"""
import os
import sys
import time
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

KEY = os.environ.get("KHOA_KEY", "").strip()
if not KEY:
    print("KHOA_KEY 없음 → 물때 생성 건너뜀 (프론트는 물때 패널 숨김).")
    sys.exit(0)

KST = timezone(timedelta(hours=9))
OBS_CODE = "DT_0005"  # 부산
BASE = "https://apis.data.go.kr/1192136/tideFcstHghLw/GetTideFcstHghLwApiService"


def encode_key(k: str) -> str:
    # 이미 URL 인코딩된 키(%포함)면 그대로, 아니면 인코딩
    return k if "%" in k else urllib.parse.quote(k, safe="")


def fetch_day(yyyymmdd: str) -> dict:
    query = "&".join([
        "serviceKey=" + encode_key(KEY),
        "obsCode=" + OBS_CODE,
        "reqDate=" + yyyymmdd,
        "type=json",
        "numOfRows=10",
    ])
    url = BASE + "?" + query
    req = urllib.request.Request(url, headers={"User-Agent": "busan-wave/1.0"})

    # ⚠️ 재시도 필수 — 이게 없어서 워크플로가 반복해서 죽었다(2026-08-09, 08-12 실패).
    #    바다누리(KHOA) 쪽이 새벽에 종종 20초를 넘긴다. 한 번 실패하면 그날 물때가
    #    통째로 안 올라가고, 앱은 어제 데이터를 그대로 보여준다 — 물때가 하루 틀리면
    #    간조 시각이 50분씩 어긋나 헛걸음이 된다.
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 5 * (attempt + 1)      # 5s → 10s → 15s
            print(f"물때 요청 실패({attempt + 1}/4): {e} — {wait}초 후 재시도", flush=True)
            if attempt < 3:
                time.sleep(wait)
    raise last


def walk(obj, out):
    """predcDt 키를 가진 객체를 재귀 탐색 (응답 중첩 구조가 문서상 가변)."""
    if isinstance(obj, list):
        for v in obj:
            walk(v, out)
    elif isinstance(obj, dict):
        if "predcDt" in obj:
            out.append(obj)
        else:
            for v in obj.values():
                walk(v, out)


def parse(js: dict) -> list:
    items = []
    walk(js, items)
    events = []
    for it in items:
        dt = it.get("predcDt")
        if not dt:
            continue
        try:
            level = float(it.get("predcTdlvVl"))
        except (TypeError, ValueError):
            level = 0.0
        se = str(it.get("extrSe", ""))
        kind = "high" if se in ("1", "3") else "low"
        # "yyyy-MM-dd HH:mm" 으로 정규화 (프론트가 slice(11,16)로 HH:mm 추출)
        time_str = dt[:16].replace("T", " ")
        events.append({"time": time_str, "level_cm": level, "kind": kind})
    return events


def fetch_openmeteo(day: str) -> list:
    """
    대체 물때 — Open-Meteo 해수면고(sea_level_height_msl)에서 고·저조를 직접 찾는다.

    ⚠️ 왜 필요한가 (2026-08-14):
       바다누리(data.go.kr)가 **깃허브 러너에서 간헐적으로 타임아웃**한다.
       국내에서는 즉시 되는데 해외 IP에서 안 되는 날이 있다 — 45초 4회 재시도도
       전부 실패했다(run 31760433320). 물때가 하루 안 올라가면 앱이 어제 값을
       보여주고, 간조가 50분 어긋나 헛걸음이 된다. 그래서 소스를 하나 더 둔다.

    ⚠️ 기준면이 다르다. 바다누리는 약최저저조면(DL), 이쪽은 평균해면(MSL) 기준이라
       **조위 숫자를 섞어 쓰면 안 된다**. 그래서 JSON 의 datum 에 어느 쪽인지 적고,
       화면에도 출처를 밝힌다. 우리가 실제로 쓰는 건 **고·저조 시각**이라 실용상 문제없다.
    """
    url = ("https://marine-api.open-meteo.com/v1/marine"
           "?latitude=35.10&longitude=129.08"
           "&hourly=sea_level_height_msl"
           f"&start_date={day[:4]}-{day[4:6]}-{day[6:]}"
           f"&end_date={day[:4]}-{day[4:6]}-{day[6:]}"
           "&timezone=Asia%2FSeoul")
    with urllib.request.urlopen(url, timeout=45) as r:
        h = json.loads(r.read().decode()).get("hourly", {})
    times, vals = h.get("time", []), h.get("sea_level_height_msl", [])
    pts = [(t, v) for t, v in zip(times, vals) if v is not None]
    if len(pts) < 5:
        return []
    # 앞뒤보다 높으면 만조, 낮으면 간조 (1시간 간격이라 시각 오차는 ±30분)
    events = []
    for i in range(1, len(pts) - 1):
        prev, cur, nxt = pts[i - 1][1], pts[i][1], pts[i + 1][1]
        kind = "high" if cur >= prev and cur >= nxt else ("low" if cur <= prev and cur <= nxt else None)
        if kind:
            events.append({
                "time": pts[i][0].replace("T", " ")[:16],
                "level_cm": round(cur * 100),
                "kind": kind,
            })
    return events


def main():
    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")
    source, datum = "바다누리(KHOA)", "약최저저조면(DL)"
    try:
        events = parse(fetch_day(today))
    except Exception as e:  # noqa: BLE001
        # ⭐ 바다누리가 안 되면 죽지 말고 대체 소스로 간다. 물때는 하루라도
        #    비면 안 되는 값이다 — 없는 것보다 ±30분 오차가 낫다.
        print("바다누리 실패 → Open-Meteo 로 대체:", e, flush=True)
        try:
            events = fetch_openmeteo(today)
            source, datum = "Open-Meteo(대체)", "평균해면(MSL)"
        except Exception as e2:  # noqa: BLE001
            print("대체 소스도 실패:", e2)
            sys.exit(1)

    # 오늘 날짜만, 시간순
    events = [e for e in events if e["time"][:10].replace("-", "") == today]
    events.sort(key=lambda e: e["time"])

    if not events:
        print("물때 항목 없음(키/관측소 확인). JSON 미생성.")
        sys.exit(1)

    out = {
        "station": "부산(DT_0005)",
        "date": now.strftime("%Y-%m-%d"),
        "generated": now.isoformat(),
        "source": source,
        "datum": datum,
        "events": events,
    }
    os.makedirs("data", exist_ok=True)
    with open("data/tide_busan.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"물때 저장: {len(events)}건 → data/tide_busan.json")


if __name__ == "__main__":
    main()
