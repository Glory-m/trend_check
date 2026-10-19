"""SKILL.md 위험 신호 감사 — 추천 전에 '외부 네트워크 호출·자격 증명 접근·셸 실행 지시'가 있는지 규칙으로 검사.

GitHub Actions에서만 실행되며(사용자 PC로 외부 파일을 받지 않음), 원문은 저장하지 않고
'어느 파일에 어떤 신호가 있는지'만 data/audit/skills.json에 남긴다. 수집한 코드는 실행하지 않는다.
"""
import re
import urllib.parse
from datetime import timedelta

from . import safety
from .timeutil import parse_iso

RISK_RULES = {
    "network": re.compile(r"\b(curl|wget|invoke-webrequest|iwr|irm|axios|urllib|http\.client|webfetch|"
                          r"requests\.(get|post|put)|fetch\()", re.I),
    "credentials": re.compile(r"\.ssh[/\\]|\bid_(rsa|ed25519)\b|\bapi[_-]?keys?\b|\baccess[_-]?token\b|\bsecrets?\b|"
                              r"\bpasswords?\b|(^|[\s/\\])\.env\b|credentials|keychain|ANTHROPIC_API_KEY|GITHUB_TOKEN", re.I),
    "shell": re.compile(r"```\s*(bash|sh|shell|zsh|powershell|ps1|cmd)\b|\bBash\(|allowed-tools:[^\n]*\bBash\b|"
                        r"\bsh\s+-c\b|subprocess|os\.system|child_process|\brm\s+-rf\b|\bsudo\b|\bchmod\s+\+x\b|!`", re.I),
}
SCRIPT_EXT = (".sh", ".bash", ".ps1", ".bat", ".cmd", ".py", ".js", ".mjs", ".ts")
SAFE_PATH = re.compile(r"[^A-Za-z0-9._/ -]")


def scan_skill(text):
    flags = [k for k, rx in RISK_RULES.items() if rx.search(text)]
    if safety.must_quarantine(safety.scan(text, "search")):
        flags.append("injection")
    return flags


def audit_repo(ctx, repo, budget):
    tree = ctx.client.get(f"/repos/{repo}/git/trees/HEAD?recursive=1").json()
    paths = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]
    skills = sorted(p for p in paths if p.lower().endswith("skill.md"))
    skill_dirs = {p.rsplit("/", 1)[0] for p in skills if "/" in p}
    rec = {
        "audited_at": ctx.store.now_iso,
        "skill_files": len(skills),
        "script_files": sum(1 for p in paths if p.lower().endswith(SCRIPT_EXT)
                            and any(p.startswith(d + "/") for d in skill_dirs)),
        # 플러그인 hooks 설정은 설치하면 명령이 자동 실행될 수 있어 별도 신호로 남긴다
        "hook_configs": sorted(SAFE_PATH.sub("_", p) for p in paths
                               if re.search(r"(^|/)(hooks/hooks\.json|\.claude/settings(\.local)?\.json)$", p))[:10],
        "mcp_configs": sorted(SAFE_PATH.sub("_", p) for p in paths if re.search(r"(^|/)\.mcp\.json$", p))[:10],
        "flags": {k: [] for k in [*RISK_RULES, "injection"]},
        "tree_truncated": bool(tree.get("truncated")),
        "checked_files": 0,
    }
    for p in skills[:ctx.rules["audit"]["max_files_per_repo"]]:
        if budget[0] <= 0:
            rec["budget_exhausted"] = True
            break
        budget[0] -= 1
        url = f"https://raw.githubusercontent.com/{repo}/HEAD/{urllib.parse.quote(p)}"
        try:
            text = ctx.client.get(url).text()[:200_000]
        except Exception:
            continue
        rec["checked_files"] += 1
        for f in scan_skill(text):
            rec["flags"][f].append(SAFE_PATH.sub("_", p)[:200])
    for k in rec["flags"]:
        rec["flags"][k] = rec["flags"][k][:20]
    return rec


def run(ctx):
    cfg = ctx.rules["audit"]
    store = ctx.store
    data = store.load_json("audit/skills.json", {"repos": {}})
    refresh = timedelta(days=cfg["refresh_days"])
    targets = [e["repo"] for e in ctx.watchlist]
    ranked = sorted(ctx.candidates["repos"].items(), key=lambda kv: kv[1].get("score", 0), reverse=True)
    targets += [n for n, _ in ranked[:cfg["top_candidates"]]]

    def stale(name):
        a = data["repos"].get(name)
        if not a or a.get("error"):
            return True
        snap = store.snapshot["repos"].get(name, {})
        audited = parse_iso(a.get("audited_at"))
        pushed = parse_iso(snap.get("pushed_at"))
        return ctx.now - audited >= refresh or (pushed and pushed > audited)

    todo = [n for n in dict.fromkeys(targets) if stale(n)]
    budget = [cfg["max_raw_fetches_per_run"]]
    done = failed = 0
    for name in todo:
        if budget[0] <= 0:
            break
        try:
            data["repos"][name] = audit_repo(ctx, name, budget)
            done += 1
        except Exception as e:
            data["repos"][name] = {"audited_at": store.now_iso, "error": f"{type(e).__name__}"[:80]}
            failed += 1
    keep = set(targets)
    data["repos"] = {k: v for k, v in sorted(data["repos"].items()) if k in keep}
    data.update({"updated_at": store.now_iso,
                 "note": "규칙 기반 신호일 뿐 — 신호가 없어도 안전이 보장되지 않는다. 원문은 저장하지 않음."})
    store.write_json("audit/skills.json", data)
    return f"targets={len(set(targets))} audited={done} failed={failed} pending={len(todo) - done - failed}"
