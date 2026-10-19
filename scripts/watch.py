"""watchlist.yml 편집 — /watch용. 주석을 보존하기 위해 YAML을 다시 쓰지 않고 해당 블록만 추가·삭제한다.

사용: python scripts/watch.py list
      python scripts/watch.py add owner/repo [--note "메모"]
      python scripts/watch.py remove owner/repo
네트워크를 쓰지 않는다. 레포 정보는 이미 수집된 데이터(후보·스냅샷)에 있으면 보여 주고, 없으면 '미확인'으로 표시한다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "watchlist.yml"
DATA = ROOT / "data"
REPO_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def known_info(name):
    idx = json.loads((DATA / "index.json").read_text(encoding="utf-8")) if (DATA / "index.json").exists() else {}
    dates = idx.get("snapshot_dates", [])
    snap = json.loads((DATA / "snapshots" / f"{dates[-1]}.json").read_text(encoding="utf-8"))["repos"] if dates else {}
    cands = json.loads((DATA / "candidates.json").read_text(encoding="utf-8"))["repos"] if (DATA / "candidates.json").exists() else {}
    for src in (snap, cands):
        for k, v in src.items():
            if k.lower() == name.lower():
                return v
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list", "add", "remove"])
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    text = WATCHLIST.read_text(encoding="utf-8")
    repos = yaml.safe_load(text)["repos"]
    names = {r["repo"].lower(): r["repo"] for r in repos}

    if args.action == "list":
        print(f"핵심 watchlist {len(repos)}개 (watchlist.yml)")
        for r in repos:
            print(f"- {r['repo']}" + (f" — {r['note']}" if r.get("note") else ""))
        return 0

    if not args.repo or not REPO_RX.match(args.repo):
        print("오류: owner/repo 형식이 아님 (영문·숫자·-·_·. 만 허용)", file=sys.stderr)
        return 1
    info = known_info(args.repo)

    if args.action == "add":
        if args.repo.lower() in names:
            print(f"이미 watchlist에 있음: {names[args.repo.lower()]}")
            return 0
        note = re.sub(r"[\r\n#]", " ", args.note).strip()[:80]
        block = f"  - repo: {args.repo}\n" + (f"    note: {note}\n" if note else "")
        WATCHLIST.write_text(text.rstrip("\n") + "\n" + block, encoding="utf-8", newline="\n")
        status = (f"수집 데이터에 있음 (★{info.get('stars')}, {(info.get('description') or '')[:80]})" if info
                  else "수집 데이터에 없음 — 존재 여부 미확인. 다음 수집 때 확인되며, 없으면 health.json에 실패로 기록됨")
        print(f"추가함: {args.repo} · {status}")
        return 0

    if args.repo.lower() not in names:
        print(f"watchlist에 없음: {args.repo}")
        return 1
    target = names[args.repo.lower()]
    lines, out, skipping = text.splitlines(keepends=True), [], False
    for ln in lines:
        if re.match(r"^\s*-\s+repo:\s*", ln):
            skipping = ln.split("repo:", 1)[1].strip() == target
        elif not ln.startswith("    "):
            skipping = False
        if not skipping:
            out.append(ln)
    WATCHLIST.write_text("".join(out), encoding="utf-8", newline="\n")
    print(f"제거함: {target} (이력 데이터는 그대로 남음, 후보로 다시 잡힐 수 있음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
