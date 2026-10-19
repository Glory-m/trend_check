"""규칙 기반 한국어 제목 (AI 없음) — 영어 원문을 대신하지 않고, 한눈에 무슨 종류의 소식인지 알려 주는 머리말.

예) "새 기능 · CLAUDE_CODE_AUTO_MODE_MODEL — Claude Code 2.1.302"
    "새 모델 출시 · Claude Haiku 5.5"
자연스러운 한국어 번역은 PC의 /brief가 AI로 만들어 data/ko/에 따로 저장한다 (classified_by: ai).
"""
import re

VERB_KO = {
    "Fixed": "버그 수정", "Added": "새 기능", "New": "새 기능", "Changed": "동작 변경", "Improved": "개선",
    "Removed": "제거", "Deprecated": "지원 중단 예고", "Updated": "업데이트", "Reduced": "개선", "Made": "개선",
    "Renamed": "이름 변경",
}
PLATFORM_KO = {
    "windows": "Windows", "vscode": "VS Code", "vs code": "VS Code", "cloud sessions": "클라우드 세션",
    "self-hosted runner": "자체 호스팅 러너", "jetbrains": "JetBrains", "macos": "macOS", "linux": "Linux",
}
PREFIX = re.compile(r"^\s*(?:\[([^\]]{1,30})\]\s*|([A-Za-z][\w .-]{0,30}):\s*)")
CODE = re.compile(r"`([^`]{2,60})`")
PRODUCT = re.compile(r"\b(Claude (?:Opus|Sonnet|Haiku|Fable) [\d.]+|Claude Managed Agents|Managed Agents|Compliance API|"
                     r"Models API|Messages API|Admin API|Agent SDK|Claude Code|Fast mode|Claude Design|Claude in Chrome|"
                     r"OpenTelemetry|MCP)\b")
OFFICIAL_RULES = [
    (re.compile(r"\blaunch(?:ed|ing)?\b|\bintroduc", re.I), "출시"),
    (re.compile(r"\bdeprecat|\bretire", re.I), "지원 중단 예고"),
    (re.compile(r"\bcan break\b|breaking", re.I), "호환성 주의"),
    (re.compile(r"\bprice|pricing|billing|credits?\b", re.I), "요금·크레딧"),
    (re.compile(r"out of (?:research )?preview|generally available|\bnow available\b", re.I), "정식 제공"),
    (re.compile(r"\bbeta\b", re.I), "베타 공개"),
    (re.compile(r"\bsecurity|vulnerab|cyber", re.I), "보안"),
]


def _key_term(text, product_first=False):
    """핵심어: Claude Code 변경은 코드 표기(`…`) 우선, 공식 노트는 제품 이름 우선."""
    order = (PRODUCT, CODE) if product_first else (CODE, PRODUCT)
    for rx in order:
        m = rx.search(text or "")
        if m:
            return m.group(1)
    return None


def headline(item, verb=None):
    """항목 종류별 한국어 머리말. 원문 제목은 그대로 두고 이 문자열을 함께 보여 준다."""
    t, title = item.get("type"), item.get("title") or ""
    repo, ver = item.get("repo"), item.get("version")
    if item.get("quarantined"):
        return "격리된 항목 · 의심 문구 감지 (원문은 링크에서 직접 확인)"
    if t == "claude_code_change":
        p = PREFIX.match(title)
        plat = None
        if p:
            raw = (p.group(1) or p.group(2) or "").strip().lower()
            plat = PLATFORM_KO.get(raw, (p.group(1) or p.group(2)).strip())
        kind = VERB_KO.get(verb, "변경")
        term = _key_term(title)
        head = f"{kind}{f'({plat})' if plat else ''}"
        return f"{head} · {term} — Claude Code {ver}" if term else f"{head} — Claude Code {ver}"
    if t == "npm_unlisted":
        return f"기록 누락 · Claude Code {ver}이 npm에만 있고 CHANGELOG에 없음"
    if t == "official_release_note":
        kind = next((ko for rx, ko in OFFICIAL_RULES if rx.search(title)), "업데이트")
        app = title.startswith("Claude 앱:")
        term = _key_term(title.removeprefix("Claude 앱:"), product_first=True)
        where = "Claude 앱" if app else "Claude 플랫폼"
        if kind == "출시" and term and term.startswith("Claude "):
            return f"새 모델·제품 출시 · {term}"
        return f"{where} {kind}" + (f" · {term}" if term else "")
    if t == "official_post":
        src = "엔지니어링 블로그" if item.get("source") == "anthropic_engineering" else "Anthropic 뉴스"
        return f"{src} · 새 글"
    if t == "official_repo":
        return f"Anthropic 새 공개 저장소 · {repo}"
    if t == "hn_mention":
        pts = re.match(r"(\d+) points", item.get("body") or "")
        return "Hacker News 화제" + (f" · {pts.group(1)}점" if pts else "")
    if t == "trending":
        period = "일간" if ":daily" in (item.get("id") or "") or "(daily)" in title else "주간"
        gained = re.search(r"([\d,]+) stars (today|this week)", title)
        return f"GitHub 트렌딩({period}) · {repo}" + (f" · ★{gained.group(1)}" if gained else "")
    if t == "candidate_new":
        stars = re.search(r"★(\d+)", title)
        return f"새로 뜨는 저장소 · {repo}" + (f" · ★{int(stars.group(1)):,}" if stars else "")
    if t == "repo_release":
        return f"새 릴리스 · {repo} {ver or ''}".strip()
    if t == "benchmark_update":
        return "벤치마크 1위 변경" if "1위 변경" in title else "벤치마크 새 기록"
    if t == "repo_surge":
        return f"스타 급등 · {repo}"
    if t == "suspicious":
        return f"스타 패턴 참고 경고 · {repo}"
    if t == "promote_suggest":
        return f"watchlist 추가 제안 · {repo}"
    if t == "demote_suggest":
        return f"watchlist 제거 검토 · {repo}"
    if t == "repo_renamed":
        return f"저장소 이름 변경 · {repo}"
    if t == "repo_archived":
        return f"유지보수 종료(보관) · {repo}"
    return "새 소식"
