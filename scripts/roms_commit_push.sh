#!/usr/bin/env bash
# data/roms 커밋·푸시 — update-wave 의 강제 푸시와 엇갈려 지워지지 않게 (2026-10-08 검토 수정)
# 사용: bash scripts/roms_commit_push.sh "<커밋 메시지>"   (워크플로 update-roms.yml 에서. GH_TOKEN·GITHUB_REPOSITORY 필요)
#
# WHY: update-wave 는 마지막 커밋이 'auto:' 면 amend → push --force-with-lease 하고, 거절되면 'git fetch origin main'(= lease 갱신) 뒤
#   다시 force 한다(끝내 안 되면 --force). 그 bot 이 실행 중(체크아웃 끝, 푸시 전 — 1회 8~11분)일 때 우리가 푸시하면 우리 커밋이 지워진다
#   → Pages 의 data/roms 가 다음 ROMS 실행(약 12시간 뒤)까지 404·옛것. 그 bot 의 HEAD 가 'auto:' 가 아니면 거꾸로 그 bot 의 일반 push 가
#   (재배치 없이) 5번 다 거절돼 그 회차 파고 갱신이 빠진다.
#   실행 기록(9/10~10/8 update-wave 100회·update-tide 55회): 스케줄이 2~6시간씩 늦게 돌아서 cron 시각만 옮겨서는 못 피한다
#   (어느 슬롯이든 ROMS 1회당 0.2~3% — 검토가 권한 03:45Z 는 오히려 2.2%로 22:45Z 0.9% 보다 나빴다).
#   update-wave 는 손대지 않는다(조팀장 승인 사항). 그래서 우리 쪽에서:
#   ① update-wave 가 실행 중이면 끝날 때까지 기다렸다 푸시한다 — 그 bot 의 일반 push 도 지킨다.
#   ② 푸시한 순간 실행 중이던 update-wave 가 끝나면 우리 커밋이 origin/main 에 남았는지 본다 → 지워졌으면 같은 파일로 새로 커밋해 다시 푸시.
#   ③ 'git pull --rebase' 대신 매번 최신 origin/main 위에 data/roms 만 다시 얹는다. 얕은 체크아웃(depth 1)에서 원격이 amend 되면
#      rebase 가 남의 옛 커밋까지 다시 얹을 수 있다. data/roms 는 이 작업만 쓰므로 '다시 얹기'가 rebase 와 같은 결과이고 더 단순하다.
#   강제 푸시는 절대 하지 않는다(히스토리를 고쳐 쓰지 않음). 상태 API 를 못 읽으면 기다리지 않고 예전처럼 진행한다(경고만).
set -uo pipefail
MSG=${1:?커밋 메시지}
DIR=data/roms
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY 없음}
WAVE_WF=${WAVE_WF:-update-wave.yml}
GH=${GH_BIN:-gh}
PRE_WAIT_MAX=${PRE_WAIT_MAX:-1200}    # 푸시 전 기다림 상한(초) — update-wave 1회 8~11분, 드물게 33분
POST_WAIT_MAX=${POST_WAIT_MAX:-1500}  # 푸시 뒤 '그 bot 이 끝났나' 기다림 상한(초)
POLL=${POLL:-30}

[ -d "$DIR" ] || { echo "$DIR 없음 — 올릴 것 없음"; exit 0; }
SAVE=$(mktemp -d)
cp -a "$DIR/." "$SAVE/"          # 이번 실행이 만든 data/roms — 다시 얹을 때마다 이것을 쓴다

# 실행 중인 update-wave run id(공백 구분). API 실패 → 반환 1
wave_running() {
  local out
  out=$($GH api "repos/$REPO/actions/workflows/$WAVE_WF/runs?status=in_progress&per_page=20" --jq '.workflow_runs[].id' 2>&1) || {
    echo "update-wave 상태 API 실패: ${out:0:160}" >&2; return 1; }
  echo $out
}

# update-wave 가 실행 중이 아닐 때까지(상한 PRE_WAIT_MAX)
wait_wave() {
  local t=0 ids
  while :; do
    ids=$(wave_running) || { echo "::warning::update-wave 실행 상태를 못 읽음 — 기다리지 않고 푸시"; return 0; }
    [ -z "$ids" ] && return 0
    if [ "$t" -ge "$PRE_WAIT_MAX" ]; then
      echo "::warning::update-wave(run $ids)가 ${PRE_WAIT_MAX}s 넘게 실행 중 — 그냥 푸시(뒤에서 지워졌는지 확인)"; return 0
    fi
    echo "update-wave 실행 중(run $ids) — 푸시 전에 ${POLL}s 기다림(누적 ${t}s)"
    sleep "$POLL"; t=$((t + POLL))
  done
}

# 주어진 run 들이 모두 끝날 때까지(상한 POST_WAIT_MAX). 못 기다리면 반환 1
wait_runs() {
  local t=0 id st left
  while :; do
    left=""
    for id in $1; do
      st=$($GH api "repos/$REPO/actions/runs/$id" --jq .status 2>/dev/null) || st="?"
      [ "$st" = "completed" ] || left="$left $id"
    done
    [ -z "$left" ] && return 0
    if [ "$t" -ge "$POST_WAIT_MAX" ]; then
      echo "::warning::update-wave(run${left})가 ${POST_WAIT_MAX}s 안에 안 끝남 — ROMS 커밋이 남았는지 확인 못 함(다음 실행이 다시 올린다)"; return 1
    fi
    sleep "$POLL"; t=$((t + POLL))
  done
}

# 최신 origin/main 위에 data/roms 를 얹어 커밋·일반 푸시. 0 푸시함 · 2 이미 같음(올릴 것 없음) · 1 실패
commit_on_latest() {
  git fetch -q --depth=50 origin main || return 1
  git checkout -q -f -B main FETCH_HEAD || return 1      # 로컬 가지만 맞춘다 — 원격 히스토리는 건드리지 않는다
  mkdir -p "$DIR" && cp -a "$SAVE/." "$DIR/"
  git add -A "$DIR"
  git diff --cached --quiet && return 2
  git commit -q -m "$1" || return 1
  git push -q origin HEAD:main
}

push_loop() {
  local i rc
  for i in 1 2 3 4 5; do
    wait_wave
    commit_on_latest "$1"; rc=$?
    [ "$rc" -eq 0 ] && return 0
    [ "$rc" -eq 2 ] && return 2
    echo "푸시 실패($i/5) — $((i * 10))초 뒤 다시"
    sleep $((i * 10))
  done
  return 1
}

for round in 1 2 3; do
  m="$MSG"; [ "$round" -gt 1 ] && m="$MSG (다시 올림 $round: update-wave 강제 푸시에 지워짐)"
  push_loop "$m"; rc=$?
  if [ "$rc" -eq 2 ]; then echo "origin/main 에 이미 같은 data/roms — 올릴 것 없음"; exit 0; fi
  if [ "$rc" -ne 0 ]; then echo "::warning::ROMS 푸시 5번 실패 — 다음 실행에서 다시 만든다"; exit 1; fi
  mine=$(git rev-parse HEAD)
  if ! ids=$(wave_running); then echo "푸시 ${mine:0:8} — update-wave 상태를 못 읽어 사후 확인 생략"; exit 0; fi
  if [ -z "$ids" ]; then echo "✅ 푸시 ${mine:0:8} — 그 순간 실행 중인 update-wave 없음"; exit 0; fi
  echo "푸시 ${mine:0:8} — 그 순간 update-wave 실행 중(run $ids) → 끝난 뒤 우리 커밋이 남았는지 확인"
  wait_runs "$ids" || exit 0
  git fetch -q --depth=50 origin main || { echo "::warning::확인용 fetch 실패"; exit 0; }
  if git merge-base --is-ancestor "$mine" FETCH_HEAD; then echo "✅ ROMS 커밋 ${mine:0:8} 이 origin/main 에 남아 있음"; exit 0; fi
  echo "::warning::update-wave 강제 푸시에 ROMS 커밋 ${mine:0:8} 이 지워짐 — 같은 파일로 다시 올림($round/3)"
done
echo "::warning::3번 다시 올렸는데도 지워짐 — 다음 실행에서 다시"
exit 1
