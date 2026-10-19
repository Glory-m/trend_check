"""실행: python -m collector [--data-dir data] [--only step1,step2] [--now 2026-10-19T00:00:00Z]

필수 단계(claude_code, watchlist)가 실패하면 종료 코드 1. 선택 단계는 실패해도 계속 진행(fail-soft).
어떤 경우든 data/health.json에 결과를 남긴다.
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

import yaml

from . import analyze, audit, classify, claude_code, discovery, official, repos
from .net import Client
from .store import Store
from .timeutil import now_utc, parse_iso

ROOT = Path(__file__).resolve().parent.parent

# (이름, 함수, 필수 여부)
STEPS = [
    ("claude_code", claude_code.collect, True),
    ("watchlist", repos.collect_core, True),
    ("search", discovery.search, False),
    ("trending", discovery.trending, False),
    ("hn", discovery.hn, False),
    ("official_platform_notes", official.platform_notes, False),
    ("official_apps_notes", official.apps_notes, False),
    ("official_news", official.news, False),
    ("official_engineering", official.engineering, False),
    ("official_org_repos", official.org_repos, False),
    ("candidates", repos.finalize_candidates, False),
    ("analyze", analyze.run, False),
    ("audit", audit.run, False),
]


class Context:
    def __init__(self, data_dir, now):
        self.now = now
        self.store = Store(data_dir, now)
        self.client = Client.from_env()
        self.rules = yaml.safe_load((ROOT / "config/rules.yml").read_text(encoding="utf-8"))
        self.watchlist = yaml.safe_load((ROOT / "watchlist.yml").read_text(encoding="utf-8"))["repos"]
        self.profile = yaml.safe_load((ROOT / "profile.yml").read_text(encoding="utf-8"))
        cands = self.store.load_json("candidates.json", None)
        self.candidates_bootstrap = cands is None
        self.candidates = cands or {"repos": {}}
        self.found = {}   # 오늘 search·trending에서 발견한 레포 → finalize_candidates가 반영
        self.warnings = []

    def warn(self, step, msg):
        self.warnings.append({"at": self.store.now_iso, "step": step, "message": str(msg)[:500]})
        print(f"  ! [{step}] {msg}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="collector")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--only", help="쉼표로 구분한 단계만 실행")
    ap.add_argument("--now", help="테스트용 현재 시각 (ISO 8601 UTC)")
    args = ap.parse_args(argv)

    now = parse_iso(args.now) if args.now else now_utc()
    ctx = Context(args.data_dir, now)
    only = set(args.only.split(",")) if args.only else None

    try:
        ctx.client.rate_limit()
    except Exception as e:
        ctx.warn("rate_limit", e)
    print(f"collector start {ctx.store.now_iso} auth={ctx.client.authenticated} rate={ctx.client.rate}")

    steps, required_failed = {}, False
    for name, fn, required in STEPS:
        if only and name not in only:
            continue
        t = time.time()
        try:
            detail = fn(ctx)
            steps[name] = {"status": "ok", "detail": detail}
            print(f"  ✓ {name}: {detail}")
        except Exception as e:
            steps[name] = {"status": "fail", "detail": f"{type(e).__name__}: {e}"[:500]}
            ctx.warn(name, f"{type(e).__name__}: {e}")
            traceback.print_exc(file=sys.stderr)
            required_failed |= required
        steps[name]["seconds"] = round(time.time() - t, 1)

    added = ctx.store.flush()

    # 분류는 저장 후 최근 N일 파일 전체에 적용 — 새 항목과 규칙 변경을 같은 경로로 처리
    t = time.time()
    try:
        steps["classify"] = {"status": "ok", "detail": classify.reclassify_recent(ctx)}
        print(f"  ✓ classify: {steps['classify']['detail']}")
    except Exception as e:
        steps["classify"] = {"status": "fail", "detail": f"{type(e).__name__}: {e}"[:500]}
        ctx.warn("classify", f"{type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stderr)
    steps["classify"]["seconds"] = round(time.time() - t, 1)

    health = ctx.store.load_json("health.json", {"errors": []})
    statuses = {s["status"] for s in steps.values()}
    status = "fail" if required_failed else ("partial" if "fail" in statuses else "ok")
    health.update({
        "last_run_at": ctx.store.now_iso,
        "status": status,
        "steps": steps,
        "new_items": added,
        "authenticated": ctx.client.authenticated,
        "rate_limit": ctx.client.rate,
        "http_calls": ctx.client.calls,
        "warnings": ctx.warnings,
    })
    if status != "fail":
        health["last_success_at"] = ctx.store.now_iso
    health["errors"] = (health.get("errors", []) + [w for w in ctx.warnings])[-30:]
    ctx.store.write_json("health.json", health)
    print(f"collector done status={status} new_items={added} http_calls={ctx.client.calls}")
    return 1 if required_failed else 0


if __name__ == "__main__":
    sys.exit(main())
