from __future__ import annotations


from .base import HOUSE_STYLE, Agent, Post


class Head(Agent):
    """Editor-in-chief: splits requests into topics, sizes the team, reports results."""
    role = "head"

    async def split(self, text: str) -> list[dict]:
        r = await self.llm.json(self.role, f"You are the editor-in-chief of tinybrains.ai.\n{HOUSE_STYLE}", f"""
The owner sent this request. Split it into distinct blog topics (one post each). Do not invent extra topics.
Request: {text}
Return JSON: {{"topics": [{{"title": "short working title", "notes": "any specific instructions for this topic"}}]}}""")
        return [t for t in r.get("topics", []) if t.get("title")][:10]

    @staticmethod
    def team_plan(n: int, max_parallel: int) -> str:
        if n == 1:
            return "1 topic → lean team: PM → Researcher → Writer → Editor → Designer → Reviewer → Tester → Publisher"
        return (f"{n} topics → {n} parallel teams (max {max_parallel} at once), each with its own "
                f"PM/Researcher/Writer/Editor/Designer/Reviewer; shared Tester build + Publisher")

    async def chat(self, text: str, status: str) -> str:
        return await self.llm.chat(self.role, f"You are the friendly editor-in-chief bot of tinybrains.ai. Be brief (max 5 sentences).\n{HOUSE_STYLE}",
                                   f"Current tracker:\n{status}\n\nOwner says: {text}")

    @staticmethod
    def summary(posts: list[Post]) -> str:
        ok = [p for p in posts if p.ok]
        bad = [p for p in posts if not p.ok]
        lines = [f"🏁 Run finished: {len(ok)} ready for review, {len(bad)} failed"]
        lines += [f"✅ {p.topic['id']} {p.meta.get('title') or p.brief.get('title')}" + (f" (PR #{p.pr})" if p.pr else "") for p in ok]
        lines += [f"⚠️ {p.topic['id']} {p.topic['title']}: {p.error[:200]}" for p in bad]
        return "\n".join(lines)


