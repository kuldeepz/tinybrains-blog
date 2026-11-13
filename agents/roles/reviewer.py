from __future__ import annotations

import json

from .base import HOUSE_STYLE, Agent, Post


class Reviewer(Agent):
    """Independent quality gate (configured to use a different model family than the writer)."""
    role = "reviewer"

    async def review(self, post: Post) -> dict:
        user = f"""Review this post for publication on tinybrains.ai.
Brief: {json.dumps(post.brief, ensure_ascii=False)}
Research notes (ground truth to check against): {post.research[:12000]}
Sources: {json.dumps(post.sources)}
Meta: {json.dumps(post.meta, ensure_ascii=False)}

<post>
{post.body}
</post>

Check: technical accuracy (flag anything not supported by notes/sources or likely outdated), code correctness,
originality/insight, structure vs brief, level-appropriateness, hype/filler, missing caveats, MDX hazards.
Return JSON: {{"approved": bool, "score": 1-10, "issues": ["..."], "required_changes": ["specific actionable fixes"]}}
Approve only if score >= 8 and there are no factual errors."""
        r = await self.llm.json(self.role, f"You are a demanding technical reviewer.\n{HOUSE_STYLE}", user)
        r["approved"] = bool(r.get("approved")) and int(r.get("score") or 0) >= 8
        post.reviews.append(r)
        post.note(self.name, f"score {r.get('score')}/10 -> {'APPROVED' if r['approved'] else 'changes requested'}")
        return r
