"""주제 검색 — 수집된 데이터에서 키워드 관련 항목만 모아 압축 출력 (/explore용).

사용: python scripts/explore.py playwright "browser test" e2e 브라우저 [--days 90] [--limit 40]
- 키워드는 OR 매칭(대소문자 무시). 한글 주제는 Claude가 영문 동의어로 넓혀서 넘긴다.
- 찾는 곳: 최근 N일 items, Claude Code 전체 CHANGELOG 이력, 핵심·후보 레포 설명.
- 스크립트가 파일을 읽고 일치한 것만 출력하므로 Claude는 data/를 직접 읽지 않는다.
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector import safety  # noqa: E402

DATA = ROOT / "data"
ORDER = {"높음": 0, "보통": 1, "낮음": 2}


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="+")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    rx = re.compile("|".join(re.escape(k.lower()) for k in args.keywords), re.I)
    index = load(DATA / "index.json", {})
    read = ["data/index.json"]
    last = index.get("last_collected_at", "?")
    print(f"주제 검색: {' | '.join(args.keywords)} · items 최근 {args.days}일 + CHANGELOG 전체 + 레포 설명")
    print(f"마지막 수집(UTC): {last}")

    since = (date.today() - timedelta(days=args.days)).isoformat()
    hits = []
    for d in sorted(index.get("item_dates", {}), reverse=True):
        if d < since:
            continue
        day = load(DATA / "items" / f"{d}.json", {"items": []})
        read.append(f"data/items/{d}.json")
        for x in day["items"]:
            text = f"{x.get('title') or ''} {x.get('body') or ''}"
            if rx.search(text) and not x.get("quarantined"):
                if safety.must_quarantine(safety.scan(text, x.get("source"))):
                    continue
                hits.append((d, x))
    hits.sort(key=lambda dx: (ORDER.get(dx[1].get("importance"), 3), dx[0]), reverse=False)
    print(f"\n## 수집 항목 ({len(hits)}건, 상위 {min(len(hits), args.limit)})")
    for d, x in hits[:args.limit]:
        print(f"- [{x.get('category')}·{x.get('importance')}] {x.get('title')} — 수집 {d}"
              + (f" · {x['url']}" if x.get("url") else ""))

    cl = load(DATA / "claude_code" / "changelog.json", {"versions": []})
    read.append("data/claude_code/changelog.json")
    cl_hits = [(v["version"], (v.get("published_at") or "")[:10], b)
               for v in cl["versions"] for b in v["bullets"] if b and rx.search(b)]
    print(f"\n## Claude Code CHANGELOG 이력 ({len(cl_hits)}건, 최신 {min(len(cl_hits), 15)})")
    for ver, pub, b in cl_hits[:15]:
        print(f"- {ver} ({pub}): {b[:220]}")

    metrics = load(DATA / "metrics.json", {"repos": {}})["repos"]
    cands = load(DATA / "candidates.json", {"repos": {}})["repos"]
    snap_dates = index.get("snapshot_dates", [])
    snap = load(DATA / "snapshots" / f"{snap_dates[-1]}.json", {"repos": {}})["repos"] if snap_dates else {}
    read += ["data/metrics.json", "data/candidates.json"] + ([f"data/snapshots/{snap_dates[-1]}.json"] if snap_dates else [])
    repos = []
    for name in set(snap) | set(cands):
        desc = (snap.get(name) or {}).get("description") or (cands.get(name) or {}).get("description") or ""
        if rx.search(f"{name} {desc}") and not desc.startswith("[격리됨"):
            m = metrics.get(name, {})
            repos.append((m.get("stars") or (cands.get(name) or {}).get("stars") or 0, name, desc, m))
    repos.sort(reverse=True)
    print(f"\n## 관련 레포 ({len(repos)}개, 별 순 상위 {min(len(repos), 15)})")
    for stars, name, desc, m in repos[:15]:
        tier = "핵심" if m.get("tier") == "core" else "후보"
        extra = f", 7일 +{m['d7']}" if m.get("d7") is not None else ""
        warn = " ⚠️참고경고" if m.get("warnings") else ""
        print(f"- [{tier}] {name} ★{stars:,}{extra}{warn} — {desc[:150]}")

    if not hits and not cl_hits and not repos:
        print("\n데이터에 없음 — 이 키워드와 일치하는 수집 데이터가 없다.")
    print("\n읽은 파일: " + ", ".join(dict.fromkeys(read)))


if __name__ == "__main__":
    main()
