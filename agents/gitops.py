"""Git/GitHub helpers. In CI uses the checked-out repo + GH_TOKEN; locally degrades to file writes only."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Any, Callable

from .settings import REPO, ROOT, TOPICS_FILE, env
from .topics import Tracker

log = logging.getLogger("tb.git")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, check=check, text=True, capture_output=True)


def has_remote() -> bool:
    return git("remote", check=False).stdout.strip() != "" and env("TB_NO_PUSH") is None


def sync_tracker(mutate: Callable[[Tracker], Any], message: str, extra_paths: list[str] | None = None) -> Any:
    """Apply `mutate` to the latest topics.json on main, commit and push (retrying on races).

    The mutation is re-applied on a fresh copy each attempt, so concurrent edits from the
    Telegram worker or other runs are never clobbered.
    """
    if not has_remote():
        t = Tracker()
        result = mutate(t)
        t.save()
        return result
    for attempt in range(5):
        git("fetch", "origin", "main")
        git("checkout", "-q", "main")
        git("reset", "-q", "--hard", "origin/main")
        t = Tracker(TOPICS_FILE)
        result = mutate(t)
        t.save()
        git("add", str(TOPICS_FILE), *(extra_paths or []))
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return result
        git("commit", "-q", "-m", message)
        if git("push", "origin", "main", check=False).returncode == 0:
            return result
        log.warning("push race, retrying (%d)", attempt + 1)
        time.sleep(2 + attempt * 2)
    raise RuntimeError("could not push tracker update")


def publish_branch(slug: str, paths: list[str], title: str, body: str) -> tuple[int | None, str]:
    """Commit the given (untracked) files to post/<slug> off origin/main and open a PR."""
    if not has_remote():
        return None, ""
    branch = f"post/{slug}"
    git("fetch", "origin", "main")
    git("checkout", "-q", "-B", branch, "origin/main")
    git("add", *paths)
    git("commit", "-q", "-m", f"post: {title}")
    git("push", "-q", "-f", "origin", branch)
    git("checkout", "-q", "main")
    if not shutil.which("gh"):
        return None, ""
    existing = subprocess.run(["gh", "pr", "list", "--repo", REPO, "--head", branch, "--json", "number,url"],
                              cwd=ROOT, text=True, capture_output=True)
    prs = json.loads(existing.stdout or "[]")
    if prs:
        return prs[0]["number"], prs[0]["url"]
    r = subprocess.run(["gh", "pr", "create", "--repo", REPO, "--base", "main", "--head", branch, "--title",
                        f"post: {title}", "--body", body, "--label", "blog-post"], cwd=ROOT, text=True, capture_output=True)
    if r.returncode != 0:  # label may not exist yet
        r = subprocess.run(["gh", "pr", "create", "--repo", REPO, "--base", "main", "--head", branch, "--title",
                            f"post: {title}", "--body", body], cwd=ROOT, text=True, capture_output=True, check=True)
    url = r.stdout.strip().splitlines()[-1]
    return int(url.rstrip("/").rsplit("/", 1)[-1]), url
