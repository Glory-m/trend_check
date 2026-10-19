"""Claude Code 변경 수집 — CHANGELOG.md · GitHub releases · npm 버전 목록 교차 확인."""
import hashlib
import re
from datetime import timedelta

from .timeutil import parse_iso

REPO = "anthropics/claude-code"
CHANGELOG_RAW = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
CHANGELOG_API = f"/repos/{REPO}/contents/CHANGELOG.md"
CHANGELOG_URL = f"https://github.com/{REPO}/blob/main/CHANGELOG.md"
RELEASES = f"/repos/{REPO}/releases?per_page=100"
NPM = "https://registry.npmjs.org/@anthropic-ai/claude-code"

VERSION_HEADING = re.compile(r"^##\s+\[?v?(\d+\.\d+\.\d+)\]?")
STABLE = re.compile(r"^\d+\.\d+\.\d+$")


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def parse_bullets(lines):
    """'- ' 불릿을 한 항목으로. 들여쓴 하위 불릿·이어지는 줄은 부모에 붙인다."""
    out = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if re.match(r"^[-*]\s+", line):
            out.append(re.sub(r"^[-*]\s+", "", line).strip())
        elif out and (line.startswith(" ") or line.startswith("\t")):
            sub = re.sub(r"^\s*[-*]\s+", "", line).strip()
            out[-1] = f"{out[-1]} / {sub}" if re.match(r"^\s*[-*]\s+", line) else f"{out[-1]} {sub}"
    return out


def parse_changelog(text):
    versions, current, buf = {}, None, []
    for line in text.splitlines():
        m = VERSION_HEADING.match(line)
        if m or line.startswith("## "):
            if current:
                versions[current] = parse_bullets(buf)
            current, buf = (m.group(1) if m else None), []
        elif current:
            buf.append(line)
    if current:
        versions[current] = parse_bullets(buf)
    return versions


def item_id(version, text):
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return f"cc:{version}:{hashlib.sha1(norm.encode('utf-8')).hexdigest()[:10]}"


def fetch_changelog(ctx):
    try:
        return ctx.client.get(CHANGELOG_RAW).text()
    except Exception as e:  # SSL 검사 프록시 등 — API로 대체 (core 한도 1회 소모)
        ctx.warn("claude_code", f"raw CHANGELOG 실패, API로 대체: {e}")
        return ctx.client.get(CHANGELOG_API, accept="application/vnd.github.raw+json").text()


def collect(ctx):
    store, now = ctx.store, ctx.now
    changelog = parse_changelog(fetch_changelog(ctx))

    releases = {}
    for r in ctx.client.get(RELEASES).json():
        tag = (r.get("tag_name") or "").lstrip("v")
        if STABLE.match(tag) and not r.get("draft"):
            releases[tag] = {"published_at": r.get("published_at"), "url": r.get("html_url"),
                             "bullets": parse_bullets((r.get("body") or "").splitlines())}

    npm_doc = ctx.client.get(NPM).json()
    npm = {v: t for v, t in npm_doc.get("time", {}).items() if STABLE.match(v)}

    state = store.load_json("claude_code/versions.json", None)
    bootstrap = state is None
    state = state or {"versions": {}}
    vs = state["versions"]
    recent = timedelta(days=ctx.rules["bootstrap"]["recent_days"])
    grace = timedelta(hours=ctx.rules["claude_code"]["unlisted_grace_hours"])

    emitted = 0
    for v in sorted(set(changelog) | set(releases) | set(npm), key=vkey):
        rec = vs.get(v) or {"first_seen_at": store.now_iso}
        rel = releases.get(v)
        published = npm.get(v) or (rel or {}).get("published_at")
        pub_dt = parse_iso(published)
        is_recent = pub_dt is not None and now - pub_dt <= recent
        rec.update({
            "in_changelog": v in changelog,
            "in_release": rel is not None,
            "in_npm": v in npm,
            "npm_published_at": npm.get(v),
            "release_published_at": (rel or {}).get("published_at"),
        })
        if v in changelog:
            bullets, source = changelog[v], "changelog"
        elif rel and rel["bullets"]:
            bullets, source = rel["bullets"], "github_release"
        else:
            bullets, source = [], None
        rec["bullet_source"] = source
        rec["bullet_count"] = len(bullets)

        if not rec.get("emitted"):
            if bullets and (not bootstrap or is_recent):
                url = rel["url"] if rel else CHANGELOG_URL
                for b in bullets:
                    emitted += store.add_item({
                        "id": item_id(v, b), "type": "claude_code_change",
                        "title": b, "url": url, "repo": REPO, "version": v,
                        "source": source, "published_at": published,
                    })
                rec["emitted"] = True
            elif bootstrap and not is_recent:
                rec["emitted"] = True   # 과거 이력 — 항목으로 만들지 않음 (history는 changelog.json)

        # npm에만 있고 CHANGELOG에 없는 버전 → '기록 누락'
        if rec["in_npm"] and not rec["in_changelog"] and not rec.get("unlisted_reported"):
            if pub_dt and now - pub_dt >= grace:
                if not bootstrap or now - pub_dt <= recent + grace:
                    store.add_item({
                        "id": f"cc-unlisted:{v}", "type": "npm_unlisted",
                        "title": f"Claude Code {v}: npm에는 배포됐지만 CHANGELOG에 기록 없음 (기록 누락)",
                        "body": "GitHub release 본문 있음" if rel else "GitHub release도 없음",
                        "url": f"https://www.npmjs.com/package/@anthropic-ai/claude-code/v/{v}",
                        "repo": REPO, "version": v, "source": "npm", "published_at": published,
                    })
                rec["unlisted_reported"] = True
        vs[v] = rec

    tags = npm_doc.get("dist-tags", {})
    state.update({
        "updated_at": store.now_iso,
        "dist_tags": {k: tags[k] for k in sorted(tags)},
        "summary": {
            "total": len(vs),
            "changelog": sum(r["in_changelog"] for r in vs.values()),
            "npm": sum(r["in_npm"] for r in vs.values()),
            "release": sum(r["in_release"] for r in vs.values()),
            "npm_only": sorted((v for v, r in vs.items() if r["in_npm"] and not r["in_changelog"]), key=vkey),
            "changelog_not_on_npm": sorted((v for v, r in vs.items() if r["in_changelog"] and not r["in_npm"]), key=vkey),
        },
        "versions": {v: vs[v] for v in sorted(vs, key=vkey, reverse=True)},
    })
    store.write_json("claude_code/versions.json", state)
    # /explore용 전체 이력 (최신순). 내용이 같으면 파일도 같다.
    store.write_json("claude_code/changelog.json", {
        "source": CHANGELOG_URL,
        "versions": [{"version": v, "published_at": npm.get(v),
                      "bullets": [store.clean(b, 1000, "changelog", f"cc:{v}", "bullet", CHANGELOG_URL)
                                  for b in changelog[v]]}
                     for v in sorted(changelog, key=vkey, reverse=True)],
    })
    return f"versions={len(vs)} new_items={emitted} bootstrap={bootstrap} latest={tags.get('latest')}"
