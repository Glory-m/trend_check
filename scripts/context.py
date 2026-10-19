"""추천·세팅 설계용 맥락 — /recommend, /design-my-setup이 읽는 압축 요약.

사용: python scripts/context.py [--days 14] [--candidates 15]
출력: 핵심 watchlist 지표, 별 속도·증가 상위 후보, 최근 N일 스킬·워크플로 관련 '높음/보통' 항목,
      SKILL.md 위험 신호 감사 결과(data/audit/skills.json, 있으면). profile.yml은 Claude가 직접 읽는다(짧음).
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def audit_line(a):
    if not a:
        return "SKILL.md 감사: 데이터 없음"
    if a.get("error"):
        return f"SKILL.md 감사 실패({a['error']})"
    f = a.get("flags", {})
    risky = [f"{k} {len(v)}개 파일" for k, v in f.items() if v]
    base = f"SKILL.md {a.get('skill_files', 0)}개, 실행 스크립트 {a.get('script_files', 0)}개"
    return base + (" · ⚠️ " + ", ".join(risky) if risky else " · 위험 신호 없음") + f" (감사 {str(a.get('audited_at', ''))[:10]})"


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--candidates", type=int, default=15)
    args = ap.parse_args()
    index = load(DATA / "index.json", {})
    metrics = load(DATA / "metrics.json", {"repos": {}, "history_days": 0})
    cands = load(DATA / "candidates.json", {"repos": {}})["repos"]
    audit = load(DATA / "audit" / "skills.json", {"repos": {}}).get("repos", {})
    read = ["data/index.json", "data/metrics.json", "data/candidates.json", "data/audit/skills.json"]
    repos = metrics.get("repos", {})
    print(f"마지막 수집(UTC): {index.get('last_collected_at', '?')} · 스타 이력 {metrics.get('history_days', 0)}일"
          f" (7일·30일 지표는 이력이 쌓인 만큼만)")

    def fmt(name, m):
        parts = [f"★{m.get('stars', 0):,}"]
        for k, label in (("d1", "1일"), ("d7", "7일"), ("d30", "30일")):
            if m.get(k) is not None:
                parts.append(f"{label} +{m[k]}")
        if m.get("warnings"):
            parts.append("⚠️참고경고: " + "; ".join(m["warnings"]))
        return f"{name} ({', '.join(parts)})"

    print("\n## 핵심 watchlist")
    for name, m in sorted(((n, m) for n, m in repos.items() if m.get("tier") == "core"), key=lambda nm: -nm[1]["stars"]):
        print(f"- {fmt(name, m)}\n  {audit_line(audit.get(name))}")

    print(f"\n## 후보 상위 {args.candidates} (별 속도 = 별/나이, 오늘 트렌딩 우선)")
    ranked = sorted(cands.items(), key=lambda kv: (kv[1].get("trending_today", False), kv[1].get("score", 0)), reverse=True)
    for name, c in ranked[:args.candidates]:
        m = repos.get(name, {"stars": c.get("stars") or 0})
        desc = c.get("description") or ""
        print(f"- {fmt(name, m)} · 하루 ★{c.get('score')} · 생성 {str(c.get('created_at', ''))[:10]} · "
              f"출처 {', '.join(c.get('sources', [])[:2])}\n  {desc[:160]}\n  {audit_line(audit.get(name))}")

    since = (date.today() - timedelta(days=args.days)).isoformat()
    picked = []
    for d in sorted(index.get("item_dates", {}), reverse=True):
        if d < since:
            continue
        read.append(f"data/items/{d}.json")
        for x in load(DATA / "items" / f"{d}.json", {"items": []})["items"]:
            if x.get("category") in ("스킬·플러그인·MCP", "사용법·워크플로", "신기술") and x.get("importance") in ("높음", "보통") \
                    and not x.get("quarantined") and x.get("type") != "claude_code_change":
                picked.append((d, x))
    print(f"\n## 최근 {args.days}일 생태계·사용법 항목 (Claude Code 변경 제외, {len(picked)}건 중 30)")
    for d, x in picked[:30]:
        print(f"- [{x['category']}·{x['importance']}] {x['title'][:160]} — {d}")
    print("\n읽은 파일: " + ", ".join(dict.fromkeys(read)))


if __name__ == "__main__":
    main()
