# 부산 파고 (Busan Wave) — 0원·상업용 PWA

윈디처럼 파고가 흐르는 **부산 연안 지도** + 해루질 물때. 홈화면에 설치되는 웹앱(PWA).
스택: MapLibre GL JS(BSD) + OpenFreeMap 타일(OSM) + 파고 애니메이션 + (Phase 2~4) NOAA·기상청·바다누리 데이터.

## 지금 상태 (2026-06-17)
- ✅ **Phase 1** — 부산 지도 + PWA(홈화면 설치) 완성. `index.html` / `manifest.json` / `sw.js` / `icons/`.
- 🟡 **Phase 3(미리 검증)** — 클라이언트에서 파고 데이터를 받아 입자 애니메이션. ⚠️ 현재 데이터 = Open-Meteo(**비상업용**) — *동작 검증용 임시*. 상업 배포 전 Phase 2에서 NOAA/기상청으로 교체.
- ⬜ Phase 2(NOAA GRIB→PNG 서버 파이프라인), Phase 4(기상청 연안+바다누리 물때), Phase 5(배포·출처·공유카드) = 남음.

## 로컬에서 보기
```
cd busan-wave-app
python3 -m http.server 8765
# 폰/브라우저에서 http://<맥IP>:8765  (PWA 설치·GPS는 https 또는 localhost 필요)
```

## 배포 (Cloudflare Pages, 무료)
1. 이 폴더를 GitHub 저장소에 push
2. Cloudflare Pages → Connect to Git → 빌드 명령 없음(정적), 출력 디렉터리 = 루트
3. 배포되면 https 도메인 생김 → 폰에서 "홈 화면에 추가"

## Phase 0 — 미리 받아둘 키 (승인 며칠 걸림, 먼저!)
- [ ] **data.go.kr** 가입 → '기상청 단기예보 조회서비스' + '해양 예보' 활용신청 (KOGL 제1유형=상업가능 확인)
- [ ] **apihub.kma.go.kr**(기상청 API허브) → 해양관측(파고부이) 키
- [ ] **바다누리**(국립해양조사원) → 조위/조류예보 API 키
- [ ] **Cloudflare** 가입 → Pages·Workers·R2 활성화 (무료 한도)
- [ ] **NOAA NOMADS**(GFS-Wave) = 키 불필요, URL만 확인

## 법적 필수 (Phase 5)
- 출처 표기: © OpenStreetMap · 기상청 · 국립해양조사원 · NOAA (지도 하단에 이미 표기 중)
- 각 공공데이터 KOGL **제1유형(상업 가능)** 개별 확인
- 타일·데이터 자가 호스팅으로 트래픽 폭탄 방지 (Phase 2에서 R2)

## ⚠️ 데이터 라이선스 핵심
- **Open-Meteo 무료 = 비상업 전용** → 상업 배포엔 못 씀. 현재는 *애니메이션 검증용 임시*.
- 상업용 정답 = **NOAA GFS-Wave(퍼블릭도메인) + 기상청(KOGL1)** → Phase 2에서 교체.
