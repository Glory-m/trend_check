"""멱등 저장소.

- items/YYYY-MM-DD.json : 그날(KST) '처음' 수집된 항목만. 같은 id는 seen_ids.json으로 영구 차단.
- snapshots/YYYY-MM-DD.json : 레포 수치. 같은 날 재실행 시 해당 레포 값을 덮어쓴다.
- index.json : 날짜 목록·항목 수·마지막 수집 시각 — 스킬·사이트가 디렉터리를 훑지 않고 필요한 파일만 고르게 한다.
"""
import json
import os
import tempfile
from pathlib import Path

from . import safety
from .timeutil import iso, kst_date

TITLE_MAX, BODY_MAX, DESC_MAX = 300, 1000, 300


class Store:
    def __init__(self, data_dir, now):
        self.dir = Path(data_dir)
        self.now = now
        self.now_iso = iso(now)
        self.today = kst_date(now)
        self.seen = self.load_json("seen_ids.json", {})
        self.index = self.load_json("index.json", {"item_dates": {}, "snapshot_dates": []})
        self.pending = []
        self.snapshot = self.load_json(f"snapshots/{self.today}.json", {"date": self.today, "repos": {}})
        self._prev_snapshot = None
        self.scanned = 0
        self.flagged = []   # 이번 실행에서 격리한 외부 텍스트 (원문은 저장하지 않음)

    # ---- 외부 텍스트 안전 처리 ----
    def clean(self, text, maxlen, source, ref, field, url=None):
        """모든 외부 텍스트의 관문: 정규화·길이 제한, 의심 패턴이면 격리 문구로 대체하고 기록."""
        if text is None:
            return None
        self.scanned += 1
        out, flags = safety.clean(text, maxlen, source)
        if flags:
            self.flagged.append({"ref": ref, "field": field, "source": source, "flags": flags,
                                 "sha256_16": safety.fingerprint(str(text)), "length": len(str(text)),
                                 "url": safety.safe_url(url)})
        return out

    # ---- 파일 입출력 ----
    def load_json(self, rel, default):
        p = self.dir / rel
        if not p.exists():
            return default
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def write_json(self, rel, obj):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, p)

    # ---- 항목 ----
    def add_item(self, item):
        """새 항목이면 collected_at을 찍고 보류 목록에 넣는다. 이미 본 id면 False."""
        if item["id"] in self.seen or any(x["id"] == item["id"] for x in self.pending):
            return False
        base = {
            "id": None, "type": None, "title": None, "body": None, "url": None,
            "repo": None, "version": None, "source": None,
            "published_at": None, "collected_at": self.now_iso,
            "category": None, "importance": None, "importance_reason": None, "classified_by": None,
        }
        base.update(item)
        base["collected_at"] = self.now_iso
        base["url"] = safety.safe_url(base["url"])
        n_before = len(self.flagged)
        base["title"] = self.clean(base["title"], TITLE_MAX, base["source"], base["id"], "title", base["url"])
        base["body"] = self.clean(base["body"], BODY_MAX, base["source"], base["id"], "body", base["url"])
        if len(self.flagged) > n_before:
            flags = sorted({f for x in self.flagged[n_before:] for f in x["flags"]})
            base["security_flags"] = flags
            base["quarantined"] = True
            # 레포 이름은 GitHub이 [A-Za-z0-9._-]만 허용하므로 안전
            base["title"] = f"[격리됨] {base['repo'] or base['source']} — 의심 문구 감지({', '.join(flags)}). 원문은 링크에서 직접 확인"
            base["body"] = None
        self.pending.append(base)
        return True

    # ---- 스냅샷 ----
    def set_snapshot(self, repo, entry):
        entry = dict(entry)
        entry["collected_at"] = self.now_iso
        if entry.get("description") is not None:
            entry["description"] = self.clean(entry["description"], DESC_MAX, "search", f"repo:{repo}",
                                              "description", f"https://github.com/{repo}")
        self.snapshot["repos"][repo] = entry

    def has_snapshot_today(self, repo):
        return repo in self.snapshot["repos"]

    def prev_snapshot(self):
        """오늘 이전 가장 최근 스냅샷 (없으면 빈 dict)."""
        if self._prev_snapshot is None:
            dates = [d for d in self.index.get("snapshot_dates", []) if d < self.today]
            self._prev_snapshot = (self.load_json(f"snapshots/{max(dates)}.json", {"repos": {}})
                                   if dates else {"repos": {}})
        return self._prev_snapshot

    # ---- 반영 ----
    def flush(self):
        if self.pending:
            rel = f"items/{self.today}.json"
            day = self.load_json(rel, {"date": self.today, "items": []})
            known = {x["id"] for x in day["items"]}
            day["items"].extend(x for x in self.pending if x["id"] not in known)
            self.write_json(rel, day)
            for x in self.pending:
                self.seen[x["id"]] = self.today
            self.write_json("seen_ids.json", dict(sorted(self.seen.items())))
            self.index["item_dates"][self.today] = len(day["items"])
        if self.snapshot["repos"]:
            self.snapshot["repos"] = dict(sorted(self.snapshot["repos"].items()))
            self.write_json(f"snapshots/{self.today}.json", self.snapshot)
            dates = set(self.index.get("snapshot_dates", []))
            dates.add(self.today)
            self.index["snapshot_dates"] = sorted(dates)
        self._write_security_report()
        self.index["item_dates"] = dict(sorted(self.index["item_dates"].items()))
        self.index["last_collected_at"] = self.now_iso
        self.write_json("index.json", self.index)
        added = len(self.pending)
        self.pending = []
        return added

    def _write_security_report(self):
        """data/security/YYYY-MM-DD.json — 그날의 인젝션 검사 결과 (같은 날 재실행 시 병합)."""
        rel = f"security/{self.today}.json"
        rep = self.load_json(rel, {"date": self.today, "flagged": []})
        known = {(x["ref"], x["field"], x["sha256_16"]) for x in rep["flagged"]}
        rep["flagged"].extend(x for x in self.flagged if (x["ref"], x["field"], x["sha256_16"]) not in known)
        rep.update({"last_scan_at": self.now_iso, "scanned_last_run": self.scanned,
                    "flagged_count": len(rep["flagged"]),
                    "rules": "collector/safety.py (규칙 기반, AI 미사용)"})
        self.write_json(rel, rep)
        dates = set(self.index.get("security_dates", []))
        dates.add(self.today)
        self.index["security_dates"] = sorted(dates)
