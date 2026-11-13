from __future__ import annotations

import json
import re

from .base import HOUSE_STYLE, MDX_RULES, Agent, Post


class Researcher(Agent):
    """Gathers current facts with web search (OpenRouter web plugin) and returns notes + sources."""
    role = "researcher"

    async def research(self, post: Post) -> None:
        user = f"""Research for a blog post.
Brief: {json.dumps(post.brief, ensure_ascii=False)}
Owner-provided material (may be partial): {post.context[:15000] or '-'}

Find the most recent, authoritative information (official docs, papers, release notes, reputable engineering blogs).
Return JSON: {{"notes": "dense factual research notes in markdown with versions/dates/numbers, flag anything uncertain",
"sources": [{{"title": "...", "url": "https://..."}}] (only URLs you actually found, 3-10)}}"""
        r = await self.llm.json(self.role, "You are a meticulous technical researcher. Accuracy over volume.", user)
        post.research = r.get("notes", "")
        post.sources = [s for s in r.get("sources", []) if isinstance(s, dict) and str(s.get("url", "")).startswith("http")][:10]
        post.note(self.name, f"research done, {len(post.sources)} sources")


class Writer(Agent):
    role = "writer"

    async def write(self, post: Post) -> None:
        user = f"""Write the full post.
Brief: {json.dumps(post.brief, ensure_ascii=False)}
Research notes:
{post.research[:20000]}
Sources (cite inline as links where relevant): {json.dumps(post.sources)}
Owner-provided material: {post.context[:15000] or '-'}

{MDX_RULES}
Hit roughly {post.brief.get('target_words', 1800)} words. Return ONLY the MDX body."""
        body = await self.llm.chat(self.role, f"You are a senior AI engineer who writes for tinybrains.ai.\n{HOUSE_STYLE}", user)
        post.body = strip_fences(body)
        post.note(self.name, f"draft written ({len(post.body.split())} words)")


def strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:mdx|markdown|md)?\s*\n(.*)\n```\s*$", t, re.S)
    t = m.group(1) if m else t
    t = re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S)  # drop accidental frontmatter
    t = re.sub(r"^# .*\n+", "", t)                         # drop accidental H1
    return t.strip() + "\n"
