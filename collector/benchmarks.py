"""AI 코딩 벤치마크 — 공개·기계판독 가능한 출처만 (API 키 없음, AI 없음).

1) Terminal-Bench 2.1 (harbor-framework/terminal-bench-2-1, Apache-2.0)
   터미널에서 코딩 에이전트가 실제 작업(빌드·디버그·시스템 관리)을 해내는 비율. 모델 × 에이전트 × 추론 강도별 한 줄.
2) Epoch AI Benchmarking Hub (epoch.ai/data/benchmark_data.zip, CC BY 4.0 — 출처 표시 필수)
   SWE-bench Verified 등 여러 벤치마크의 모델별 점수 모음.

자주 바뀌지 않으므로: 바뀐 파일만 다시 받고(sha·날짜 비교), 새 기록이나 1위 변화가 있을 때만 항목을 만든다.
외부 텍스트(모델·에이전트 이름)는 store.clean으로 검사한다.
"""
import csv
import io
import re
import zipfile

TB_REPO = "harbor-framework/terminal-bench-2-1"
TB_LIST = f"/repos/{TB_REPO}/contents/leaderboard/submissions"
TB_PAGE = "https://www.tbench.ai/leaderboard/terminal-bench/2.1"
EPOCH_ZIP = "https://epoch.ai/data/benchmark_data.zip"
EPOCH_PAGE = "https://epoch.ai/benchmarks"
MAX_ZIP = 40 * 1024 * 1024
NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def terminal_bench(ctx):
    store = ctx.store
    state = store.load_json("benchmarks/terminal_bench.json", None)
    bootstrap = state is None
    state = state or {"files": {}}
    listing = ctx.client.get(TB_LIST).json()
    files = [f for f in listing if isinstance(f, dict) and f.get("name", "").endswith(".json")]
    if not files:
        raise RuntimeError("Terminal-Bench 제출 목록이 비어 있음 — 저장소 구조 변경 가능성")
    old_top = (state.get("rows") or [{}])[0].get("model") if state.get("rows") else None
    fetched = new = 0
    seen = set()
    for f in files:
        name, sha = f["name"], f.get("sha")
        seen.add(name)
        rec = state["files"].get(name)
        if rec and rec.get("sha") == sha:
            continue
        d = ctx.client.get(f["download_url"]).json()
        fetched += 1
        meta, m = d.get("metadata") or {}, d.get("metrics") or {}
        model = store.clean((meta.get("model_display") or {}).get("label") or meta.get("model_name") or name, 80,
                            "github_release", f"bench:{name}", "model")
        agent = store.clean((meta.get("agent_display") or {}).get("label") or "", 60, "github_release", f"bench:{name}", "agent")
        row = {"sha": sha, "model": model, "agent": agent, "effort": str(meta.get("reasoning_effort") or "")[:20],
               "date": str(meta.get("date") or name[:10])[:10], "accuracy": _num(m.get("accuracy")),
               "stderr": _num(m.get("accuracy_stderr")), "trials": m.get("n_trials"), "cost_usd": _num(m.get("total_cost_usd"))}
        if row["accuracy"] is None:
            continue
        is_new = rec is None
        state["files"][name] = row
        if is_new and not bootstrap:
            new += 1
            store.add_item({
                "id": f"bench-tb:{name}", "type": "benchmark_update", "source": "benchmark",
                "title": f"Terminal-Bench 2.1 새 기록: {model} + {agent} ({row['effort'] or '기본'}) {row['accuracy']}%",
                "url": TB_PAGE, "published_at": f"{row['date']}T00:00:00Z" if re.match(r"\d{4}-\d{2}-\d{2}$", row["date"]) else None,
            })
    for gone in set(state["files"]) - seen:
        del state["files"][gone]
    # 모델별 최고 기록 한 줄 (같은 모델의 다른 에이전트·추론 강도는 접는다)
    best = {}
    for r in state["files"].values():
        if r["model"] not in best or r["accuracy"] > best[r["model"]]["accuracy"]:
            best[r["model"]] = r
    rows = sorted(best.values(), key=lambda r: -r["accuracy"])
    state.update({"benchmark": "Terminal-Bench 2.1", "measures": "터미널에서 코딩 에이전트가 실제 작업을 끝까지 해내는 비율",
                  "source": f"https://github.com/{TB_REPO}", "page": TB_PAGE, "license": "Apache-2.0",
                  "checked_at": store.now_iso, "rows": [{k: v for k, v in r.items() if k != "sha"} for r in rows]})
    store.write_json("benchmarks/terminal_bench.json", state)
    if rows and old_top and rows[0]["model"] != old_top:
        store.add_item({
            "id": f"bench-tb-top:{rows[0]['model']}:{store.today}", "type": "benchmark_update", "source": "benchmark",
            "title": f"Terminal-Bench 2.1 1위 변경: {old_top} → {rows[0]['model']} ({rows[0]['accuracy']}%)", "url": TB_PAGE})
    return f"files={len(files)} fetched={fetched} new={new} models={len(rows)} bootstrap={bootstrap}"


# Epoch 압축 파일 안에서 코딩에 직결되는 벤치마크만 (파일명, 표시명, 설명, 점수 열, 단위, 부가 열)
EPOCH_SETS = [
    ("swe_bench_verified.csv", "SWE-bench Verified", "실제 GitHub 이슈를 고쳐 테스트를 통과시키는 비율", "mean_score", "%", "stderr"),
    ("webdev_arena_external.csv", "WebDev Arena", "웹앱 만들기 결과를 사람이 비교해 매긴 점수", "Arena Score", "점", "Votes"),
    ("frontierswe_external.csv", "FrontierSWE", "구현·성능·연구가 섞인 어려운 소프트웨어 작업 점수", "Score", "%", "Harness"),
]


def epoch(ctx):
    """Epoch 압축 파일에서 코딩 벤치마크 3종을 모델별 최고 점수로 정리. 1위가 바뀌면 항목 생성."""
    store = ctx.store
    prev = store.load_json("benchmarks/epoch.json", None)
    r = ctx.client.get(EPOCH_ZIP)
    if len(r.body) > MAX_ZIP:
        raise RuntimeError(f"Epoch 데이터가 너무 큼 ({len(r.body) // 1024 // 1024}MB)")
    zf = zipfile.ZipFile(io.BytesIO(r.body))
    names = set(zf.namelist())
    sets, missing = [], []
    for fname, label, measures, col, unit, extra in EPOCH_SETS:
        if fname not in names:
            missing.append(fname)
            continue
        with zf.open(fname) as fh:
            rows = list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace")))
        best = {}
        for row in rows:
            score = _num(row.get(col))
            raw_model = (row.get("Model version") or "").strip()
            if score is None or not raw_model:
                continue
            if raw_model not in best or score > best[raw_model]["score"]:
                ex = (row.get(extra) or "").strip()
                if extra == "stderr" and _num(ex) is not None:       # 표준오차 비율 → ±%p
                    ex = f"±{_num(ex) * 100:.1f}" if _num(ex) <= 1 else f"±{ex}"
                elif extra == "Votes" and ex:
                    ex = f"{ex}표"
                best[raw_model] = {"raw": raw_model, "score": score, "org": (row.get("Organization") or "")[:40],
                                   "released": (row.get("Release date") or "")[:10], "extra": ex[:40]}
        if not best:
            missing.append(f"{fname}(빈 데이터)")
            continue
        ranked = sorted(best.values(), key=lambda x: -x["score"])
        if unit == "%" and ranked[0]["score"] <= 1:          # 0~1 비율이면 %로
            for x in ranked:
                x["score"] = round(x["score"] * 100, 1)
        top = []
        for x in ranked[:12]:
            top.append({"model": store.clean(x["raw"], 80, "github_release", f"epoch:{fname}", "model"),
                        "org": store.clean(x["org"], 40, "github_release", f"epoch:{fname}", "org"),
                        "score": x["score"], "released": x["released"],
                        "extra": store.clean(x["extra"], 40, "github_release", f"epoch:{fname}", "extra")})
        sets.append({"benchmark": label, "measures": measures, "unit": unit, "file": fname, "models": len(best), "top": top})
        old = next((s for s in (prev or {}).get("sets", []) if s["benchmark"] == label), None)
        if old and old["top"] and old["top"][0]["model"] != top[0]["model"]:
            store.add_item({
                "id": f"bench-epoch-top:{label}:{top[0]['model']}", "type": "benchmark_update", "source": "benchmark",
                "title": f"{label} 1위 변경: {old['top'][0]['model']} → {top[0]['model']} ({top[0]['score']}{unit})",
                "url": EPOCH_PAGE})
    if not sets:
        raise RuntimeError("Epoch 데이터에서 코딩 벤치마크를 찾지 못함 — 파일 구조 변경 가능성")
    store.write_json("benchmarks/epoch.json", {
        "source": EPOCH_PAGE, "download": EPOCH_ZIP, "license": "CC BY 4.0",
        "attribution": "Data: Epoch AI, Benchmarking Hub (epoch.ai/benchmarks), CC BY 4.0",
        "checked_at": store.now_iso, "missing": missing, "sets": sets})
    return f"sets={len(sets)} missing={len(missing)} bytes={len(r.body)}"
