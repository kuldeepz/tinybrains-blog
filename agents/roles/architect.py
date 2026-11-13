from __future__ import annotations

import json

from .base import PLAYBOOK, Agent, Post


class Architect(Agent):
    """Senior mode: the strongest model decides the *substance* of the post; cheaper models execute it."""
    role = "architect"

    async def plan(self, post: Post) -> None:
        user = f"""You are a principal AI/ML systems architect (15+ years, has run LLM systems in production at scale).
Write the ARCHITECT BRIEF for this post. A capable but less experienced writer model will turn it into the article,
so put all the senior judgement here: they can write, but they don't know what matters.

Post brief: {json.dumps(post.brief, ensure_ascii=False)}
Research notes (verified facts; flag anything you doubt): {post.research[:20000]}
Sources: {json.dumps(post.sources)}
Owner-provided material: {post.context[:12000] or '-'}

Produce markdown with exactly these sections:
## Thesis
One opinionated sentence the post argues, plus 2-3 sentences of justification.
## Non-obvious insights
4-7 bullets a staff engineer would not find in the docs; each with the mechanism behind it.
## Trade-off table
The comparison table to include (options x criteria that matter), filled in, with "choose when" guidance.
## Failure modes
3-6 entries: symptom -> root cause -> fix. At least one that only appears at scale/over time.
## Numbers
Back-of-envelope calculations with stated assumptions; mark each figure as SOURCED (from research) or ESTIMATE.
## What most teams get wrong
3-5 specific mistakes with the fix.
## Section plan
For each section: heading (stating the point) + the exact point it must land + what evidence/code goes there.
## Code
What the main code example must demonstrate, language, and production concerns it must show.
## Do not say
Claims, clichés or outdated advice the writer must avoid for this topic.

Follow this playbook:
{PLAYBOOK}"""
        post.architect_brief = await self.llm.chat(self.role, "You are a principal architect writing a brief for a writer.", user)
        post.note(self.name, f"architect brief ready ({len(post.architect_brief.split())} words)")
