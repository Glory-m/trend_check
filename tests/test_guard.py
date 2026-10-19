"""커밋 전 검사 테스트 — 가짜 비밀값은 실행 중에만 조립해서 이 파일 자체가 검사에 걸리지 않게 한다."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import guard  # noqa: E402


class GuardTest(unittest.TestCase):
    def run_check(self, name, content):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            with mock.patch.object(guard, "ROOT", Path(d)):
                return guard.check([name])

    def test_secrets_detected(self):
        fake = "sk-" + "ant-" + "a" * 30
        self.assertTrue(self.run_check("a.py", f"key = '{fake}'"))
        self.assertTrue(self.run_check("b.yml", "env:\n  KEY: ${{ secrets." + "ANTHROPIC_API_KEY }}"))
        self.assertTrue(self.run_check("c.json", '{"t": "gh' + 'p_' + "x" * 36 + '"}'))
        self.assertTrue(self.run_check("d.md", "-----BEGIN " + "OPENSSH PRIVATE KEY-----"))

    def test_hidden_and_forbidden(self):
        self.assertTrue(self.run_check("e.py", "x = 1  # " + chr(0x202E)))
        self.assertTrue(self.run_check(".env", "A=1"))
        self.assertTrue(self.run_check(".claude/settings.local.json", "{}"))

    def test_private_terms_from_local_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "guard.local.txt").write_text("# comment
acme-corp
", encoding="utf-8")
            Path(d, "x.md").write_text("hello
works at ACME-CORP
", encoding="utf-8")
            with mock.patch.object(guard, "ROOT", Path(d)):
                problems = guard.check(["x.md", "company.crt"])
        self.assertEqual(len(problems), 2)
        self.assertIn("x.md:2", problems[0])

    def test_clean_passes(self):
        self.assertEqual(self.run_check("ok.py", "print('hello')  # ANTHROPIC_API_KEY는 쓰지 않는다"), [])
        self.assertEqual(self.run_check("ok.md", "emoji 👨" + chr(0x200D) + "💻"), [])


if __name__ == "__main__":
    unittest.main()
