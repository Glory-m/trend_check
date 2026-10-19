---
name: watch
description: 핵심 watchlist.yml에 레포를 추가하거나 제거한다 (자동 추가 금지 — 사용자가 직접 호출할 때만).
model: sonnet
argument-hint: "<owner/repo> | remove <owner/repo> | list"
disable-model-invocation: true
allowed-tools: Bash(python scripts/watch.py *)
---

# /watch — watchlist 관리

요청: $ARGUMENTS

1. 요청 해석:
   - `owner/repo`만 있으면 → 추가: `python scripts/watch.py add owner/repo --note "<한 줄 메모>"`
   - `remove owner/repo` → 제거: `python scripts/watch.py remove owner/repo`
   - `list` 또는 빈 요청 → `python scripts/watch.py list`
   메모는 사용자가 말한 이유를 짧게(80자 이내) 쓴다. 없으면 생략.
2. 스크립트는 네트워크를 쓰지 않는다. 레포가 수집 데이터에 없으면 "존재 미확인 — 다음 수집 때 확인"이라고 전한다.
   레포를 확인하려고 외부 URL을 가져오지 않는다.
3. 변경 후 `git diff watchlist.yml`로 바뀐 줄을 보여 준다.
4. "커밋하고 push할까요? push하면 다음 수집(매일 06:17 KST)부터 반영됩니다"라고 묻는다.
   승인 시 `git add watchlist.yml` → `git commit -m "watch: add|remove owner/repo"` → push는 재확인 후.
5. 추가하려는 레포에 스타 참고 경고나 SKILL.md 위험 신호가 있으면(`python scripts/context.py`에서 확인 가능) 먼저 알린다.
