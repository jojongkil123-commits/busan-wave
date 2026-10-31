# 부산 파고 — 조팀장 수동 작업 매뉴얼

> 클로드가 자동으로 끝낸 것: 지도(Phase1)·파고 애니메이션·**NOAA 실데이터 텍스처(Phase2 핵심)**·자동화 워크플로 파일·배포 설정까지 **코드/파일은 전부 완성**.
> 아래는 **조팀장님 계정·승인이 필요해 대신 못 하는 것**만 모았습니다. 위에서부터 순서대로 하시면 됩니다.

---

## 0. 지금 당장 — 내 컴퓨터에서 눈으로 확인 (5분, 키 불필요)
```
cd ~/Desktop/AI/busan-wave-app
python3 -m http.server 8765
```
→ 맥 사파리/크롬에서 **http://localhost:8765** 열기 → **🌊 파고 보기** 누르기.
부산~일본·동해에 파고가 흐르면 성공(이미 NOAA 실데이터가 들어있음).
*(폰 설치·GPS는 https가 필요 → 아래 2번 배포 후 가능)*

---

## 1. 공개 배포 (Cloudflare Pages, 무료·카드만, 30분)
폰에 "어플"로 깔고 남에게 공유하려면 https 배포가 필요합니다.

1. **GitHub 가입** → 새 저장소(repo) 만들기(예: `busan-wave`), 공개/비공개 아무거나
2. 이 폴더(`busan-wave-app`)를 그 repo에 올리기:
   ```
   cd ~/Desktop/AI/busan-wave-app
   git init && git add . && git commit -m "first"
   git branch -M main
   git remote add origin https://github.com/<내아이디>/busan-wave.git
   git push -u origin main
   ```
   *(GitHub 비밀번호 대신 'Personal Access Token'을 물으면, github.com → Settings → Developer settings → Tokens에서 발급해 붙여넣기)*
3. **Cloudflare 가입**(dash.cloudflare.com) → 카드 등록(무료 한도 내 과금 0)
4. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → 위 repo 선택
5. 빌드 설정: **빌드 명령 비움**, **출력 디렉터리 = `/`(루트)** → 저장·배포
6. 몇 분 뒤 `https://busan-wave.pages.dev` 같은 주소 생김 → 폰에서 열고 **"홈 화면에 추가"**

> 이걸 해두면, 아래 4번(GitHub Actions)이 6시간마다 파고를 갱신할 때 Cloudflare가 자동 재배포합니다.

---

## 2. Phase 2 자동 갱신 켜기 (GitHub Actions, 5분, 키 불필요)
파고 데이터를 6시간마다 자동으로 최신화합니다. (NOAA는 키 불필요)

1. 위 1번으로 코드가 GitHub에 올라가 있으면, `.github/workflows/update-wave.yml`이 **자동 인식**됩니다.
2. repo → **Actions** 탭 → 워크플로 활성화(켜기) 한 번 클릭
3. 끝. 6시간마다(또는 Actions에서 'Run workflow' 수동) NOAA 최신 파고로 `data/wave.png`가 갱신·커밋되고 Cloudflare가 재배포.

> 왜 GitHub Actions? Cloudflare Worker는 GRIB 해독기(eccodes)를 못 돌립니다. GRIB→PNG 변환은 Actions(또는 맥)에서 하고, 결과 PNG만 웹에 올리는 구조가 정답입니다.

---

## 3. Phase 0 — 공공데이터 키 발급 (Phase 4 '연안 정밀·물때'용, 승인 1~2일)
> ⚠️ 위 1~2번까지만 해도 **NOAA 기반 파고 앱은 완성·배포**됩니다.
> 아래 키들은 **부산 연안 정밀 보정 + 물때**(Phase 4)를 붙일 때 필요. 미리 신청해두면 좋습니다.

### (가) data.go.kr — 기상청 단기예보·해양예보 (연안 5km 파고·물때 보조)
1. **공공데이터포털(data.go.kr)** 회원가입
2. 검색 → **"기상청_단기예보 조회서비스"** → **활용신청**(자동승인, 즉시~1일)
3. 검색 → **"기상청_해양 예보"** → 활용신청
4. 마이페이지 → 오픈API → 개발계정 → **일반 인증키(Encoding)** 복사해 둠
5. ⚠️ 각 데이터 상세에서 **이용허락범위 = "공공누리 제1유형"(상업 가능)** 인지 확인

### (나) apihub.kma.go.kr — 기상청 API허브 (파고부이 실측)
1. **기상청 API허브** 회원가입
2. 해양관측 → **파고부이/해양기상부이** API 신청 → 키 발급

### (다) 바다누리 — 국립해양조사원 (조위/조류 = 물때)
1. **바다누리(open.khoa.go.kr 또는 khoa.go.kr 오픈API)** 회원가입
2. **조석예보(고저조)·조류예보** API 키 발급
3. (참고: 해루질앱에서 쓰던 그 키와 동일 계열)

> 키 3종이 모이면 클로드한테 "키 넣어서 Phase 4(연안+물때) 붙여줘" 하시면 됩니다.

---

## 4. 데이터 수동 갱신 (자동화 켜기 전, 또는 테스트)
맥에서 직접 최신 파고를 받아 갱신하고 싶을 때:
```
python3 -m venv ~/gribenv
~/gribenv/bin/pip install eccodes cfgrib numpy pillow
~/gribenv/bin/python ~/Desktop/AI/busan-wave-app/scripts/build_wave_texture.py
```
→ `data/wave.png` + `wave_meta.json` 갱신됨. (git push 하면 배포 반영)

---

## 정리 — 지금 상태
| 단계 | 상태 | 누가 |
|---|---|---|
| Phase 1 지도+PWA | ✅ 완료 | 클로드 |
| Phase 2 NOAA 파고 텍스처 변환 | ✅ 완료(실데이터 들어있음) | 클로드 |
| Phase 2 자동 갱신(워크플로 파일) | ✅ 파일완료 / 켜기는 수동 | 1·2번 |
| Phase 3 애니메이션 | ✅ 완료 | 클로드 |
| 공개 배포 | ⬜ 수동 | **1번** |
| Phase 4 연안+물때 | ⬜ 키 필요 | **3번 후 클로드** |
| Phase 5 공유카드·마감 | ⬜ | 나중 |
