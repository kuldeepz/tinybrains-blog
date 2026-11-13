from __future__ import annotations

import json

from .base import HOUSE_STYLE, MDX_RULES, Agent, Post, split_tagged
from .writer import strip_fences


class Editor(Agent):
    role = "editor"

    async def edit(self, post: Post, feedback: list[str] | None = None) -> None:
        fb = "\n".join(f"- {f}" for f in feedback) if feedback else ""
        task = (f"Revise the draft to fix ALL of these review issues:\n{fb}" if fb
                else "Edit the draft: tighten prose, fix structure/flow, verify code is correct and runnable, "
                     "ensure headings follow the outline, remove fluff and hype, keep technical depth.")
        user = f"""{task}

Brief: {json.dumps(post.brief, ensure_ascii=False)}
Sources: {json.dumps(post.sources)}

{MDX_RULES}

Draft:
<draft>
{post.body}
</draft>

Return exactly two tagged blocks:
<meta>{{"title": "...", "description": "1-2 sentence SEO description (max 160 chars)",
"tldr": "3-4 sentence summary", "takeaways": ["3-5 crisp takeaways"], "tags": ["lowercase", "tags"]}}</meta>
<body>
...full revised MDX body...
</body>"""
        out = await self.llm.chat(self.role, f"You are the senior editor of tinybrains.ai.\n{HOUSE_STYLE}", user)
        body = split_tagged(out, "body")
        meta_raw = split_tagged(out, "meta")
        if body:
            post.body = strip_fences(body)
        if meta_raw:
            try:
                meta = json.loads(meta_raw)
                post.meta.update({k: v for k, v in meta.items() if v})
            except json.JSONDecodeError:
                post.note(self.name, "meta block unparsable; keeping previous meta")
        post.note(self.name, "revised per review" if fb else "edit pass done")
