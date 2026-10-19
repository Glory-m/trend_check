"""스타 지표 — 1·7·30일 증가량·증가율, 가속도, 급등, 의심 패턴, 승격·강등 제안 (AI 없음).

과거 스타 이력은 복원하지 않는다. data/series.json에 오늘부터 하루 한 칸씩 쌓는다.
의심 패턴은 '참고 경고'일 뿐 — 바이럴로 생긴 급성장과 구분하기 어렵다.
"""
from datetime import date, timedelta

from .timeutil import parse_iso


def update_series(ctx):
    """오늘 스냅샷의 별 수를 series.json에 기록 (같은 날 재실행은 마지막 칸 덮어쓰기)."""
    store, keep = ctx.store, ctx.rules["stars"]["series_days"]
    s = store.load_json("series.json", {"dates": [], "repos": {}})
    if not s["dates"] or s["dates"][-1] != store.today:
        s["dates"].append(store.today)
        for v in s["repos"].values():
            v.append(None)
    col = len(s["dates"]) - 1
    for name, snap in store.snapshot["repos"].items():
        row = s["repos"].setdefault(name, [None] * len(s["dates"]))
        row[col] = snap.get("stars")
    if len(s["dates"]) > keep:                      # 오래된 칸 잘라내기
        cut = len(s["dates"]) - keep
        s["dates"] = s["dates"][cut:]
        s["repos"] = {k: v[cut:] for k, v in s["repos"].items()}
    s["repos"] = {k: v for k, v in sorted(s["repos"].items()) if any(x is not None for x in v)}
    store.write_json("series.json", s)
    return s


def value_at(series, row, days_ago, today):
    """오늘로부터 N일 이전(또는 그보다 이전 중 가장 가까운) 날의 값과 그 날짜."""
    target = (date.fromisoformat(today) - timedelta(days=days_ago)).isoformat()
    for i in range(len(series["dates"]) - 1, -1, -1):
        d = series["dates"][i]
        if d <= target and row[i] is not None:
            return row[i], d
    return None, None


def pct(delta, base):
    return round(100 * delta / base, 2) if delta is not None and base else None


def run(ctx):
    store, cfg = ctx.store, ctx.rules["stars"]
    series = update_series(ctx)
    today, week = store.today, ctx.now.strftime("%G-W%V")
    surge_cfg, sus_cfg = cfg["surge"], cfg["suspicious"]
    out, surges, warns, promos, demos = {}, 0, 0, 0, 0

    for name, snap in store.snapshot["repos"].items():
        stars = snap.get("stars")
        row = series["repos"].get(name)
        if stars is None or row is None:
            continue
        m = {"tier": snap.get("tier"), "stars": stars, "forks": snap.get("forks")}
        bases = {}
        for key, days in (("d1", 1), ("d7", 7), ("d14", 14), ("d30", 30)):
            base, bdate = value_at(series, row, days, today)
            bases[key] = base
            if key != "d14":
                m[key] = stars - base if base is not None else None
                m[f"{key}_pct"] = pct(m[key], base)
                m[f"{key}_since"] = bdate
        m["accel"] = ((stars - bases["d7"]) - (bases["d7"] - bases["d14"])
                      if bases["d7"] is not None and bases["d14"] is not None else None)

        # 급등 — 절대값 또는 비율
        reasons = []
        if m["d1"] is not None:
            if m["d1"] >= surge_cfg["d1_abs"]:
                reasons.append(f"1일 +{m['d1']}")
            elif stars >= surge_cfg["min_stars"] and m["d1"] >= surge_cfg["d1_min_abs"] and (m["d1_pct"] or 0) >= surge_cfg["d1_pct"]:
                reasons.append(f"1일 +{m['d1_pct']}%")
        if m["d7"] is not None:
            if m["d7"] >= surge_cfg["d7_abs"]:
                reasons.append(f"7일 +{m['d7']}")
            elif stars >= surge_cfg["min_stars"] and m["d7"] >= surge_cfg["d7_min_abs"] and (m["d7_pct"] or 0) >= surge_cfg["d7_pct"]:
                reasons.append(f"7일 +{m['d7_pct']}%")
        m["surge"] = reasons
        if reasons:
            surges += store.add_item({
                "id": f"surge:{name}:{week}", "type": "repo_surge", "repo": name,
                "title": f"급등: {name} ★{stars:,} ({', '.join(reasons)})",
                "body": snap.get("description"), "url": f"https://github.com/{name}", "source": "snapshot",
            })

        # 의심 패턴 — 참고 경고
        w = []
        forks = snap.get("forks") or 0
        if stars >= sus_cfg["star_fork_min_stars"] and stars / max(forks, 1) > sus_cfg["star_fork_ratio"]:
            w.append(f"포크 대비 별이 매우 많음 (별/포크 {stars // max(forks, 1)})")
        created = parse_iso(snap.get("created_at"))
        if created and (ctx.now - created).days <= sus_cfg["young_days"] and stars >= sus_cfg["young_stars"] \
                and forks < stars * 0.01:
            w.append(f"생성 {(ctx.now - created).days}일 만에 ★{stars:,}, 포크 1% 미만")
        if m["d7"] and m["d7"] >= sus_cfg["step_min_abs"]:
            daily = [row[i] - row[i - 1] for i in range(max(1, len(row) - 7), len(row))
                     if row[i] is not None and row[i - 1] is not None]
            if daily and max(daily) >= sus_cfg["step_share"] * m["d7"] and len(daily) >= 5:
                w.append(f"7일 증가분의 {round(100 * max(daily) / m['d7'])}%가 하루에 몰림 (계단식)")
        m["warnings"] = w
        if w:
            warns += store.add_item({
                "id": f"susp:{name}:{week}", "type": "suspicious", "repo": name,
                "title": f"참고 경고: {name} 스타 패턴 이상 — " + "; ".join(w),
                "body": "바이럴로 생긴 급성장과 구분하기 어렵다. 판단 근거로만 참고.",
                "url": f"https://github.com/{name}", "source": "snapshot",
            })

        # 승격·강등 제안 (자동 반영 금지)
        p = cfg["promote"]
        pushed = parse_iso(snap.get("pushed_at"))
        if m["tier"] == "candidate" and m["d7"] is not None and pushed \
                and (ctx.now - pushed).days <= p["pushed_within_days"] \
                and (m["d7"] >= p["d7_abs"] or (stars >= p["min_stars"] and (m["d7_pct"] or 0) >= p["d7_pct"])):
            promos += store.add_item({
                "id": f"promote:{name}:{week}", "type": "promote_suggest", "repo": name,
                "title": f"watchlist 추가 제안: {name} (7일 +{m['d7']}, +{m['d7_pct']}%)",
                "body": "자동 추가하지 않음 — /watch 로 직접 추가", "url": f"https://github.com/{name}",
                "source": "snapshot",
            })
        d = cfg["demote"]
        if m["tier"] == "core" and pushed and (ctx.now - pushed).days >= d["no_push_days"] \
                and m["d30_pct"] is not None and m["d30_pct"] < d["d30_pct_below"]:
            demos += store.add_item({
                "id": f"demote:{name}:{today[:7]}", "type": "demote_suggest", "repo": name,
                "title": f"watchlist 제거 검토: {name} ({(ctx.now - pushed).days}일 push 없음, 30일 +{m['d30_pct']}%)",
                "body": "자동 제거하지 않음 — /watch 로 직접 제거", "url": f"https://github.com/{name}",
                "source": "snapshot",
            })
        out[name] = m

    store.write_json("metrics.json", {
        "date": today, "generated_at": store.now_iso, "history_days": len(series["dates"]),
        "note": "d7·d30 등은 이력이 쌓인 만큼만 계산됨 (null = 데이터 부족). 의심 경고는 참고용.",
        "repos": dict(sorted(out.items())),
    })
    return f"repos={len(out)} history_days={len(series['dates'])} surges={surges} warnings={warns} promote={promos} demote={demos}"
