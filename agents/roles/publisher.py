from __future__ import annotations

import asyncio

from .. import gitops
from ..settings import REPO, SITE_URL
from ..telegram import Telegram, esc
from .base import Agent, Post
from .tester import write_files

_lock = asyncio.Lock()  # git working tree is shared between parallel teams


class Publisher(Agent):
    role = "publisher"

    def __init__(self, llm, tg: Telegram, name: str | None = None, open_pr: bool = True):
        super().__init__(llm, name)
        self.tg = tg
        self.open_pr = open_pr

    async def publish(self, post: Post) -> None:
        async with _lock:
            paths = write_files(post)
            title = post.meta.get("title") or post.brief.get("title")
            if not self.open_pr:
                post.note(self.name, f"files written locally: {paths}")
                return
            review = post.review
            pr_body = (f"**{title}**\n\n{post.meta.get('tldr', '')}\n\n"
                       f"- Topic: {post.topic['id']} · {post.brief.get('topic')} / {post.brief.get('level')} / {post.brief.get('type')}\n"
                       f"- Review score: {review.get('score', '?')}/10\n"
                       f"- Will be live at: {SITE_URL}/posts/{post.slug}/\n\n"
                       "Approve from Telegram (or merge this PR) to publish.\n\n"
                       + (("<details><summary>Open reviewer notes</summary>\n\n"
                           + "\n".join(f"- {i}" for i in (review.get("required_changes") or review.get("issues") or [])[:12])
                           + "\n</details>\n\n") if review and not review.get("approved") else "")
                       + "<details><summary>Agent log</summary>\n\n" + "\n".join(f"- {l}" for l in post.log) + "\n</details>")
            pr, url = await asyncio.to_thread(gitops.publish_branch, post.slug, paths, title, pr_body)
            post.pr, post.pr_url = pr, url
        post.note(self.name, f"PR #{pr} opened")
        if pr:
            preview = f"https://github.com/{REPO}/blob/post/{post.slug}/site/src/content/posts/{post.slug}.mdx"
            self.tg.send(
                f"📝 <b>{esc(title)}</b>\n<i>{esc(post.topic['id'])} · {esc(post.brief.get('topic', ''))} · "
                f"{esc(post.brief.get('level', ''))} · {len(post.body.split())} words · review {review.get('score', '?')}/10</i>\n\n"
                f"{esc(post.meta.get('tldr', ''))}\n\n<a href=\"{preview}\">Read draft</a> · <a href=\"{url}\">PR #{pr}</a>",
                buttons=[[{"text": "✅ Approve & publish", "callback_data": f"approve:{pr}"},
                          {"text": "❌ Reject", "callback_data": f"reject:{pr}"}]],
            )
