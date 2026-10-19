"""Anthropic 공식 소스 — 새 모델·API·앱 기능(릴리스 노트), 뉴스·엔지니어링 블로그, anthropics 조직의 새 레포.

페이지 구조가 바뀌면 해당 단계만 실패하고(fail-soft) health.json에 기록된다.
"""
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone

from .timeutil import parse_iso

PLATFORM_NOTES = "https://platform.claude.com/docs/en/release-notes/overview.md"
PLATFORM_NOTES_URL = "https://platform.claude.com/docs/en/release-notes/overview"
APPS_NOTES = "https://support.claude.com/en/articles/12138966-release-notes"
NEWS = "https://www.anthropic.com/news"
ENGINEERING = "https://www.anthropic.com/engineering"
ORG_REPOS = "/orgs/anthropics/repos?sort=created&direction=desc&per_page=30"

DATE_RX = re.compile(r"\b([A-Z][a-z]{2,8}) (\d{1,2}), (\d{4})\b")


def parse_date(text):
    """'October 15, 2026' / 'Oct 6, 2026' → UTC 자정 ISO. 실패하면 None."""
    m = DATE_RX.search(text or "")
    if not m:
        return None
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
            return d.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def md_to_text(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)               # 이미지 제거
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)           # 링크 → 텍스트
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s.replace("**", "")).strip()


def html_to_text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def h10(*parts):
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


class SourceState:
    """출처별 첫 실행 여부 — 첫 실행 때는 과거 글을 '새 항목'으로 쏟아내지 않는다."""

    def __init__(self, ctx, name):
        self.ctx, self.name = ctx, name
        self.state = ctx.store.load_json("official/state.json", {})
        self.bootstrap = name not in self.state
        self.window = timedelta(days=ctx.rules["official"]["bootstrap_days"])

    def should_emit(self, published):
        if not self.bootstrap:
            return True
        p = parse_iso(published)
        return p is not None and self.ctx.now - p <= self.window

    def offer(self, item):
        """첫 실행이면 최근 글만 항목으로, 나머지는 '이미 본 것'으로 기록. 이후에는 새 글 전부 항목으로."""
        if self.should_emit(item.get("published_at")):
            return self.ctx.store.add_item(item)
        self.ctx.store.mark_seen(item["id"])
        return False

    def done(self, count):
        self.state = self.ctx.store.load_json("official/state.json", {})
        rec = self.state.get(self.name) or {"first_run_at": self.ctx.store.now_iso}
        rec.update({"last_ok_at": self.ctx.store.now_iso, "last_parsed": count})
        self.state[self.name] = rec
        self.ctx.store.write_json("official/state.json", dict(sorted(self.state.items())))


def platform_notes(ctx):
    st = SourceState(ctx, "platform_release_notes")
    text = ctx.client.get(PLATFORM_NOTES).text()
    sections = re.split(r"^###\s+", text, flags=re.M)[1:]
    if not sections:
        raise RuntimeError("플랫폼 릴리스 노트 구조 변경 — '### 날짜' 섹션 없음")
    parsed = added = 0
    for sec in sections:
        head, _, body = sec.partition("\n")
        published = parse_date(head)
        if not published:
            continue
        bullets, cur = [], None
        for line in body.splitlines():
            if re.match(r"^[*-]\s+", line):
                cur = md_to_text(re.sub(r"^[*-]\s+", "", line))
                bullets.append(cur)
            elif cur is not None and line.startswith("  ") and line.strip():
                bullets[-1] = f"{bullets[-1]} {md_to_text(line)}"
        for b in bullets:
            parsed += 1
            added += st.offer({
                "id": f"platform-rn:{published[:10]}:{h10(b)}", "type": "official_release_note",
                "title": b, "url": PLATFORM_NOTES_URL, "source": "anthropic_release_notes",
                "published_at": published, "repo": None,
            })
    st.done(parsed)
    return f"parsed={parsed} new_items={added} bootstrap={st.bootstrap}"


def apps_notes(ctx):
    """Claude 앱(claude.ai·데스크톱·모바일) 릴리스 노트 — 새 모델 출시·요금제 변경이 여기 실린다."""
    st = SourceState(ctx, "apps_release_notes")
    page = ctx.client.get(APPS_NOTES).text()
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", page, flags=re.S)
    if len(parts) < 3:
        raise RuntimeError("앱 릴리스 노트 구조 변경 — <h3> 날짜 헤딩 없음")
    parsed = added = 0
    for i in range(1, len(parts) - 1, 2):
        published = parse_date(html_to_text(parts[i]))
        if not published:
            continue
        section = re.split(r"<h[12][^>]*>", parts[i + 1])[0]   # 다음 월 헤딩 전까지
        features, cur = [], None
        for p in re.findall(r"<p[^>]*>(.*?)</p>", section, re.S):
            txt = html_to_text(p)
            if not txt:
                continue
            bold = re.fullmatch(r"\s*<b>(.*?)</b>\s*", p, re.S)
            if bold:
                cur = {"title": html_to_text(bold.group(1)), "body": []}
                features.append(cur)
            elif cur is not None:
                cur["body"].append(txt)
            else:
                features.append(cur := {"title": txt[:120], "body": [txt]})
        for f in features:
            parsed += 1
            added += st.offer({
                "id": f"apps-rn:{published[:10]}:{h10(f['title'])}", "type": "official_release_note",
                "title": f"Claude 앱: {f['title']}", "body": " ".join(f["body"]),
                "url": APPS_NOTES, "source": "anthropic_apps_notes", "published_at": published,
            })
    st.done(parsed)
    return f"parsed={parsed} new_items={added} bootstrap={st.bootstrap}"


def _listing(ctx, url, prefix, name, source, label):
    st = SourceState(ctx, name)
    page = ctx.client.get(url).text()
    seen, parsed, added = set(), 0, 0
    for m in re.finditer(r'<a\b[^>]*href="(' + re.escape(prefix) + r'[a-z0-9-]+)"[^>]*>(.*?)</a>', page, re.S):
        path = m.group(1)
        if path in seen:
            continue
        seen.add(path)
        texts = [t for t in (html.unescape(x).strip() for x in re.split(r"<[^>]+>", m.group(2))) if t]
        published = next((parse_date(t) for t in texts if parse_date(t)), None)
        words = [t for t in texts if not parse_date(t) and " " in t]
        if not words:
            continue
        title = words[0]
        summary = next((t for t in words[1:] if len(t) > 60), None)
        parsed += 1
        added += st.offer({
            "id": f"{name}:{path.rsplit('/', 1)[-1]}", "type": "official_post",
            "title": f"{label}: {title}", "body": summary, "url": f"https://www.anthropic.com{path}",
            "source": source, "published_at": published,
        })
    if parsed == 0:
        raise RuntimeError(f"{url} 구조 변경 — 글 링크를 찾지 못함")
    st.done(parsed)
    return f"parsed={parsed} new_items={added} bootstrap={st.bootstrap}"


def news(ctx):
    return _listing(ctx, NEWS, "/news/", "anthropic_news", "anthropic_news", "Anthropic 뉴스")


def engineering(ctx):
    return _listing(ctx, ENGINEERING, "/engineering/", "anthropic_engineering", "anthropic_engineering",
                    "Anthropic 엔지니어링 블로그")


def org_repos(ctx):
    """anthropics 조직의 새 공개 레포 — 공식 신규 도구·프로토콜. 후보 풀에도 넣어 별 추이를 추적한다."""
    st = SourceState(ctx, "anthropics_org_repos")
    repos = ctx.client.get(ORG_REPOS).json()
    added = 0
    for r in repos:
        if r.get("fork") or r.get("archived") or r.get("private"):
            continue
        name = r["full_name"]
        added += st.offer({
            "id": f"org-repo:{name}", "type": "official_repo", "repo": name,
            "title": f"anthropics 새 레포: {name} (★{r.get('stargazers_count')})",
            "body": r.get("description"), "url": r.get("html_url"), "source": "github_org",
            "published_at": r.get("created_at"),
        })
        ctx.found.setdefault(name, {"info": {}, "labels": set()})
        ctx.found[name]["info"].update({k: v for k, v in {
            "tier": "candidate", "stars": r.get("stargazers_count"), "forks": r.get("forks_count"),
            "open_issues": r.get("open_issues_count"), "pushed_at": r.get("pushed_at"),
            "created_at": r.get("created_at"), "description": r.get("description"),
            "language": r.get("language"), "archived": False}.items() if v is not None})
        ctx.found[name]["labels"].add("org:anthropics")
    st.done(len(repos))
    return f"repos={len(repos)} new_items={added} bootstrap={st.bootstrap}"
