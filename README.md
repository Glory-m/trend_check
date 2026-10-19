# trend-watch

Claude Code·새 모델·스킬/플러그인/MCP·사용법 트렌드를 매일 모아 **내 프로필 기준으로** 정리하는 개인 관제실.

- 사이트(공개, 보기 전용): **https://glory-m.github.io/trend_check/**
- 로컬(내 PC): 같은 사이트 + **AI 비서 채팅** + `/brief` 같은 Claude Code 스킬

```
매일 06:17 KST  GitHub Actions ── 수집·분류·인젝션 검사 (AI·API 키 없음) ──▶ data/ 커밋
                                                                          │
     휴대폰·PC 브라우저 ◀── GitHub Pages (보기 전용) ◀──────────────────────┤
                                                                          │
     내 PC: git pull ──▶ /brief · 비서 채팅 (구독 계정의 Claude) ──▶ 요약·한국어 번역 저장
```

---

## 매일 쓰는 법

| 상황 | 할 일 |
|---|---|
| 잠깐 훑어보기 (휴대폰 OK) | 사이트 열기 → **▶ 1분 브리핑 보기** |
| PC에서 내 기준 정리 | 이 폴더에서 `git pull` → Claude Code에서 `/brief` |
| 대화하듯 묻기 | `python scripts/serve.py` → http://127.0.0.1:8765 → 오른쪽 아래 **비서** |

`/brief`는 요약과 함께 핵심 항목의 **한국어 번역**을 저장합니다. 저장·커밋·push까지 하면 공개 사이트도 한국어로 갱신됩니다.

### Claude Code 스킬

| 스킬 | 하는 일 | 모델 |
|---|---|---|
| `/brief` | 마지막 확인 이후 변경 브리핑 (+ 한국어 번역 갱신, digest 저장 제안) | Sonnet |
| `/weekly` | 이번 주 정리 + 지난주 대비 추이 | Sonnet |
| `/explore <주제>` | 주제별 모아보기 (예: `/explore 브라우저 테스트`) | Sonnet |
| `/recommend` | 내 프로필 기준 추천 (비용·충돌·신뢰도·보안 신호 포함) | Opus |
| `/design-my-setup` | 내 세팅 추가/제거/유지 diff 제안 | Opus |
| `/watch owner/repo` | 핵심 watchlist 추가·제거 (직접 호출할 때만) | Sonnet |
| `/profile` | `profile.yml` 갱신 인터뷰 (직접 호출할 때만) | Sonnet |

기간은 이렇게 해석합니다 (표시는 항상 한국시간):
- 기간 언급 없음 → 마지막 확인(`state/last_seen.json`) 이후. 단, "기록하지 마"라고 하면 확인 시각을 갱신하지 않음
- "오늘" → 오늘 00:00부터 / "이번 주" → 이번 주 월요일 00:00부터 / "최근 N일" → 지금부터 N×24시간

---

## 처음 설치 (새 PC)

필요한 것: Git, Python 3.11+, Claude Code(구독 계정 로그인).

```bash
git clone https://github.com/Glory-m/trend_check.git
cd trend_check
pip install -r requirements.txt

# 커밋 전 검사(테스트·비밀키·숨김문자·개인 키워드) 켜기
git config core.hooksPath .githooks
# 개인 이메일이 공개 레포에 남지 않게 (GitHub noreply 주소)
git config user.email "<숫자>+<아이디>@users.noreply.github.com"
# 이 폴더는 HTTPS 인증서 검증을 켠다 (전역 설정과 무관하게)
git config http.sslVerify true
```

**`guard.local.txt` 만들기** (커밋되지 않는 로컬 전용 파일). 회사명·사내 도메인처럼 **공개 레포에 절대 올라가면 안 되는 단어**를 한 줄에 하나씩 적어 두면, 커밋할 때 그 단어가 있으면 막아 줍니다.

### Claude Code가 구독 계정으로 로그인됐는지 확인 (`/status`)
이 프로젝트는 **Anthropic API 키를 쓰지 않습니다.** 모든 AI 작업은 구독 계정으로 돌아야 합니다.

1. 이 폴더에서 Claude Code를 열고 `/status` 입력
2. 로그인 방식이 **Claude 계정(Pro/Max)** 인지 확인. "API key"로 나오면 구독이 아니라 API 과금입니다.
3. API 키 환경변수가 비어 있는지 확인. 값이 나오면 지우세요.
   - PowerShell: `echo $env:ANTHROPIC_API_KEY` → 아무것도 안 나와야 정상
   - bash: `echo $ANTHROPIC_API_KEY`

---

## GitHub 설정 (한 번만)

| 항목 | 설정 |
|---|---|
| Actions | 따로 할 것 없음. 워크플로가 쓰기 권한을 직접 선언함. 매일 06:17 KST 자동 실행 |
| 수동 수집 | Actions → **collect** → **Run workflow** |
| Pages | Settings → Pages → Branch `main` / `/ (root)` → Save |
| 계정 보안 | GitHub 2단계 인증(2FA) 켜기 권장 |

---

## 폴더 구조

```
profile.yml            내 프로필 (스택·관심 분야·안 쓰는 것·설치 도구·요금제) → 중요도 판정 기준
watchlist.yml          핵심 추적 레포 (수동 관리, /watch)
config/rules.yml       수집 범위, 급등·승격 임계값, 분류 키워드
collector/             수집기 (python -m collector) — Actions에서 실행
scripts/               window.py(기간·필터) explore.py context.py ko.py watch.py serve.py guard.py
.claude/               스킬 7개, 권한 규칙, 위험 명령 차단 훅
index.html, site/      사이트 (빌드 도구·외부 라이브러리 없음)
data/                  수집 결과 (Actions가 커밋)
  items/<날짜>.json      그날 처음 수집된 항목 (분류·중요도·근거·한국어 머리말)
  ko/<날짜>.json         AI 한국어 번역 (classified_by: ai)
  digests/<날짜>.md      /brief·/weekly 요약
  snapshots/ series.json metrics.json   레포 별 이력·지표
  security/<날짜>.json   그날의 인젝션 검사 결과
  health.json            수집 상태·실패 기록
```

---

## 보안 원칙

- **API 키 없음**: Actions는 GitHub 자동 토큰만, AI는 내 PC의 구독 계정만 씁니다.
- **수집 데이터는 믿지 않는다**: 레포 설명·뉴스 제목 같은 외부 글은 저장 전에 규칙으로 인젝션 검사를 하고, 의심되면 원문 대신 `[격리됨]`으로 바꿉니다. AI에게 넘기기 직전에 한 번 더 검사합니다.
- **설치·실행 금지**: 어떤 스킬·플러그인·MCP도 자동 설치하지 않습니다. 수집한 코드는 실행하지 않습니다. SKILL.md의 위험 신호(네트워크·자격 증명·셸)는 Actions에서 감사해 추천할 때 경고합니다.
- **내 PC 보호**: 이 폴더의 Claude는 PreToolUse 훅이 외부 접속·설치·비밀 파일 읽기·파괴적 명령을 막습니다. 로컬 비서는 `127.0.0.1` 전용이고 조회·저장 도구만 씁니다.
- **공개 레포 보호**: 커밋 전 검사(테스트, 비밀키 패턴, 숨김문자, 금지 파일, 개인 키워드, noreply 이메일). 외부 Actions는 커밋 해시로 고정했습니다.

---

## 문제 해결

| 증상 | 원인·해결 |
|---|---|
| 사이트·`/brief`에 "업데이트 지연" 경고 | 마지막 수집이 24시간 넘음 → Actions에서 collect 수동 실행, PC는 `git pull` |
| `python -m collector`가 SSL 오류 (회사 네트워크) | SSL 검사 프록시 때문. 로컬 실행에서만 `TREND_RELAX_X509_STRICT=1` (검증은 유지) |
| 로컬 수집이 rate limit | 토큰 없이 돌면 시간당 60회(공유 IP면 더 적음). 실제 수집은 Actions가 하므로 로컬은 개발용 |
| "보안 훅 차단" 메시지 | 정상 동작. 정말 필요한 명령은 직접 터미널에서 실행 |
| 비서가 "허용되지 않은 작업 N건" | 정상. 비서는 조회·번역·요약 저장만 가능 (커밋·설치 불가) |
| 비서 버튼이 안 보임 | `python scripts/serve.py`로 열었는지 확인 (GitHub Pages·일반 정적 서버에서는 숨김) |

테스트: `python -m unittest discover -s tests`
