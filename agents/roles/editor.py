from __future__ import annotations

import json

from .base import HOUSE_STYLE, MDX_RULES, PLAYBOOK, Agent, Post, split_tagged
from .writer import strip_fences


class Editor(Agent):
    role = "editor"

    async def edit(self, post: Post, feedback: list[str] | None = None, role: str | None = None) -> None:
        fb = "\n".join(f"- {f}" for f in feedback) if feedback else ""
        task = (f"""Revise the draft to fix these review issues:
{fb}

How to revise (playbook section 9 applies):
- Change only what the issues require; keep everything that works. Do not rewrite sections nobody complained about.
- Fix a challenged claim by correcting it against the research notes, or delete it. Do NOT add disclaimers or hedges.
- If an issue asks for something the research notes cannot support (a benchmark, a tested version, a real measurement),
  remove the claim instead of inventing support. Never write that anything was tested or measured.
- Never mention the review, the revision, the brief or "this post" in the body, title, description, tldr or takeaways.
- Stay within 1,500-3,000 words and keep the main code example under ~90 lines; cut to make room.""" if fb
                else "Edit the draft to the playbook's senior bar: enforce every non-negotiable ingredient, cut filler and banned "
                     "phrases, make headings state the point, verify code is correct and runnable, keep and sharpen technical depth.")
        if post.architect_brief and not fb:
            task += f"\nThe draft must deliver everything in this architect brief:\n{post.architect_brief[:12000]}"
        elif post.architect_brief:
            task += f"\nKeep the architect brief's thesis and judgement (for reference, do not expand toward it):\n{post.architect_brief[:4000]}"
        user = f"""{task}

Brief: {json.dumps(post.brief, ensure_ascii=False)}
Sources: {json.dumps(post.sources)}
{f"Research notes (the only ground truth for facts, versions and numbers):{chr(10)}{post.research[:15000]}" if fb else ""}

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
        out = await self.llm.chat(role or self.role, f"You are the senior editor of tinybrains.ai.\n{HOUSE_STYLE}\n\n# Writing playbook\n{PLAYBOOK}", user)
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
