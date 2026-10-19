"""규칙 기반 분류·중요도 1차 판정 (AI 없음). 모든 판정에 근거 한 줄을 남긴다.

분류: 신기술 / 스킬·플러그인·MCP / 사용법·워크플로 / 보안 / 기타
중요도: 높음(내 profile 직접 영향, 보안, 사용법을 바꾸는 변경, 급등) · 보통 · 낮음(단순 버그 수정, 내 스택과 무관)
AI 판단은 digest(data/digests/)에 따로 저장하고 여기 결과(classified_by: rule)와 섞지 않는다.
"""
import re
from datetime import date, timedelta

from . import korean

CATEGORIES = ["보안", "스킬·플러그인·MCP", "신기술", "사용법·워크플로", "기타"]
# 'Windows: Fixed …', '[VSCode] Added …' 같은 플랫폼 접두어 뒤의 동사
VERB = re.compile(r"^\s*(?:\[[^\]]{1,30}\]\s*|[A-Za-z][\w .-]{0,30}:\s*)?"
                  r"(Fixed|Added|Improved|Changed|Removed|Deprecated|Updated|New|Reduced|Made|Renamed)\b")
REPO_TYPES = {"candidate_new", "trending", "repo_release", "repo_renamed", "repo_archived",
              "repo_surge", "promote_suggest", "demote_suggest", "suspicious"}


def compile_kw(k):
    """단어 단위 매칭(복수·과거형·진행형 허용). 끝이 * 이면 접두어."""
    k = k.lower().strip()
    if k.endswith("*"):
        body, right = re.escape(k[:-1]), ""
    else:
        body = re.escape(k)
        right = r"(?:s|es|ed|d|ing)?(?![a-z0-9])" if k[-1].isalnum() else ""
    left = r"(?<![a-z0-9])" if k[0].isalnum() else ""
    return re.compile(left + body + right)


class Matcher:
    def __init__(self, words):
        self.items = [(w, compile_kw(w)) for w in words if w and w.strip("* ")]

    def first(self, text):
        for w, rx in self.items:
            if rx.search(text):
                return w
        return None


class Classifier:
    def __init__(self, rules, profile):
        c = rules["classify"]
        self.cat = {name: Matcher(c["category_keywords"].get(name, [])) for name in CATEGORIES[:-1]}
        self.breaking = Matcher(c["high_signals"]["breaking"])
        self.security_issue = Matcher(c["high_signals"]["security_issue"])
        self.not_using = [(i["name"], Matcher(i.get("keywords", []))) for i in profile.get("not_using", [])]
        self.model_launch = Matcher(c["high_signals"]["model_launch"])
        self.low_types = set(c.get("low_types", []))
        self.interests = [(i["name"], Matcher(i.get("keywords", []))) for i in profile.get("interests", [])]
        self.not_interested = [(i["name"], Matcher(i.get("keywords", []))) for i in profile.get("not_interested", [])]
        self.env = Matcher((profile.get("environment") or {}).get("keywords", []))
        self.stack = Matcher(profile.get("stack_keywords", []))
        inst = profile.get("installed") or {}
        self.installed = Matcher([*inst.get("skills", []), *inst.get("plugins", []), *inst.get("mcp_servers", [])])
        plan = (profile.get("plan") or "").strip().lower()
        self.plan = plan
        self.plan_rx = re.compile(rf"(?<![a-z]){re.escape(plan)}\b[^.]{{0,30}}\bplans?\b") if plan else None

    # ---- 분류 ----
    def category(self, item, text, verb):
        if item.get("quarantined"):
            return "보안", "인젝션 의심 문구로 격리됨"
        if (k := self.cat["보안"].first(text)):
            return "보안", f"키워드 '{k}'"
        t = item["type"]
        if (k := self.cat["스킬·플러그인·MCP"].first(text)) and t != "npm_unlisted":
            return "스킬·플러그인·MCP", f"키워드 '{k}'"
        if t == "claude_code_change":
            if verb in ("Added", "New"):
                return "신기술", f"새 기능({verb})"
            if verb in ("Changed", "Removed", "Deprecated", "Renamed"):
                return "사용법·워크플로", f"동작 변경({verb})"
            if verb == "Fixed":
                return "기타", "버그 수정"
        if t == "official_repo":
            return "신기술", "anthropics 공식 새 레포"
        if t == "benchmark_update":
            return "신기술", "AI 코딩 벤치마크"
        if t in REPO_TYPES:
            return "스킬·플러그인·MCP", "생태계 레포"
        if t == "official_post" and item.get("source") == "anthropic_engineering":
            return "사용법·워크플로", "Anthropic 엔지니어링 블로그"
        for name in ("신기술", "사용법·워크플로"):
            if (k := self.cat[name].first(text)):
                return name, f"키워드 '{k}'"
        if t == "official_release_note":
            return "신기술", "공식 릴리스 노트"
        return "기타", "해당 분류 키워드 없음"

    # ---- 중요도 ----
    def importance(self, item, text, verb, category):
        t = item["type"]
        if item.get("quarantined"):
            return "보통", "인젝션 의심으로 격리 — 원문 직접 확인 전 사용 금지"
        if category == "보안":
            if (k := self.security_issue.first(text)):
                return "높음", f"보안 이슈 신호 '{k}'"
            return "보통", "보안 관련 언급 (구체적 이슈 신호 없음)"
        if t == "repo_surge":
            return "높음", "스타 급등"
        if t == "benchmark_update":
            return ("높음", "벤치마크 1위 변경") if "1위 변경" in (item.get("title") or "") else ("보통", "벤치마크 새 기록")
        if t in ("promote_suggest", "demote_suggest"):
            return "보통", "watchlist 변경 제안 (자동 반영 안 함)"
        if t == "suspicious":
            return "보통", "스타 패턴 참고 경고 (바이럴과 구분 어려움)"
        if t in self.low_types:
            return "낮음", "기록 누락 표시 (정보성)"
        is_fix = verb == "Fixed"
        # 나에게 직접 해당하는 신호를 '쓰지 않는 기능' 판정보다 먼저 본다 (예: 'Max and Team plans')
        if self.plan_rx and self.plan_rx.search(text):
            return "높음", f"내 요금제({self.plan.title()}) 관련"
        if (k := self.installed.first(text)):
            return "높음", f"설치된 도구 '{k}' 관련"
        if t in ("official_release_note", "official_post") and (k := self.model_launch.first(text)):
            return "높음", f"새 모델·제품 출시 신호 '{k}'"
        for n, m in self.not_using:
            if (k := m.first(text)):
                return "낮음", f"내가 쓰지 않는 기능·환경 '{n}' ('{k}')"
        interest = next(((n, k) for n, m in self.interests if (k := m.first(text))), None)
        stack = self.stack.first(text)
        changes_usage = verb in ("Changed", "Removed", "Deprecated", "Renamed") or (
            verb is None and t in ("official_release_note", "official_post"))
        if changes_usage and (k := self.breaking.first(text)):
            return "높음", f"기존 사용법을 바꾸는 변경 신호 '{k}'"
        minor = verb in ("Improved", "Reduced", "Made", "Updated")   # 소소한 개선은 관심 분야여도 '보통'
        if interest and not is_fix and not minor:
            return "높음", f"관심 분야 '{interest[0]}' 키워드 '{interest[1]}'"
        if not interest and not stack:
            for n, m in self.not_interested:
                if (k := m.first(text)):
                    return "낮음", f"관심 없는 분야 '{n}' ('{k}')"
        env = self.env.first(text)
        if is_fix:
            if env:
                return "보통", f"내 환경({env}) 버그 수정"
            if interest:
                return "보통", f"관심 분야 '{interest[0]}' 버그 수정"
            return "낮음", "단순 버그 수정"
        if minor and interest:
            return "보통", f"관심 분야 '{interest[0]}' 소소한 개선"
        if env:
            return "보통", f"내 환경({env}) 관련 변경"
        if stack:
            return "보통", f"내 스택 '{stack}' 관련"
        if category == "기타" and t in ("hn_mention", "official_post"):
            return "낮음", "개발 주제와 무관한 일반 소식"
        if t == "candidate_new":
            return "보통", "신규 발견 (별 속도 상위)"
        if t == "trending":
            return "보통", "GitHub 트렌딩"
        return "보통", "특이 신호 없음 (기본값)"

    def classify(self, item):
        text = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
        m = VERB.match(item.get("title") or "")
        verb = m.group(1) if m else None
        category, why_cat = self.category(item, text, verb)
        level, why = self.importance(item, text, verb, category)
        return {"category": category, "importance": level, "importance_reason": why, "category_reason": why_cat,
                "headline_ko": korean.headline(item, verb), "classified_by": "rule"}


def reclassify_recent(ctx):
    """최근 N일(KST) 항목 파일을 규칙으로 다시 판정. 결과가 같으면 파일을 다시 쓰지 않는다(멱등)."""
    clf = Classifier(ctx.rules, ctx.profile)
    days = ctx.rules["classify"]["reclassify_days"]
    since = (date.fromisoformat(ctx.store.today) - timedelta(days=days)).isoformat()
    changed_files = changed_items = 0
    for d in sorted(ctx.store.index.get("item_dates", {})):
        if d < since:
            continue
        rel = f"items/{d}.json"
        day = ctx.store.load_json(rel, None)
        if not day:
            continue
        dirty = False
        for item in day["items"]:
            if item.get("classified_by") == "ai":
                continue
            new = clf.classify(item)
            if any(item.get(k) != v for k, v in new.items()):
                item.update(new)
                dirty = True
                changed_items += 1
        if dirty:
            ctx.store.write_json(rel, day)
            changed_files += 1
    return f"reclassified_items={changed_items} files={changed_files}"
