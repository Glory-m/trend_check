"""로컬 비서 서버 보안 — 실제 claude는 부르지 않는다 (잘못된 요청은 그 전에 막혀야 함)."""
import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import serve  # noqa: E402


class ServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        cls.srv.claude_version = None
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r.getheader("Content-Type"), data

    def good(self):
        return {"Origin": f"http://127.0.0.1:{self.port}", "X-TW-Token": serve.TOKEN, "Content-Type": "application/json"}

    def test_status_and_static(self):
        st, _, data = self.req("GET", "/api/status")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(data)["token"], serve.TOKEN)
        st, ctype, _ = self.req("GET", "/site/app.js")
        self.assertEqual((st, ctype), (200, "text/javascript; charset=utf-8"))   # Windows text/plain 문제 방지

    def test_blocks_files_outside_site(self):
        for p in ["/.git/config", "/profile.yml", "/state/last_seen.json", "/scripts/serve.py", "/site/../.git/config",
                  "/%2e%2e/%2e%2e/Windows/win.ini", "/guard.local.txt"]:
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_rejects_bad_host(self):   # DNS 리바인딩
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.example"})[0], 403)

    def test_post_requires_token_and_origin(self):
        body = {"message": "hi"}
        self.assertEqual(self.req("POST", "/api/ask", body, {"Origin": f"http://127.0.0.1:{self.port}"})[0], 403)
        self.assertEqual(self.req("POST", "/api/ask", body, {**self.good(), "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/ask", body, {**self.good(), "X-TW-Token": "wrong"})[0], 403)

    def test_validates_input_before_calling_claude(self):
        self.assertEqual(self.req("POST", "/api/ask", {"message": ""}, self.good())[0], 400)
        self.assertEqual(self.req("POST", "/api/ask", {"message": "x" * 5000}, self.good())[0], 400)


if __name__ == "__main__":
    unittest.main()
