"""레포 스냅샷 — 핵심 watchlist(수동 관리)와 자동 후보 풀(candidates.json)."""
from datetime import timedelta

from .timeutil import parse_iso

CC_REPO = "anthropics/claude-code"   # release는 claude_code 모듈이 버전별로 처리


def core_names(watchlist):
    """watchlist 레포 이름과 옛 이름(aliases)을 소문자 집합으로."""
    names = set()
    for e in watchlist:
        names.add(e["repo"].lower())
        names.update(a.lower() for a in e.get("aliases", []))
    return names


def stats_from_api(d, tier):
    return {
        "tier": tier,
        "stars": d.get("stargazers_count"),
        "forks": d.get("forks_count"),
        "open_issues": d.get("open_issues_count"),
        "pushed_at": d.get("pushed_at"),
        "created_at": d.get("created_at"),
        "archived": d.get("archived", False),
        "description": (d.get("description") or "")[:300],
        "language": d.get("language"),
    }


def collect_core(ctx):
    store, client = ctx.store, ctx.client
    prev = store.prev_snapshot()["repos"]
    first_days = timedelta(days=ctx.rules["watchlist"]["first_release_days"])
    failed = []
    for entry in ctx.watchlist:
        repo = entry["repo"]
        try:
            d = client.get(f"/repos/{repo}").json()
            r = client.get(f"/repos/{repo}/releases/latest", ok404=True)
        except Exception as e:
            failed.append(repo)
            ctx.warn("watchlist", f"{repo}: {e}")
            continue
        latest = None
        if r.status == 200:
            rd = r.json()
            latest = {"tag": rd.get("tag_name"), "name": rd.get("name"),
                      "published_at": rd.get("published_at"), "url": rd.get("html_url")}
        snap = stats_from_api(d, "core")
        snap["latest_release"] = latest
        store.set_snapshot(repo, snap)

        if d.get("full_name", repo).lower() != repo.lower():
            store.add_item({
                "id": f"rename:{repo}:{d['full_name']}", "type": "repo_renamed", "repo": repo,
                "title": f"{repo} → {d['full_name']} 로 이름 변경됨 (watchlist.yml 갱신 필요)",
                "url": d.get("html_url"), "source": "snapshot",
            })
        if d.get("archived"):
            store.add_item({
                "id": f"archived:{repo}", "type": "repo_archived", "repo": repo,
                "title": f"{repo} 가 보관(archived) 처리됨 — 더 이상 유지보수되지 않음",
                "url": d.get("html_url"), "source": "snapshot",
            })
        if latest and repo != CC_REPO:
            before = prev.get(repo)
            prev_tag = ((before or {}).get("latest_release") or {}).get("tag")
            pub = parse_iso(latest["published_at"])
            if (before and latest["tag"] != prev_tag) or (
                    not before and pub and ctx.now - pub <= first_days):
                store.add_item({
                    "id": f"rel:{repo}:{latest['tag']}", "type": "repo_release", "repo": repo,
                    "title": f"{repo} {latest['tag']} 릴리스" + (f" — {latest['name']}" if latest.get("name") and latest["name"] != latest["tag"] else ""),
                    "url": latest["url"], "version": latest["tag"], "source": "github_release",
                    "published_at": latest["published_at"],
                })
    if failed and len(failed) == len(ctx.watchlist):
        raise RuntimeError(f"watchlist 전체 실패 ({len(failed)}개)")
    return f"repos={len(ctx.watchlist) - len(failed)} failed={len(failed)}"


def velocity(info, now):
    """별 속도 = 별 수 / 나이(일, 최소 7). 신예의 급성장과 대형 레포를 한 기준으로 비교한다."""
    created = parse_iso(info.get("created_at"))
    age = max((now - created).days, 7) if created else 30
    return round((info.get("stars") or 0) / age, 2)


def finalize_candidates(ctx):
    """오늘 발견분을 후보 풀에 반영 → 순위로 최대 개수 유지 → 남은 후보만 스냅샷 → 신규 발견 항목(상위 N개)."""
    pool, store = ctx.candidates["repos"], ctx.store
    cfg = ctx.rules["candidates"]
    core = core_names(ctx.watchlist)
    new_window = timedelta(days=ctx.rules["discovery"]["new_candidate_days"])

    entered = []
    for name, x in ctx.found.items():
        info = x["info"]
        rec = pool.get(name)
        if rec is None:
            rec = {"first_seen_at": store.now_iso, "sources": []}
            entered.append(name)
        rec["last_seen_at"] = store.now_iso
        rec["sources"] = sorted(set(rec["sources"]) | x["labels"])
        rec["trending_today"] = any(l.startswith("trending:") for l in x["labels"])
        for k in ("created_at", "language", "stars"):
            if info.get(k) is not None:
                rec[k] = info[k]
        if info.get("description") is not None:
            rec["description"] = store.clean(info["description"], 300, "search", f"repo:{name}", "description",
                                             f"https://github.com/{name}")
        rec["score"] = velocity(rec, ctx.now)
        rec["url"] = f"https://github.com/{name}"
        pool[name] = rec

    drop_before = ctx.now - timedelta(days=cfg["drop_after_days"])
    for name in list(pool):
        last = parse_iso(pool[name].get("last_seen_at"))
        if name.lower() in core or (last and last < drop_before):
            del pool[name]
    seen_today = {n for n in pool if pool[n]["last_seen_at"] == store.now_iso}
    for n in set(pool) - seen_today:
        pool[n]["trending_today"] = False
    ranked = sorted(pool, key=lambda n: (pool[n].get("trending_today", False), pool[n].get("score", 0)), reverse=True)
    for name in ranked[cfg["max_tracked"]:]:
        del pool[name]

    for name in pool:
        if name in seen_today:
            store.set_snapshot(name, ctx.found[name]["info"] | {"tier": "candidate"})

    fresh = [n for n in entered if n in pool]
    if ctx.candidates_bootstrap:   # 첫 실행: 오래된 레포는 '신규'가 아님
        fresh = [n for n in fresh if (c := parse_iso(pool[n].get("created_at"))) and ctx.now - c <= new_window]
    fresh.sort(key=lambda n: pool[n]["score"], reverse=True)
    for name in fresh[:cfg["max_new_items_per_day"]]:
        rec = pool[name]
        store.add_item({
            "id": f"cand:{name}", "type": "candidate_new", "repo": name,
            "title": f"신규 발견: {name} (★{rec.get('stars')}, 하루 ★{rec['score']})",
            "body": rec.get("description"), "url": rec["url"],
            "source": sorted(rec["sources"])[0].split(":")[0], "published_at": rec.get("created_at"),
        })

    ctx.candidates["updated_at"] = store.now_iso
    ctx.candidates["repos"] = dict(sorted(pool.items()))
    store.write_json("candidates.json", ctx.candidates)
    return f"found={len(ctx.found)} tracked={len(pool)} entered={len(fresh)} new_items={min(len(fresh), cfg['max_new_items_per_day'])}"
