"""공식 소스 — 첫 실행(bootstrap) 뒤 같은 날 재실행해도 과거 글이 새 항목으로 들어오지 않아야 한다.

2026-10-19 Actions 2회차에서 실제로 397건이 잘못 들어온 버그의 회귀 테스트.
"""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import yaml

from collector import official
from collector.store import Store
from collector.timeutil import parse_iso

RULES = yaml.safe_load((Path(__file__).resolve().parent.parent / "config/rules.yml").read_text(encoding="utf-8"))

NOTES_MD = """# Claude Platform release notes

### October 15, 2026

* Recent feature A
* Recent feature B

### March 1, 2026

* Old feature C
"""
APPS_HTML = ("<h3>October 7, 2026</h3><p><b>New model launch</b></p><p>We launched it.</p>"
             "<h2>January 2026</h2><h3>January 5, 2026</h3><p><b>Old thing</b></p><p>Old body.</p>")
LISTING = ('<a href="/news/recent-post"><span>Oct 14, 2026</span><span>Recent post title here</span></a>'
           '<a href="/news/old-post"><span>Feb 2, 2026</span><span>Old post title here</span></a>')
ORG = [{"full_name": "anthropics/new-tool", "created_at": "2026-10-16T00:00:00Z", "stargazers_count": 5},
       {"full_name": "anthropics/old-tool", "created_at": "2025-01-01T00:00:00Z", "stargazers_count": 900}]


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def text(self):
        return self.body

    def json(self):
        return self.body


class FakeClient:
    def get(self, url, **kw):
        if url == official.PLATFORM_NOTES:
            return FakeResponse(NOTES_MD)
        if url == official.APPS_NOTES:
            return FakeResponse(APPS_HTML)
        if url == official.NEWS:
            return FakeResponse(LISTING)
        if url == official.ORG_REPOS:
            return FakeResponse(ORG)
        raise AssertionError(url)


class Ctx:
    def __init__(self, d, now):
        self.now, self.rules, self.client = now, RULES, FakeClient()
        self.store = Store(d, now)
        self.found = {}


class BootstrapTest(unittest.TestCase):
    def test_second_run_adds_nothing(self):
        now = parse_iso("2026-10-19T06:30:00Z")
        with tempfile.TemporaryDirectory() as d:
            counts = []
            for run in range(3):
                ctx = Ctx(d, now + timedelta(minutes=10 * run))
                for fn in (official.platform_notes, official.apps_notes, official.news, official.org_repos):
                    fn(ctx)
                counts.append(ctx.store.flush())
            self.assertEqual(counts, [5, 0, 0])   # 1회차: 최근 글만 (A, B, 앱 1, 뉴스 1, 레포 1)
            titles = [x["title"] for x in Store(d, now).load_json("items/2026-10-19.json", None)["items"]]
            self.assertFalse(any("Old" in t or "old" in t for t in titles), titles)

    def test_new_post_after_bootstrap_is_emitted(self):
        now = parse_iso("2026-10-19T06:30:00Z")
        with tempfile.TemporaryDirectory() as d:
            ctx = Ctx(d, now)
            official.news(ctx)
            ctx.store.flush()
            global LISTING
            saved, LISTING = LISTING, LISTING + '<a href="/news/brand-new"><span>Oct 20, 2026</span><span>Brand new post</span></a>'
            try:
                ctx = Ctx(d, now + timedelta(days=1))
                official.news(ctx)
                self.assertEqual(ctx.store.flush(), 1)
            finally:
                LISTING = saved


if __name__ == "__main__":
    unittest.main()
