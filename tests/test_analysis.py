"""분류·스타 지표 테스트 — 실제 profile.yml·rules.yml로 판정을 고정한다."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import yaml

from collector import analyze
from collector.classify import Classifier, compile_kw
from collector.store import Store
from collector.timeutil import parse_iso

ROOT = Path(__file__).resolve().parent.parent
RULES = yaml.safe_load((ROOT / "config/rules.yml").read_text(encoding="utf-8"))
PROFILE = yaml.safe_load((ROOT / "profile.yml").read_text(encoding="utf-8"))


def cc(title, t="claude_code_change", **kw):
    return {"type": t, "title": title, "body": None, "source": "changelog", **kw}


class KeywordTest(unittest.TestCase):
    def test_word_boundaries(self):
        self.assertTrue(compile_kw("launch").search("we launched claude"))
        self.assertTrue(compile_kw("hooks").search("pretooluse hooks run"))
        self.assertFalse(compile_kw("test").search("the latest release"))
        self.assertTrue(compile_kw("deprecat*").search("this flag is deprecated"))
        self.assertTrue(compile_kw("cve-").search("fixes cve-2026-1234"))


class ClassifyTest(unittest.TestCase):
    clf = Classifier(RULES, PROFILE)

    def check(self, item, category, importance):
        r = self.clf.classify(item)
        self.assertEqual((r["category"], r["importance"]), (category, importance), (item["title"], r))
        self.assertTrue(r["importance_reason"])
        self.assertEqual(r["classified_by"], "rule")

    def test_claude_code_changes(self):
        self.check(cc("Fixed a crash when resizing the terminal"), "기타", "낮음")
        self.check(cc("Windows: Fixed PowerShell processes left running"), "기타", "보통")       # 내 환경
        self.check(cc("Changed `UserPromptSubmit` hooks to run before a skill expands"), "스킬·플러그인·MCP", "높음")
        self.check(cc("Removed the `--sandbox` flag from `claude remote-control`"), "사용법·워크플로", "높음")
        self.check(cc("Improved the error shown when a worktree cannot be created"), "기타", "보통")   # 소소한 개선
        self.check(cc("Added `--drain` to `claude self-hosted-runner orchestrator` hooks"), "신기술", "낮음")  # 안 쓰는 환경

    def test_security(self):
        self.check(cc("Fixed a prompt injection via MCP tool results"), "보안", "높음")
        self.check({"type": "official_post", "title": "Anthropic 뉴스: Expanding the Cyber security program",
                    "body": None, "source": "anthropic_news"}, "보안", "보통")
        self.check({"type": "candidate_new", "title": "[격리됨] a/b — 의심 문구 감지", "body": None,
                    "source": "search", "quarantined": True}, "보안", "보통")

    def test_official_and_plan(self):
        note = {"type": "official_release_note", "source": "anthropic_release_notes", "body": None}
        self.check({**note, "title": "We've launched Claude Haiku 5.5, our most capable small model"}, "신기술", "높음")
        self.check({**note, "title": "Claude Max and Team plans now include monthly API credits"}, "신기술", "높음")
        self.check({**note, "title": "The Compliance API now returns user preferences for Enterprise"}, "신기술", "낮음")

    def test_off_topic_news(self):
        self.check({"type": "hn_mention", "title": "HN: Anthropic assigned junk credit rating", "body": None,
                    "source": "hn"}, "기타", "낮음")


class StarMetricsTest(unittest.TestCase):
    def test_surge_and_series(self):
        class Ctx:
            pass
        with tempfile.TemporaryDirectory() as d:
            start = parse_iso("2026-10-01T21:17:00Z")
            for day, stars in enumerate([100, 110, 120, 130, 140, 150, 160, 400]):
                ctx = Ctx()
                ctx.now = start + timedelta(days=day)
                ctx.rules = RULES
                ctx.store = Store(d, ctx.now)
                ctx.store.set_snapshot("o/r", {"tier": "candidate", "stars": stars, "forks": 5,
                                               "pushed_at": "2026-10-01T00:00:00Z"})
                analyze.run(ctx)
                ctx.store.flush()
            m = ctx.store.load_json("metrics.json", None)["repos"]["o/r"]
            self.assertEqual((m["d1"], m["d7"]), (240, 300))
            self.assertTrue(m["surge"])
            types = {x["type"] for x in ctx.store.load_json(f"items/{ctx.store.today}.json", {"items": []})["items"]}
            self.assertIn("repo_surge", types)
            self.assertIn("promote_suggest", types)   # 7일 +300, +300%
            s = ctx.store.load_json("series.json", None)
            self.assertEqual(len(s["dates"]), 8)


if __name__ == "__main__":
    unittest.main()
