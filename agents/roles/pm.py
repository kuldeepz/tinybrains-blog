from __future__ import annotations

import json

from .base import HOUSE_STYLE, Agent, Post, slugify

TOPICS = ["LLMs", "Agents", "RAG", "MLOps", "Evals", "Infra", "Research", "Tools"]


class PM(Agent):
    """Turns a raw topic/idea into a concrete brief, avoiding overlap with published posts."""
    role = "pm"

    async def plan(self, post: Post, published: list[dict]) -> None:
        pub = "\n".join(f"- {p['title']} ({p.get('url') or p.get('slug')})" for p in published[-60:]) or "(none yet)"
        user = f"""Topic request: {post.topic['title']}
Owner notes: {post.topic.get('notes') or '-'}
Private source material provided by the owner (summarise/use, do not quote personal details):
{post.context[:12000] or '-'}

Already published on the blog (avoid overlap; pick a distinct angle and suggest internal links):
{pub}

Return JSON: {{
 "title": "specific, non-clickbait headline (max 80 chars)",
 "angle": "what makes this post distinct and useful",
 "topic": one of {json.dumps(TOPICS)},
 "level": "Beginner" | "Practitioner" | "Expert",
 "type": "Article" | "Tutorial" | "Deep dive",
 "audience": "who it's for",
 "outline": ["## section heading - what it covers", ...] (5-9 items),
 "must_cover": ["key facts/points"],
 "research_questions": ["questions the researcher must answer with current sources"],
 "code_examples": ["what runnable examples to include, language"],
 "target_words": 1200-3000,
 "tags": ["3-6 lowercase tags"],
 "internal_links": ["titles of published posts worth linking"]
}}"""
        b = await self.llm.json(self.role, f"You are the PM/managing editor of tinybrains.ai.\n{HOUSE_STYLE}", user)
        if b.get("topic") not in TOPICS:
            b["topic"] = "LLMs"
        if b.get("level") not in ("Beginner", "Practitioner", "Expert"):
            b["level"] = "Practitioner"
        if b.get("type") not in ("Article", "Tutorial", "Deep dive"):
            b["type"] = "Article"
        b["title"] = (b.get("title") or post.topic["title"]).strip()
        post.brief = b
        post.slug = slugify(b["title"])
        post.note(self.name, f"brief ready: '{b['title']}' [{b['topic']}/{b['level']}/{b['type']}]")
