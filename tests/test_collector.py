"""오프라인 테스트: python -m unittest discover -s tests"""
import tempfile
import unittest
from datetime import timedelta

from collector.claude_code import item_id, parse_changelog
from collector.discovery import build_queries
from collector.store import Store
from collector.timeutil import kst_date, parse_iso

CHANGELOG = """# Changelog

## 2.1.303

- Bug fixes and reliability improvements

## 2.1.302

- Added `FOO` env var
  continued line
- Fixed a crash
  - sub detail

## Unreleased notes
- should be ignored
"""


class ChangelogTest(unittest.TestCase):
    def test_parse(self):
        v = parse_changelog(CHANGELOG)
        self.assertEqual(list(v), ["2.1.303", "2.1.302"])
        self.assertEqual(v["2.1.303"], ["Bug fixes and reliability improvements"])
        self.assertEqual(v["2.1.302"], ["Added `FOO` env var continued line", "Fixed a crash / sub detail"])

    def test_item_id_stable_and_whitespace_insensitive(self):
        self.assertEqual(item_id("1.0.0", "Fixed  a crash"), item_id("1.0.0", "fixed a crash "))
        self.assertNotEqual(item_id("1.0.0", "x"), item_id("1.0.1", "x"))


class StoreTest(unittest.TestCase):
    def test_idempotent_same_day(self):
        now = parse_iso("2026-10-19T21:17:00Z")   # KST 2026-10-20 06:17
        with tempfile.TemporaryDirectory() as d:
            for run in range(2):
                s = Store(d, now + timedelta(minutes=run))
                s.add_item({"id": "a", "type": "t", "title": "A"})
                s.add_item({"id": "a", "type": "t", "title": "A"})   # 같은 실행 안 중복
                s.set_snapshot("o/r", {"stars": 10 + run})
                added = s.flush()
                self.assertEqual(added, 1 if run == 0 else 0)
            s = Store(d, now)
            day = s.load_json("items/2026-10-20.json", None)
            self.assertEqual(len(day["items"]), 1)
            self.assertEqual(day["items"][0]["collected_at"], "2026-10-19T21:17:00Z")  # 첫 수집 시각 유지
            snap = s.load_json("snapshots/2026-10-20.json", None)
            self.assertEqual(snap["repos"]["o/r"]["stars"], 11)                     # 같은 날은 최신 값으로 덮어씀
            self.assertEqual(s.index["snapshot_dates"], ["2026-10-20"])
            self.assertEqual(s.index["item_dates"], {"2026-10-20": 1})

    def test_kst_day_boundary(self):
        self.assertEqual(kst_date(parse_iso("2026-10-19T14:59:59Z")), "2026-10-19")
        self.assertEqual(kst_date(parse_iso("2026-10-19T15:00:00Z")), "2026-10-20")


class QueryTest(unittest.TestCase):
    def test_build_queries(self):
        cfg = {"topics": ["claude-code"], "keywords": ["claude code"],
               "conditions": [{"name": "new", "q": "created:>={days_ago:30} stars:>=20"}]}
        qs = build_queries(cfg, parse_iso("2026-10-19T00:00:00Z"))
        self.assertEqual(qs[0], ("topic:claude-code/new", "topic:claude-code created:>=2026-09-19 stars:>=20"))
        self.assertEqual(qs[1][1], '"claude code" in:name,description created:>=2026-09-19 stars:>=20')


if __name__ == "__main__":
    unittest.main()
