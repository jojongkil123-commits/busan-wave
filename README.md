# tidal-tiles — 전 세계 조류 격자 (자동 · 매 실행 강제 푸시)

(2026-10-10 조팀장 요청: 전 세계 조류 · 윈디처럼 부드럽게)

이 가지는 main 과 이어지지 않는 **부모 없는 커밋 하나**다. update-tidal 워크플로가 매일 새로 만들어 강제 푸시한다(역사가 쌓이지 않게).
코드·형식 설명은 main 의 `scripts/build_tidal_global.py` (FORMAT_DOC).

- `index.json` — 지금 run, t0·n, 두 단계(L0 1° 전 지구 · L1 0.25° 10°×10° 타일) 목록·주소·형식
- `<run>/L0.bin`, `<run>/L1/<minLat>_<minLng>.bin` — raw DEFLATE 로 누른 int16 u·v (0.5 cm/s 단위)
- 이번 run 과 바로 전 run 폴더만 둔다(어제 index 를 막 받은 앱이 타일을 마저 받을 수 있게).

Generated using E.U. Copernicus Marine Service Information.
