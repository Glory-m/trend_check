"""HTTP 클라이언트 — rate limit 추적, 재시도, 지수 backoff.

토큰은 환경변수 GITHUB_TOKEN에서만 읽는다 (Actions 기본 토큰). 파일에 저장하지 않는다.
TREND_RELAX_X509_STRICT=1 은 SSL 검사 프록시가 있는 로컬 환경 전용 옵트인으로,
인증서 체인 검증은 유지한 채 Python 3.13의 RFC 5280 엄격 플래그만 해제한다.
"""
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
USER_AGENT = "trend-watch (+https://github.com/Glory-m/trend_check)"
RETRY_STATUS = {500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, status, url, detail=""):
        super().__init__(f"HTTP {status} {url} {detail}".strip())
        self.status = status


class RateLimited(Exception):
    pass


class Response:
    def __init__(self, status, body, headers):
        self.status = status
        self.body = body
        self.headers = headers

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def text(self):
        return self.body.decode("utf-8", "replace")


class Client:
    def __init__(self, token=None, relax_x509=False, max_retries=4, sleep=time.sleep):
        self.token = token
        self.max_retries = max_retries
        self.sleep = sleep
        self.ctx = ssl.create_default_context()
        if relax_x509:
            self.ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        self.rate = {}   # resource -> {"remaining": int, "reset": int}
        self.calls = 0

    @classmethod
    def from_env(cls):
        return cls(
            token=os.environ.get("GITHUB_TOKEN") or None,
            relax_x509=os.environ.get("TREND_RELAX_X509_STRICT") == "1",
        )

    @property
    def authenticated(self):
        return bool(self.token)

    def get(self, url, accept=None, ok404=False):
        if url.startswith("/"):
            url = API + url
        headers = {"User-Agent": USER_AGENT}
        if url.startswith(API):
            headers["Accept"] = accept or "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
        elif accept:
            headers["Accept"] = accept

        last = None
        for attempt in range(self.max_retries):
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60, context=self.ctx) as r:
                    body = r.read()
                    self._track(r.headers)
                    return Response(r.status, body, r.headers)
            except urllib.error.HTTPError as e:
                body = e.read()
                self._track(e.headers)
                if e.code == 404 and ok404:
                    return Response(404, body, e.headers)
                wait = self._retry_wait(e.code, e.headers, body, attempt)
                if wait is None:
                    raise HttpError(e.code, url, body[:200].decode("utf-8", "replace")) from None
                last = HttpError(e.code, url)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                wait = self._backoff(attempt)
                last = e
            if attempt < self.max_retries - 1:
                self.sleep(wait)
        raise last

    def rate_limit(self):
        """GET /rate_limit — 이 호출은 한도를 소모하지 않는다."""
        d = self.get("/rate_limit").json()["resources"]
        for name in ("core", "search", "graphql"):
            if name in d:
                self.rate[name] = {"remaining": d[name]["remaining"], "reset": d[name]["reset"],
                                   "limit": d[name]["limit"]}
        return self.rate

    def remaining(self, resource="core"):
        return self.rate.get(resource, {}).get("remaining")

    def _track(self, headers):
        if headers is None:
            return
        res = headers.get("x-ratelimit-resource")
        rem = headers.get("x-ratelimit-remaining")
        if res and rem is not None:
            self.rate.setdefault(res, {})
            self.rate[res]["remaining"] = int(rem)
            if headers.get("x-ratelimit-reset"):
                self.rate[res]["reset"] = int(headers["x-ratelimit-reset"])

    def _retry_wait(self, status, headers, body, attempt):
        if status in (403, 429):
            if headers.get("x-ratelimit-remaining") == "0":
                wait = int(headers.get("x-ratelimit-reset", "0")) - time.time() + 1
                if wait > 90:
                    raise RateLimited(f"rate limit 소진 — {int(wait)}초 후 초기화") from None
                return max(wait, 1)
            if headers.get("retry-after"):
                return min(int(headers["retry-after"]), 90)
            if b"secondary rate limit" in body.lower():
                return 30 + self._backoff(attempt)
            return None
        if status in RETRY_STATUS:
            return self._backoff(attempt)
        return None

    @staticmethod
    def _backoff(attempt):
        return min(30, 1.5 * 2 ** attempt) + random.uniform(0, 1)
