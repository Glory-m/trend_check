"""벤치마크 수집 — 바뀐 파일만 받고, 1위가 바뀔 때만 항목을 만든다."""
import io
import json
import tempfile
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path

from collector import benchmarks
from collector.store import Store
from collector.timeutil import parse_iso


def tb_file(model, acc, date="2026-07-09"):
    return {"metadata": {"model_display": {"label": model}, "agent_display": {"label": "Claude Code"}, "date": date,
                         "reasoning_effort": "high"}, "metrics": {"accuracy": acc, "accuracy_stderr": 1.2, "n_trials": 445,
                                                                  "total_cost_usd": 100}}


def epoch_zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        lines = ["Model version,mean_score,Release date,Organization,stderr"] + [f"{m},{s},2026-09-01,Org,0.01" for m, s in rows]
        z.writestr("swe_bench_verified.csv", "\n".join(lines))
    return buf.getvalue()


class R:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def json(self):
        return json.loads(self.body)


class FakeClient:
    def __init__(self, files, zrows):
        self.files, self.zrows, self.calls = files, zrows, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url == benchmarks.TB_LIST:
            return R([{"name": n, "sha": f"sha-{n}-{v['metrics']['accuracy']}", "download_url": f"raw/{n}"} for n, v in self.files.items()])
        if url.startswith("raw/"):
            return R(self.files[url[4:]])
        if url == benchmarks.EPOCH_ZIP:
            return R(epoch_zip(self.zrows))
        raise AssertionError(url)


class Ctx:
    def __init__(self, d, now, client):
        self.now, self.client, self.store = now, client, Store(d, now)


class BenchTest(unittest.TestCase):
    def test_terminal_bench_incremental_and_top_change(self):
        now = parse_iso("2026-10-19T21:17:00Z")
        with tempfile.TemporaryDirectory() as d:
            files = {"a.json": tb_file("Sonnet 5", 74.6), "b.json": tb_file("Opus 4.8", 78.9)}
            ctx = Ctx(d, now, FakeClient(files, []))
            benchmarks.terminal_bench(ctx)
            self.assertEqual(ctx.store.flush(), 0)                      # 첫 실행은 항목 없음
            ctx = Ctx(d, now + timedelta(minutes=5), FakeClient(files, []))
            benchmarks.terminal_bench(ctx)
            self.assertEqual([c for c in ctx.client.calls if c.startswith("raw/")], [])   # 안 바뀐 파일은 다시 받지 않음
            files["c.json"] = tb_file("Opus 5.5", 88.0)
            ctx = Ctx(d, now + timedelta(days=1), FakeClient(files, []))
            benchmarks.terminal_bench(ctx)
            titles = [x["title"] for x in ctx.store.pending]
            self.assertTrue(any("새 기록: Opus 5.5" in t for t in titles))
            self.assertTrue(any("1위 변경: Opus 4.8 → Opus 5.5" in t for t in titles))

    def test_epoch_top_change(self):
        now = parse_iso("2026-10-19T21:17:00Z")
        with tempfile.TemporaryDirectory() as d:
            ctx = Ctx(d, now, FakeClient({}, [("claude-opus-4-7_max", 0.83), ("gpt-5.5_xhigh", 0.81)]))
            benchmarks.epoch(ctx)
            saved = json.loads((Path(d) / "benchmarks" / "epoch.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["sets"][0]["top"][0], {"model": "claude-opus-4-7_max", "org": "Org", "score": 83.0,
                                                          "released": "2026-09-01", "extra": "±1.0"})
            self.assertEqual(ctx.store.pending, [])
            ctx = Ctx(d, now + timedelta(days=1), FakeClient({}, [("claude-opus-4-7_max", 0.83), ("gpt-6_max", 0.9)]))
            benchmarks.epoch(ctx)
            self.assertEqual(len(ctx.store.pending), 1)
            self.assertIn("SWE-bench Verified 1위 변경", ctx.store.pending[0]["title"])


if __name__ == "__main__":
    unittest.main()
