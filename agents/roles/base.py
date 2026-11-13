"""Shared types and helpers for agent roles."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..llm import LLM

HOUSE_STYLE = """tinybrains.ai is an AI-engineering blog for practitioners ("AI engineering, in practice").
Voice: clear, concrete, opinionated where justified, zero hype, no filler, no "In today's fast-paced world".
Prefer working code, real numbers, trade-off tables and failure modes over generic advice.
Never invent benchmarks, quotes, versions, prices or citations. If unsure, say so or omit.
Audience levels: Beginner (explain terms), Practitioner (assume Python + LLM API basics), Expert (internals, papers, edge cases)."""

MDX_RULES = """Output format is MDX (Markdown + JSX) for an Astro site. Rules:
- Do NOT include frontmatter and do NOT repeat the title as an H1. Start with an intro paragraph; use ## and ### headings.
- Fenced code blocks must declare a language (```python, ```ts, ```bash ...); optional filename: ```python title="agent.py".
- Never write raw `<` or `{` / `}` in prose (MDX parses them as JSX/expressions). Write "less than", or put it in `inline code`.
- Available components (no imports needed), use sparingly where they genuinely help:
  <Callout type="tip" title="Optional title">markdown...</Callout>   (type: tip | warning | note)
  <PullQuote>One memorable sentence.</PullQuote>
  <Terminal lines={`$ command
output line`} />   (terminal session output; use the lines prop with a backtick string, never children)
  <Diagram src="diagrams/FILE.svg" caption="..." />  (only if a diagram file is provided to you)
- Tables in GitHub-flavoured Markdown. Links as [text](https://...)."""

COMPONENTS = {"Callout", "PullQuote", "Terminal", "Diagram"}


def slugify(s: str, maxlen: int = 70) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen].rstrip("-") or "post"


@dataclass
class Post:
    topic: dict[str, Any]                      # tracker entry
    team: str = ""                             # e.g. "team-2"
    context: str = ""                          # private source material (from uploads); never written to repo
    brief: dict[str, Any] = field(default_factory=dict)
    research: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)
    body: str = ""
    meta: dict[str, Any] = field(default_factory=dict)  # title, description, tldr, takeaways, tags, topic, level, type
    slug: str = ""
    cover_svg: str = ""
    diagrams: dict[str, str] = field(default_factory=dict)  # filename -> svg
    reviews: list[dict[str, Any]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    pr: int | None = None
    pr_url: str = ""

    def note(self, agent: str, msg: str) -> None:
        line = f"[{self.team}/{agent}] {msg}"
        self.log.append(line)
        logging.getLogger("tb.agents").info(line)


class Agent:
    role = "base"

    def __init__(self, llm: LLM, name: str | None = None):
        self.llm = llm
        self.name = name or self.role.capitalize()


def split_tagged(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.S)
    return m.group(1) if m else None
