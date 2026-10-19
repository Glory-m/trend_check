---
name: profile
description: profile.yml(스택·목표·관심 분야·설치된 도구·요금제·답변 길이)을 인터뷰로 갱신한다. 사용자가 직접 호출할 때만.
model: sonnet
argument-hint: "[바꿀 항목 — 예: 설치 목록, 관심 분야]"
disable-model-invocation: true
---

# /profile — 프로필 갱신 인터뷰

요청: $ARGUMENTS

## 규칙
- 먼저 `profile.yml`을 읽고, 바꿀 항목을 정한다(요청에 없으면 "무엇을 바꿀지" 먼저 묻는다).
- **한 번에 질문 하나**, 각 질문에 **추천 답**을 함께 제시한다 (AskUserQuestion, 추천 옵션은 맨 앞에 "(추천)").
- 추측하지 않는다. 모호하면 묻는다.
- 설치 목록은 실제 설정으로 확인할 수 있다: `~/.claude/skills/` 목록과 `~/.claude/settings.json`의 enabledPlugins,
  이 폴더의 `.mcp.json`. 단, 자격 증명 파일(`.credentials.json` 등)은 읽지 않는다.
- **public 레포다.** 회사명·고객명·사내 도메인·이메일 같은 식별 정보는 profile.yml에 쓰지 않는다.
  사용자가 그런 내용을 말하면 일반화해서(예: "업무용 Spring 백엔드") 적어도 되는지 묻는다.

## 분류 규칙과 연결
`interests`, `environment`, `not_using`, `not_interested`의 `keywords`는 수집기의 중요도 판정에 쓰인다
(collector/classify.py). 관심 분야를 바꾸면 그에 맞는 영문 키워드(소문자, 단어 단위, 접두어는 `*`)도 함께 제안한다.
너무 넓은 단어(test, design, review처럼 흔한 단어)는 피한다.

## 마무리
1. `updated_at`을 오늘(KST)로 바꾼다.
2. `git diff profile.yml`로 변경을 보여 준다.
3. "커밋하고 push할까요? 다음 수집부터 분류에 반영됩니다(최근 14일 항목도 재분류)."
   승인 시 `git add profile.yml` → `git commit -m "profile: <요약>"` → push는 재확인 후.
