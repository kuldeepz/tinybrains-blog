"""Post videos: ask the video pipeline (a separate private repo) for a post's 5-minute video, and attach it when it's on YouTube.

    published post --finalize--> repository_dispatch "blog" to VIDEO_REPO (secret VIDEO_DISPATCH_TOKEN)
    video published --VIDEO_REPO--> repository_dispatch "video" here {topic, youtube} --> set_video(): frontmatter + redeploy

The other repo's name lives in the VIDEO_REPO repo variable, not in this public code.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess

import httpx

from . import gitops
from .settings import POSTS_DIR, ROOT, SITE_URL, env
from .telegram import Telegram, esc
from .topics import Tracker

log = logging.getLogger("tb.video")
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TOPIC = re.compile(r"^T\d{3,6}$")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def request_video(topic: dict) -> bool:
    """Ask the video pipeline to make this post's video. False (and nothing sent) when it isn't configured."""
    repo, token = env("VIDEO_REPO"), env("VIDEO_DISPATCH_TOKEN")
    if not (repo and token and topic.get("slug")):
        return False
    r = httpx.post(f"https://api.github.com/repos/{repo}/dispatches", timeout=30,
                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                   json={"event_type": "blog", "client_payload": {
                       "kind": "blog", "topic": topic["id"], "slug": topic["slug"], "title": topic.get("title", "")}})
    if r.status_code >= 300:
        log.warning("video request failed: HTTP %s", r.status_code)
        return False
    return True


def with_youtube(mdx: str, video_id: str) -> str:
    """Set (or replace) `youtube:` in the post's frontmatter; the rest of the file is untouched."""
    m = FRONTMATTER.match(mdx)
    if not m:
        raise ValueError("post has no frontmatter")
    lines = [l for l in m.group(1).split("\n") if not l.startswith("youtube:")]
    lines.append(f"youtube: {json.dumps(video_id)}")
    return "---\n" + "\n".join(lines) + "\n---\n" + mdx[m.end():]


def set_video(topic_id: str, video_id: str, tg: Telegram | None = None) -> bool:
    tg = tg or Telegram()
    topic_id = str(topic_id).upper()
    if not TOPIC.match(topic_id) or not YT_ID.match(str(video_id)):
        log.warning("bad video event")
        return False
    holder: dict = {}

    def mut(t: Tracker):
        topic = t.get(topic_id)
        f = POSTS_DIR / f"{(topic or {}).get('slug')}.mdx"
        if not topic or topic.get("status") != "published" or not f.exists():
            return
        f.write_text(with_youtube(f.read_text(), video_id))
        t.set(topic, youtube=video_id)
        holder.update(topic, path=str(f.relative_to(ROOT)))

    # extra_paths must name the file before we know it: add every post, only the edited one actually changes
    gitops.sync_tracker(mut, f"post: add video to {topic_id}", extra_paths=[str(POSTS_DIR)])
    if not holder:
        tg.send(f"⚠️ Video for {esc(topic_id)} arrived, but that post isn't published here. Add "
                f"<code>youtube: {esc(video_id)}</code> to its frontmatter by hand.")
        return False
    # pushes made with the workflow token don't start other workflows, so ask Pages to redeploy explicitly
    if gitops.has_remote():
        subprocess.run(["gh", "workflow", "run", "pages.yml", "--ref", "main"], cwd=ROOT, check=False, capture_output=True)
    tg.send(f"🎬 Video added to <b>{esc(holder.get('title', topic_id))}</b>\n"
            f"https://youtu.be/{video_id}\n{SITE_URL}/posts/{holder['slug']}/ (live in ~2 min)")
    return True
