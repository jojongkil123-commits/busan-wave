#!/usr/bin/env bash
# data/roms 커밋·푸시 — update-wave 의 강제 푸시와 엇갈려 지워지지 않게 (2026-10-08 검토 수정)
# 사용: bash scripts/roms_commit_push.sh "<커밋 메시지>"   (워크플로 update-roms.yml 에서. GH_TOKEN·GITHUB_REPOSITORY 필요)
# (2026-10-09 조팀장 요청: 윈디와 같은 조류, 전국) 본문은 폴더 인자를 받는 data_commit_push.sh 로 옮겼다 — 전국 조류(data/tidal)도
#   같은 방어를 쓴다. 이 파일은 data/roms 로 부르는 껍데기(동작 같음). WHY·절차 설명은 data_commit_push.sh 머리에.
exec bash "$(dirname "$0")/data_commit_push.sh" "${1:?커밋 메시지}" data/roms
