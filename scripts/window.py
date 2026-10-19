"""기간 해석 + 필요한 데이터 파일만 읽어 압축 출력 — /brief·/weekly 등 스킬이 data/를 직접 훑지 않게 한다.

사용:
  python scripts/window.py                  # 기간 언급 없음 → state/last_seen.json 이후 전부
  python scripts/window.py --today          # 오늘 00:00 KST ~ 지금
  python scripts/window.py --week           # 이번 주 월요일 00:00 KST ~ 지금 (+ 지난주 같은 구간 비교)
  python scripts/window.py --days 3         # 지금으로부터 3×24시간
  python scripts/window.py --mark-seen 2026-10-19T07:10:00Z   # 브리핑을 보여준 뒤 last_seen 갱신

규칙:
- '새로움'의 기준은 collected_at(UTC 저장). 표시는 KST.
- 구간에 해당하는 KST 날짜의 items 파일만 연다 (읽은 파일 목록을 출력에 남긴다).
- AI에게 넘기기 직전에 collector/safety.py로 외부 텍스트를 한 번 더 검사한다 (이중 검사).
"""
import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collector import safety  # noqa: E402
from collector.timeutil import KST, fmt_kst, iso, now_utc, parse_iso  # noqa: E402

DATA = ROOT / "data"
STATE = ROOT / "state" / "last_seen.json"
LEVELS = ["높음", "보통", "낮음"]
FIRST_BRIEF_DAYS = 7
STALE_HOURS = 24


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def kst_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=KST).astimezone(timezone.utc)


def resolve_window(args, now):
    """(start, end, 설명). 모두 UTC datetime."""
    today_kst = now.astimezone(KST).date()
    if args.today:
        return kst_midnight(today_kst), now, "오늘"
    if args.week:
        monday = today_kst - timedelta(days=today_kst.weekday())
        return kst_midnight(monday), now, "이번 주"
    if args.days:
        return now - timedelta(hours=24 * args.days), now, f"최근 {args.days}일"
    state = load(STATE, {})
    last = parse_iso(state.get("last_seen_at"))
    if last:
        return last, now, "마지막 확인 이후"
    return now - timedelta(days=FIRST_BRIEF_DAYS), now, f"첫 브리핑 — 기록이 없어 최근 {FIRST_BRIEF_DAYS}일"


def kst_dates(start, end):
    d, last = start.astimezone(KST).date(), end.astimezone(KST).date()
    out = []
    while d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def items_in(start, end, index, read_files):
    """구간 KST 날짜의 items 파일만 열어 collected_at이 [start, end)인 항목."""
    out = []
    for d in kst_dates(start, end):
        if d not in index.get("item_dates", {}):
            continue
        rel = f"data/items/{d}.json"
        day = load(DATA / "items" / f"{d}.json", {"items": []})
        read_files.append(rel)
        for x in day["items"]:
            c = parse_iso(x.get("collected_at"))
            if c and start <= c < end:
                out.append(x)
    return out


def recheck(item):
    """로컬 2차 인젝션 검사 — 걸리면 AI가 원문을 보지 않게 격리."""
    if item.get("quarantined"):
        return item, False
    text = f"{item.get('title') or ''}\n{item.get('body') or ''}"
    flags = safety.scan(text, item.get("source"))
    if safety.must_quarantine(flags):
        item = dict(item, title=f"[격리됨·로컬 2차 검사] {item.get('repo') or item.get('source')} — {', '.join(flags)}",
                    body=None, quarantined=True, category="보안", importance="보통",
                    importance_reason="로컬 2차 검사에서 의심 문구 감지 — 원문 직접 확인 전 사용 금지")
        return item, True
    return item, False


def line(x, with_reason=True):
    pub = (x.get("published_at") or "")[:10]
    parts = [f"[{x.get('category') or '미분류'}] {x.get('title')}"]
    if x.get("repo") and x["repo"] not in (x.get("title") or ""):
        parts.append(f"({x['repo']})")
    s = " ".join(parts)
    meta = []
    if with_reason and x.get("importance_reason"):
        meta.append(f"근거: {x['importance_reason']}")
    if pub:
        meta.append(f"발표 {pub}")
    if x.get("url"):
        meta.append(x["url"])
    return f"- {s}" + (f"  \n  {' · '.join(meta)}" if meta else "")


def summarize_counts(items):
    lv = Counter(x.get("importance") or "미분류" for x in items)
    return " · ".join(f"{k} {lv[k]}" for k in LEVELS + ["미분류"] if lv.get(k))


def main():
    global STATE, DATA
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--today", action="store_true")
    g.add_argument("--week", action="store_true")
    g.add_argument("--days", type=int)
    g.add_argument("--mark-seen", metavar="END_ISO", help="브리핑 구간의 끝 시각으로 last_seen 갱신")
    ap.add_argument("--medium", type=int, default=12, help="'보통' 항목을 몇 개까지 나열할지")
    ap.add_argument("--now", help="테스트용 현재 시각 (ISO UTC)")
    ap.add_argument("--state", help="테스트용 last_seen 파일 경로", default=str(STATE))
    ap.add_argument("--data", help="테스트용 data 폴더 경로", default=str(DATA))
    args = ap.parse_args()
    STATE, DATA = Path(args.state), Path(args.data)

    if args.mark_seen:
        end = parse_iso(args.mark_seen)
        state = load(STATE, {})
        hist = (state.get("history") or [])[-19:] + [state["last_seen_at"]] if state.get("last_seen_at") else []
        STATE.parent.mkdir(exist_ok=True)
        with open(STATE, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"last_seen_at": iso(end), "last_seen_kst": fmt_kst(end), "history": hist},
                      f, ensure_ascii=False, indent=1)
            f.write("\n")
        print(f"last_seen 갱신: {fmt_kst(end)} KST")
        return 0

    now = parse_iso(args.now) if args.now else now_utc()
    start, end, label = resolve_window(args, now)
    index = load(DATA / "index.json", {})
    health = load(DATA / "health.json", {})
    read = ["data/index.json", "data/health.json"]

    print(f"기준 구간: {fmt_kst(start)} ~ {fmt_kst(end)} (KST) — {label}")
    print(f"구간 끝(UTC, --mark-seen에 사용): {iso(end)}")
    last = parse_iso(index.get("last_collected_at"))
    if not last:
        print("⚠️ 수집 데이터 없음 — data/index.json이 없습니다. `git pull` 후 다시 실행하세요.")
        return 0
    age_h = (now - last).total_seconds() / 3600
    if age_h >= STALE_HOURS:
        print(f"⚠️ 데이터 최신성 경고: 마지막 수집 {fmt_kst(last)} KST ({age_h:.0f}시간 전). "
              f"`git pull` 하거나 GitHub Actions에서 collect를 수동 실행하세요.")
    else:
        print(f"마지막 수집: {fmt_kst(last)} KST ({age_h:.1f}시간 전) · 상태 {health.get('status', '?')}")
    failed = [k for k, v in (health.get("steps") or {}).items() if v.get("status") == "fail"]
    if failed:
        print(f"⚠️ 수집 실패 단계: {', '.join(failed)} (data/health.json)")

    for d in kst_dates(start, end):
        if d in index.get("security_dates", []):
            rep = load(DATA / "security" / f"{d}.json", {})
            read.append(f"data/security/{d}.json")
            print(f"보안 검토 {d}: 외부 텍스트 {rep.get('scanned_last_run', '?')}건 검사, "
                  f"격리 {rep.get('quarantined_count', rep.get('flagged_count', 0))}건")

    items = items_in(start, end, index, read)
    rechecked = 0
    for i, x in enumerate(items):
        items[i], hit = recheck(x)
        rechecked += hit
    if rechecked:
        print(f"⚠️ 로컬 2차 검사에서 {rechecked}건 추가 격리")

    if not items:
        print("\n새 항목 없음 (이 구간에 수집된 항목이 데이터에 없음)")
    else:
        order = {k: i for i, k in enumerate(LEVELS)}
        items.sort(key=lambda x: (order.get(x.get("importance"), 3), x.get("category") or "", x.get("title") or ""))
        print(f"\n항목 {len(items)}건 ({summarize_counts(items)})")
        cats = Counter(x.get("category") or "미분류" for x in items)
        print("분류: " + " · ".join(f"{k} {v}" for k, v in cats.most_common()))

        high = [x for x in items if x.get("importance") == "높음"]
        print(f"\n## 높음 ({len(high)})")
        for x in high:
            print(line(x))
        med = [x for x in items if x.get("importance") == "보통"]
        print(f"\n## 보통 ({len(med)}) — 상위 {min(len(med), args.medium)}개")
        for x in med[:args.medium]:
            print(line(x, with_reason=True))
        if len(med) > args.medium:
            rest = Counter(x.get("category") for x in med[args.medium:])
            print(f"- … 나머지 {len(med) - args.medium}건: " + ", ".join(f"{k} {v}" for k, v in rest.most_common()))
        low = [x for x in items if x.get("importance") == "낮음"]
        if low:
            why = Counter((x.get("importance_reason") or "").split(" '")[0].split(" (")[0] for x in low)
            print(f"\n## 낮음 ({len(low)}) — 목록 생략, 사유별: " + ", ".join(f"{k} {v}" for k, v in why.most_common(5)))
        unc = [x for x in items if not x.get("importance")]
        if unc:
            print(f"\n## 미분류 ({len(unc)}) — 다음 수집 때 분류됨")
            for x in unc[:5]:
                print(line(x, with_reason=False))

    if args.week:
        prev_start, prev_end = start - timedelta(days=7), end - timedelta(days=7)
        prev = items_in(prev_start, prev_end, index, read)
        print(f"\n## 지난주 같은 구간 비교 ({fmt_kst(prev_start)} ~ {fmt_kst(prev_end)})")
        if not prev:
            print("- 지난주 데이터 없음 (수집 시작 전) — 추이 비교 불가")
        else:
            now_c, prev_c = Counter(x.get("category") for x in items), Counter(x.get("category") for x in prev)
            for k in sorted(set(now_c) | set(prev_c), key=lambda k: -now_c.get(k, 0)):
                print(f"- {k}: {prev_c.get(k, 0)} → {now_c.get(k, 0)}")

    metrics = load(DATA / "metrics.json")
    if metrics:
        read.append("data/metrics.json")
        repos = metrics.get("repos", {})
        print(f"\n## 스타 지표 (data/metrics.json, {metrics.get('date')} · 이력 {metrics.get('history_days')}일)")
        surges = [(n, m) for n, m in repos.items() if m.get("surge")]
        warns = [(n, m) for n, m in repos.items() if m.get("warnings")]
        core = sorted(((n, m) for n, m in repos.items() if m.get("tier") == "core"),
                      key=lambda nm: (-(nm[1].get("d7") or nm[1].get("d1") or 0), -nm[1].get("stars", 0)))
        if metrics.get("history_days", 0) < 2:
            print("- 증가량 계산에 필요한 이력이 아직 부족함 (수집 1일차)")
        for n, m in surges[:10]:
            print(f"- 급등 {n}: ★{m['stars']:,} ({', '.join(m['surge'])})")
        for n, m in warns[:5]:
            print(f"- 참고 경고 {n}: {'; '.join(m['warnings'])} — 바이럴과 구분 어려움")
        top = [f"{n} ★{m['stars']:,}" + (f" (+{m['d1']} 1일)" if m.get("d1") is not None else "")
               for n, m in core[:5]]
        print("- 핵심 레포: " + ", ".join(top))

    print("\n읽은 파일: " + ", ".join(dict.fromkeys(read)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
