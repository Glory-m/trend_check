"""window.py — 기간 해석·last_seen·구간 밖 파일 미열람 (완료 기준 검증)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "window.py"


def item(i, collected, importance="높음"):
    return {"id": f"x{i}", "type": "claude_code_change", "title": f"Added feature {i}", "body": None,
            "source": "changelog", "collected_at": collected, "category": "신기술",
            "importance": importance, "importance_reason": "테스트", "url": None, "repo": None, "published_at": None}


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.data, self.state = d / "data", d / "state" / "last_seen.json"
        (self.data / "items").mkdir(parents=True)
        days = {
            "2026-10-12": [item(1, "2026-10-12T01:00:00Z")],                    # 지난주 월요일 (KST)
            "2026-10-19": [item(2, "2026-10-18T21:17:00Z"), item(3, "2026-10-19T03:00:00Z", "보통")],
        }
        for day, items in days.items():
            (self.data / "items" / f"{day}.json").write_text(json.dumps({"date": day, "items": items}), encoding="utf-8")
        (self.data / "index.json").write_text(json.dumps({
            "item_dates": {k: len(v) for k, v in days.items()}, "last_collected_at": "2026-10-19T03:00:00Z"}),
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_w(self, *args, now="2026-10-19T06:00:00Z"):   # 2026-10-19 (월) 15:00 KST
        r = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.data), "--state", str(self.state),
                            "--now", now, *args], capture_output=True, text=True, encoding="utf-8", check=True)
        return r.stdout

    def test_today_window_and_files(self):
        out = self.run_w("--today")
        self.assertIn("기준 구간: 2026-10-19 00:00 ~ 2026-10-19 15:00 (KST)", out)
        self.assertIn("항목 2건", out)   # 10/19 06:17 KST, 12:00 KST — 10/12 항목은 제외
        self.assertNotIn("items/2026-10-12", out.split("읽은 파일:")[1])

    def test_week_window(self):
        out = self.run_w("--week")
        self.assertIn("기준 구간: 2026-10-19 00:00 ~ 2026-10-19 15:00 (KST) — 이번 주", out)
        self.assertIn("지난주 같은 구간 비교", out)

    def test_days_window(self):
        out = self.run_w("--days", "3")
        self.assertIn("기준 구간: 2026-10-16 15:00 ~ 2026-10-19 15:00 (KST)", out)

    def test_brief_twice_second_is_empty(self):
        first = self.run_w()                                  # 기록 없음 → 최근 7일
        self.assertIn("첫 브리핑", first)
        self.assertIn("항목 2건", first)                          # 최근 7일: 10/12 01:00Z는 7일 밖
        end = [l for l in first.splitlines() if l.startswith("구간 끝")][0].split(": ")[1]
        self.run_w("--mark-seen", end)
        second = self.run_w(now="2026-10-19T06:05:00Z")
        self.assertIn("기준 구간: 2026-10-19 15:00 ~ 2026-10-19 15:05 (KST) — 마지막 확인 이후", second)
        self.assertIn("새 항목 없음", second)
        files = second.split("읽은 파일:")[1]
        self.assertIn("data/items/2026-10-19.json", files)       # 구간 날짜의 파일만 열고
        self.assertNotIn("data/items/2026-10-12.json", files)    # 구간 밖 파일은 열지 않는다

    def test_stale_warning(self):
        out = self.run_w("--today", now="2026-10-20T06:00:00Z")
        self.assertIn("데이터 최신성 경고", out)


if __name__ == "__main__":
    unittest.main()
