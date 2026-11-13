"""Topic/idea tracker stored in ops/topics.json (public: titles + status only, never chat text or uploads).

Statuses: idea -> queued -> in_progress -> in_review -> published | rejected
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .settings import TOPICS_FILE

STATUSES = ("idea", "queued", "in_progress", "in_review", "published", "rejected")
STOP = set("a an the of for and or to in on with how why what is are vs using your you from into at by".split())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def similarity(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class Tracker:
    def __init__(self, path: Path = TOPICS_FILE):
        self.path = path
        self.data: dict[str, Any] = {"version": 1, "next_id": 1, "topics": []}
        if path.exists():
            self.data = json.loads(path.read_text())

    # ---- persistence
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    @property
    def topics(self) -> list[dict[str, Any]]:
        return self.data["topics"]

    # ---- queries
    def get(self, tid: str) -> dict[str, Any] | None:
        tid = tid.strip().upper()
        return next((t for t in self.topics if t["id"] == tid), None)

    def by_status(self, *statuses: str) -> list[dict[str, Any]]:
        return [t for t in self.topics if t["status"] in statuses]

    def by_slug(self, slug: str) -> dict[str, Any] | None:
        return next((t for t in self.topics if t.get("slug") == slug), None)

    def by_pr(self, pr: int) -> dict[str, Any] | None:
        return next((t for t in self.topics if t.get("pr") == pr), None)

    def similar(self, title: str, threshold: float = 0.5) -> list[tuple[float, dict[str, Any]]]:
        hits = [(similarity(title, t["title"]), t) for t in self.topics if t["status"] != "rejected"]
        return sorted([h for h in hits if h[0] >= threshold], key=lambda h: -h[0])

    # ---- mutations
    def add(self, title: str, *, notes: str = "", tags: list[str] | None = None, source: str = "cli",
            status: str = "idea") -> dict[str, Any]:
        tid = f"T{self.data['next_id']:03d}"
        self.data["next_id"] += 1
        t = {
            "id": tid,
            "title": title.strip()[:200],
            "notes": notes.strip()[:1000],
            "status": status,
            "tags": tags or [],
            "source": source,
            "created": _now(),
            "updated": _now(),
            "slug": None,
            "pr": None,
            "url": None,
            "private_files": False,
            "history": [{"at": _now(), "status": status}],
        }
        self.topics.append(t)
        return t

    def set(self, t: dict[str, Any], status: str | None = None, **fields: Any) -> dict[str, Any]:
        if status:
            if status not in STATUSES:
                raise ValueError(f"bad status {status}")
            t["status"] = status
            t.setdefault("history", []).append({"at": _now(), "status": status})
        t.update(fields)
        t["updated"] = _now()
        return t

    # ---- reporting
    def summary(self) -> str:
        groups = {s: self.by_status(s) for s in STATUSES}
        lines = [f"📚 {len(self.topics)} topics · ✅ {len(groups['published'])} published · "
                 f"🛠 {len(groups['in_progress']) + len(groups['queued'])} in progress · "
                 f"👀 {len(groups['in_review'])} in review · 💡 {len(groups['idea'])} ideas"]
        for s, icon in (("in_review", "👀"), ("in_progress", "🛠"), ("queued", "⏳"), ("idea", "💡"), ("published", "✅")):
            for t in groups[s][-15:]:
                extra = f" → {t['url']}" if t.get("url") else (f" (PR #{t['pr']})" if t.get("pr") else "")
                lines.append(f"{icon} {t['id']} {t['title']}{extra}")
        return "\n".join(lines)


def today() -> str:
    return date.today().isoformat()
