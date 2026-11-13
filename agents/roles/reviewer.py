from __future__ import annotations

import json

import os

from .base import HOUSE_STYLE, PLAYBOOK, Agent, Post


MIN_SCORE = int(os.environ.get("TB_REVIEW_MIN", "9"))


class Reviewer(Agent):
    """Independent quality gate (configured to use a different model family than the writer)."""
    role = "reviewer"

    async def review(self, post: Post) -> dict:
        arch = f"Architect brief the post must deliver:\n{post.architect_brief[:10000]}" if post.architect_brief else ""
        user = f"""Review this post for publication on tinybrains.ai.
Brief: {json.dumps(post.brief, ensure_ascii=False)}
Research notes (ground truth to check against): {post.research[:12000]}
Sources: {json.dumps(post.sources)}
Meta: {json.dumps(post.meta, ensure_ascii=False)}

<post>
{post.body}
</post>

{arch}

Review it as a skeptical principal engineer using the playbook's rubric (section 8). Check technical accuracy against the
notes/sources (flag anything unsupported, invented or outdated), code correctness, insight, trade-offs, failure modes,
actionability, voice (banned phrases, filler), structure, level-appropriateness and MDX hazards.
Return JSON: {{"approved": bool, "score": 1-10, "rubric": {{"insight": n, "correctness": n, "tradeoffs": n,
"actionability": n, "voice": n, "structure": n, "code": n}}, "issues": ["..."],
"required_changes": ["specific actionable fixes, quoting the passage to change"]}}
Approve only if score >= {MIN_SCORE} and there are no factual errors."""
        r = await self.llm.json(self.role, f"You are a demanding principal-engineer reviewer.\n{HOUSE_STYLE}\n\n# Playbook\n{PLAYBOOK}", user)
        try:
            score = int(float(r.get("score") or 0))
        except (TypeError, ValueError):
            score = 0
        r["score"] = score
        r["approved"] = bool(r.get("approved")) and score >= MIN_SCORE
        post.reviews.append(r)
        post.note(self.name, f"score {r.get('score')}/10 -> {'APPROVED' if r['approved'] else 'changes requested'}")
        return r
