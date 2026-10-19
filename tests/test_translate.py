"""무료 기계 번역 — 엔진 없으면 건너뛰고, 코드 표기는 보존하고, 검증 통과분만 저장하며, AI 번역은 덮어쓰지 않는다."""
import json
import os
import sys
import tempfile
import zipfile
import unittest
from pathlib import Path
from unittest import mock

from collector import translate
from collector.store import Store
from collector.timeutil import kst_date, parse_iso

NOW = parse_iso("2026-10-19T21:30:00Z")


class FakeClient:
    def __init__(self, replies):
        self.replies, self.sent, self.headers = replies, [], None

    def post_json(self, url, payload, headers):
        self.sent.append(payload)
        self.headers = headers
        return [{"translations": [{"text": self.replies.get(p["Text"], "번역됨: " + p["Text"]), "to": "ko"}]} for p in payload]


class Ctx:
    def __init__(self, d, client):
        self.now, self.client = NOW, client
        self.rules = {"translate": {"days": 3, "max_items_per_run": 80, "max_chars_per_run": 20000}}
        self.store = Store(d, NOW)


def setup_items(d, items, ko=None):
    day = kst_date(NOW)
    (Path(d) / "items").mkdir(parents=True, exist_ok=True)
    (Path(d) / "items" / f"{day}.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    if ko:
        (Path(d) / "ko").mkdir(exist_ok=True)
        (Path(d) / "ko" / f"{day}.json").write_text(json.dumps({"date": day, "items": ko}), encoding="utf-8")
    return day


def item(i, title, imp="높음", t="claude_code_change"):
    return {"id": i, "type": t, "title": title, "body": None, "importance": imp}


class TranslateTest(unittest.TestCase):
    def test_skips_without_key(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AZURE_TRANSLATOR_KEY", None)
            os.environ.pop("TREND_MT_MODEL_ZIP", None)
            self.assertIn("skipped", translate.run(Ctx(d, FakeClient({}))))

    def test_translates_validates_and_keeps_ai(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"AZURE_TRANSLATOR_KEY": "k", "AZURE_TRANSLATOR_REGION": "koreacentral"}):
            day = setup_items(d, [
                item("a", "Added `--safe-mode` flag to background sessions"),
                item("b", "Fixed a crash", imp="낮음"),                     # 낮음은 대상 아님
                item("c", "Changed hooks to run earlier"),                  # 이미 AI 번역 있음 → 건드리지 않음
                item("e", "Bad output case"),
            ], ko={"c": {"ko": "훅이 더 일찍 실행되도록 변경", "classified_by": "ai"}})
            client = FakeClient({"Bad output case": "see https://evil.example"})
            out = translate.run(Ctx(d, client))
            self.assertIn("translated=1", out)
            self.assertIn("rejected=1", out)
            sent = [p["Text"] for p in client.sent[0]]
            self.assertIn('Added <span class="notranslate">--safe-mode</span> flag to background sessions', sent)  # 코드 표기 보존
            self.assertEqual(len(sent), 2)
            self.assertEqual(client.headers["Ocp-Apim-Subscription-Region"], "koreacentral")
            saved = json.loads((Path(d) / "ko" / f"{day}.json").read_text(encoding="utf-8"))["items"]
            self.assertEqual(saved["a"]["classified_by"], "mt")
            self.assertIn("--safe-mode", saved["a"]["ko"])
            self.assertEqual(saved["c"]["classified_by"], "ai")       # AI 번역 유지
            self.assertNotIn("e", saved)                               # 링크 포함 → 버림

    def test_html_roundtrip(self):
        self.assertEqual(translate.from_html('<span class="notranslate">a &lt;b&gt;</span> 변경'), "a <b> 변경")
        self.assertEqual(translate.to_html("x < y `z`"), 'x &lt; y <span class="notranslate">z</span>')


class FakeArgos:
    name, model = "argos", "argos-en_ko-1.1"
    pinned, sha = True, "x"

    def translate(self, srcs):
        # 코드 표기를 잃은 결과는 None (Argos.translate 와 같은 규칙)
        return [None if "`" in s else "번역: " + s for s in srcs]


def make_zip(path, extra=()):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("translate-en_ko-1_1/model/model.bin", b"bin")
        z.writestr("translate-en_ko-1_1/model/shared_vocabulary.json", b"[]")
        z.writestr("translate-en_ko-1_1/sentencepiece.model", b"spm")
        z.writestr("translate-en_ko-1_1/metadata.json", json.dumps({"package_version": "1.1"}))
        for n in extra:
            z.writestr(n, b"evil")


class ArgosTest(unittest.TestCase):
    def test_engine_run_rejects_lost_code(self):
        with tempfile.TemporaryDirectory() as d:
            day = setup_items(d, [item("a", "Added `--x` flag"), item("b", "Changed hooks")])
            out = translate.run(Ctx(d, FakeClient({})), engine=FakeArgos())
            self.assertIn("engine=argos translated=1 rejected=1", out)
            saved = json.loads((Path(d) / "ko" / f"{day}.json").read_text(encoding="utf-8"))["items"]
            self.assertEqual(saved["b"]["model"], "argos-en_ko-1.1")
            self.assertEqual(saved["b"]["classified_by"], "mt")

    def test_extract_only_needed_files(self):
        with tempfile.TemporaryDirectory() as d:
            zp = os.path.join(d, "m.zip")
            make_zip(zp, extra=["../evil.txt", "translate-en_ko-1_1/model/../../evil2", "translate-en_ko-1_1/model/sub/x"])
            out = os.path.join(d, "out")
            os.makedirs(out)
            mdir, spm, meta = translate.extract_model(zp, out)
            self.assertEqual(sorted(os.listdir(mdir)), ["model.bin", "shared_vocabulary.json"])
            self.assertEqual(sorted(os.listdir(out)), ["model", "sentencepiece.model"])
            self.assertFalse(os.path.exists(os.path.join(d, "evil.txt")))
            self.assertEqual(meta["package_version"], "1.1")

    def test_hash_mismatch_stops(self):
        with tempfile.TemporaryDirectory() as d:
            zp = os.path.join(d, "m.zip")
            make_zip(zp)
            with self.assertRaises(ValueError):
                translate.Argos(zp, "0" * 64)

    def test_missing_libs_skip(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(sys.modules, {"ctranslate2": None}):
            zp = os.path.join(d, "m.zip")
            make_zip(zp)
            with mock.patch.dict(os.environ, {"TREND_MT_MODEL_ZIP": zp}):
                os.environ.pop("AZURE_TRANSLATOR_KEY", None)
                self.assertIn("미설치", translate.run(Ctx(d, FakeClient({}))))


if __name__ == "__main__":
    unittest.main()
