#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
discover_tide_points.py — 국립해양조사원 조석예보 지점(SO_·DT_) 전수 찾기  [2026-10-01]

왜: 조팀장 "조류세기(물흐름)는 바다타임과 동일하게". 바다타임은 장소마다 가까운 조석예보 지점을 쓰는데
    (예: 용호부두 11:00·04:24, 송정 10:55·04:19), 우리 목록은 97곳(SO_ 35곳)뿐이라 그런 곳이 해운대로 대체돼
    물흐름이 1% 다르게 나왔다. 조석예보(고저조) 응답에 지점명·위경도가 오므로 코드를 훑어 전부 모은다.
결과: scripts/tide_points_all.json [{code,name,lat,lon}] — build_tides.py 가 이 목록을 쓴다(없으면 tide_stations.json).
"""
import os, sys, json, time, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

KEY = os.environ.get("KHOA_KEY", "").strip()
if not KEY:
    print("KHOA_KEY 없음"); sys.exit(0)
RELAY = os.environ.get("KHOA_RELAY", "").strip()
API = "https://apis.data.go.kr/1192136/tideFcstHghLw/GetTideFcstHghLwApiService"
HERE = os.path.dirname(os.path.abspath(__file__))
DAY = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def enc(k): return k if "%" in k else urllib.parse.quote(k, safe="")


def probe(code):
    q = f"serviceKey={enc(KEY)}&obsCode={code}&reqDate={DAY}&type=json&numOfRows=10"
    url = (RELAY + "?path=tideFcstHghLw/GetTideFcstHghLwApiService&" + q) if RELAY else (API + "?" + q)
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "busan-wave/1.0", "x-region": "ap-northeast-2"})
            with urllib.request.urlopen(req, timeout=20) as r:
                js = json.loads(r.read().decode("utf-8", "replace"))
            items = (((js.get("body") or {}).get("items") or {}).get("item")) or []
            if isinstance(items, dict): items = [items]
            for it in items:
                if it.get("lat") is not None and it.get("lot") is not None:
                    return {"code": code, "name": str(it.get("obsvtrNm") or code),
                            "lat": round(float(it["lat"]), 5), "lon": round(float(it["lot"]), 5)}
            return None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403): return None
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


codes = [f"SO_{n:04d}" for n in range(1, 1601)] + [f"DT_{n:04d}" for n in range(1, 131)]
with ThreadPoolExecutor(max_workers=8) as ex:
    found = [r for r in ex.map(probe, codes) if r]
found.sort(key=lambda r: r["code"])
with open(os.path.join(HERE, "tide_points_all.json"), "w", encoding="utf-8") as f:
    json.dump(found, f, ensure_ascii=False, indent=0)
print(f"조석예보 지점 {len(found)}곳 (SO_ {sum(r['code'].startswith('SO_') for r in found)} · DT_ {sum(r['code'].startswith('DT_') for r in found)})")
