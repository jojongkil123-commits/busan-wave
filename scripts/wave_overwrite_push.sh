#!/usr/bin/env bash
# 바람·파도·수온 텍스처 올리기 — main 을 '부모 없는 커밋 하나'로 덮어쓰기 (update-wave 전용)
# 사용: bash scripts/wave_overwrite_push.sh "<커밋 메시지>" <이번 실행이 만든 파도 파일을 모아 둔 폴더>
#
# (2026-10-15 조팀장 결정: "예전처럼 덮어쓰기") 파도 파일은 한 번에 ≈150MB 라 일반 푸시로 쌓으면 저장소가 하루 ≈0.6GB 씩 큰다
#   (10/14 일반 푸시로 바꾼 뒤 9.7GB). 예전 봇처럼 main 을 커밋 하나로 덮어써서 옛 파도 파일이 역사에 남지 않게 한다.
#   예전 봇(≈9/30)과 같은 모양: 원격 main = 봇이 만든 부모 없는 커밋 1개 (+ 그 뒤에 다른 작업이 올린 커밋들, 다음 실행 때 다시 하나로).
#   예전 봇과 다른 점(다른 작업의 커밋을 지우지 않게):
#   ① 예전엔 '마지막 커밋이 auto: 일 때만' amend 했다 → 그사이 수온 커밋이 끼면 일반 커밋이 쌓여 9/30 뒤로 역사가 다시 자랐다.
#      이제는 매번 '최신 main 의 파일 전부 + 이번 파도 파일' 로 부모 없는 커밋을 새로 만든다(git commit-tree, amend 와 결과가 같다).
#      → 다른 작업(수온·조류·물때·코드)이 올린 파일 내용은 그대로 들어간다. 커밋 기록만 하나로 접힌다(접은 커밋 제목은 본문에 남긴다).
#   ② 강제 푸시는 lease(방금 받은 그 SHA 일 때만)로만 한다. 예전의 마지막 수단 'git push --force'(무조건)는 없다.
#      받은 뒤 누가 먼저 올렸으면 거절된다 → 최신 main 을 다시 받아 그 위에서 다시 만든다(최대 6번).
#   ③ 받는 건 최신 main 한 커밋(깊이 1)뿐 — 옛 파도 파일(수 GB)을 받지 않는다. 올리는 건 바뀐 파도 파일만(≈150MB).
#   다른 작업 쪽: 일반 푸시가 거절되면 'git pull --rebase'(update-sst-obs·update-tide) 또는 data_commit_push.sh(update-tidal)가
#     최신 main 위에 자기 파일만 다시 얹는다 — 2026-10-15 로컬 시험(얕은 체크아웃 + 덮어쓰기 경합 4가지)에서 유실 0.
#   되돌리기(일반 푸시로): _backup/overwrite1015/update-wave.yml.orig 의 '커밋 & 푸시' 단계로 바꾸면 된다(이 파일은 안 쓰게 됨).
set -uo pipefail

squashed_list() {   # 이번에 접는 커밋들(최신 main 에서 뿌리까지) — 커밋 본문에 남겨 '누가 뭘 올렸는지'를 볼 수 있게. 실패해도 진행
  local base=$1 out n
  [ -n "${GITHUB_REPOSITORY:-}" ] || { echo "(접은 커밋 목록: 저장소 이름 없음)"; return 0; }
  out=$(${GH_BIN:-gh} api "repos/$GITHUB_REPOSITORY/commits?sha=$base&per_page=100" \
        --jq '.[] | "\(.sha[0:8]) \(.commit.committer.date) \(.commit.message | split("\n")[0])"' 2>/dev/null) || {
    echo "(접은 커밋 목록을 못 읽음)"; return 0; }
  n=$(printf '%s\n' "$out" | grep -c .)
  echo "이 커밋으로 접은 커밋 ${n}개$([ "$n" -ge 100 ] && echo '+')(파일 내용은 모두 이 커밋에 들어 있음):"
  printf '%s\n' "$out" | head -60
  [ "$n" -gt 60 ] && echo "… 외 $((n - 60))개"
  return 0
}

main() {
  local MSG=${1:?커밋 메시지} SAVE=${2:?파도 파일 폴더} i base tree new body
  [ -d "$SAVE" ] && [ -n "$(ls -A "$SAVE")" ] || { echo "::error::$SAVE 가 비었다"; return 1; }
  for i in 1 2 3 4 5 6; do
    if ! git fetch -q --depth=1 origin main; then echo "받기 실패($i/6)"; sleep $((i * 10)); continue; fi
    base=$(git rev-parse FETCH_HEAD)
    git checkout -q -f -B main "$base" || { sleep $((i * 10)); continue; }
    # 옛 스텝 파일을 지우고 이번 것만 — 스텝 목록이 바뀌어도(실패한 스텝·옛 wave_fine) 다른 런 격자가 섞이지 않게
    rm -f data/wind_t[0-9][0-9][0-9]* data/wave_fill_t[0-9][0-9][0-9]* data/wave_fine_t[0-9][0-9][0-9]* data/sst_t[0-9][0-9][0-9]*
    cp "$SAVE"/* data/
    git add -A data/
    tree=$(git write-tree)
    if [ "$tree" = "$(git rev-parse "$base^{tree}")" ]; then
      echo "origin/main 에 이미 같은 파일 — 올릴 것 없음"; return 0
    fi
    body=$(squashed_list "$base")
    new=$(git commit-tree "$tree" -m "$MSG" -m "$body") || { echo "commit-tree 실패"; return 1; }
    # lease = 방금 받은 base 일 때만 바꾼다. 그새 다른 작업이 올렸으면 거절 → 다시 받아서 그 위에서 다시 만든다
    if git push -q --force-with-lease="refs/heads/main:$base" origin "$new:refs/heads/main"; then
      git checkout -q -f -B main "$new"
      echo "✅ 덮어쓰기 푸시 ${new:0:8} (부모 없음, 바뀌기 전 main ${base:0:8}): $MSG"
      return 0
    fi
    echo "푸시 거절($i/6) — 받은 뒤 다른 작업이 main 을 올렸다(lease) → $((i * 10))초 뒤 최신 main 위에서 다시"
    sleep $((i * 10))
  done
  echo "::error::덮어쓰기 푸시 6번 실패 — 이번 런은 못 올림(다음 실행에서 다시)"
  return 1
}

main "$@"; exit $?
