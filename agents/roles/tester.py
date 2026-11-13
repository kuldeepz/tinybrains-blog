from __future__ import annotations

import asyncio
import re
from datetime import date

import yaml

from ..settings import AUTHOR, COVERS_DIR, POSTS_DIR, SITE
from .base import COMPONENTS, MDX_RULES, Agent, Post
from .writer import strip_fences

HTML_OK = {"br", "sup", "sub", "kbd", "details", "summary", "img", "a", "em", "strong", "code", "span", "div", "p", "ul", "li", "ol"}
PROTECT = re.compile(
    r"(```.*?```"                                  # fenced code
    r"|<Terminal\b[^>]*?lines=\{`.*?`\}[^>]*?/>"     # <Terminal lines={`...`} />
    r"|<Terminal\b[^>]*>.*?</Terminal>"            # terminal blocks with children
    r"|<(?:Callout|PullQuote|Diagram|Terminal)\b[^>]*>"  # component tags
    r"|</(?:Callout|PullQuote|Diagram)>"
    r"|`[^`\n]+`"                                  # inline code
    r"|\[[^\]]*\]\([^)]*\))",                      # links
    re.S,
)


def sanitize_mdx(body: str) -> str:
    """Escape MDX hazards in prose (raw <, {, }) while leaving code and components intact."""
    out, last = [], 0
    for m in PROTECT.finditer(body):
        out.append(_escape(body[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_escape(body[last:]))
    return "".join(out)


def _escape(text: str) -> str:
    text = re.sub(r"(?<!\\)([{}])", r"\\\1", text)  # idempotent: skip already-escaped braces

    def lt(m: re.Match) -> str:
        tag = m.group(1)
        if tag and (tag in COMPONENTS or tag.lower() in HTML_OK):
            return m.group(0)
        return "&lt;" + m.group(0)[1:]
    return re.sub(r"</?([A-Za-z][\w-]*)?", lt, text)


def check_post(post: Post) -> list[str]:
    problems = []
    m = post.meta
    for k in ("title", "description", "tldr"):
        if not str(m.get(k) or "").strip():
            problems.append(f"missing {k}")
    if len(post.body.split()) < 400:
        problems.append("body too short (<400 words)")
    for comp in re.findall(r"<([A-Z]\w*)", post.body):
        if comp not in COMPONENTS:
            problems.append(f"unknown component <{comp}>")
    for f in re.findall(r'Diagram src="diagrams/([^"]+)"', post.body):
        if f not in post.diagrams:
            problems.append(f"diagram {f} referenced but missing")
    if post.body.count("```") % 2:
        problems.append("unbalanced code fences")
    return problems


META_TALK = re.compile(
    r"\b(this (revised )?(post|article|piece|draft)|revised (post|version|draft)|the reviewer|review(er)? (feedback|notes)|"
    r"architect brief|as requested|tested combinations?|we (tested|benchmarked|measured)|in our (tests|benchmarks))\b",
    re.I)


def style_issues(post: Post) -> list[str]:
    """Deterministic checks for the failure modes of LLM revisions. Advisory: fed to the reviser, never blocks publishing."""
    issues = []
    words = len(post.body.split())
    if words > 3300:
        issues.append(f"post is {words} words; cut to under 3,000 by removing the weakest material, not by summarising everything")
    for block in re.findall(r"```[^\n]*\n(.*?)```", post.body, re.S):
        n = block.count("\n")
        if n > 120:
            issues.append(f"a code block is {n} lines; cut it to under ~90 lines that teach the point (drop CLI/option plumbing)")
    texts = [post.body] + [str(post.meta.get(k, "")) for k in ("title", "description", "tldr")] + [str(t) for t in post.meta.get("takeaways") or []]
    for hit in sorted({m.group(0).lower() for t in texts for m in META_TALK.finditer(t)}):
        issues.append(f'remove drafting/meta talk or unverifiable testing claim: "{hit}"')
    return issues


def frontmatter(post: Post) -> str:
    b, m = post.brief, post.meta
    fm = {
        "title": m.get("title") or b.get("title"),
        "description": (m.get("description") or "")[:200],
        "date": date.today(),
        "topic": b.get("topic", "LLMs"),
        "level": b.get("level", "Practitioner"),
        "type": b.get("type", "Article"),
        "tags": [str(t).lower() for t in (m.get("tags") or b.get("tags") or [])][:8],
        "tldr": m.get("tldr", ""),
        "takeaways": [str(t) for t in (m.get("takeaways") or [])][:6],
        "cover": f"covers/{post.slug}.svg",
        "sources": post.sources,
        "author": AUTHOR,
        "draft": False,
        "version": 1,
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000) + "---\n\n"


def render(post: Post) -> str:
    return frontmatter(post) + post.body


def write_files(post: Post) -> list[str]:
    """Write the post into the site tree; returns repo-relative paths."""
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    p = POSTS_DIR / f"{post.slug}.mdx"
    p.write_text(render(post))
    paths.append(p)
    c = COVERS_DIR / f"{post.slug}.svg"
    c.write_text(post.cover_svg)
    paths.append(c)
    if post.diagrams:
        d = SITE / "public" / "diagrams"
        d.mkdir(parents=True, exist_ok=True)
        for name, svg in post.diagrams.items():
            (d / name).write_text(svg)
            paths.append(d / name)
    root = SITE.parent
    return [str(x.relative_to(root)) for x in paths]


def remove_files(post: Post) -> None:
    for x in [POSTS_DIR / f"{post.slug}.mdx", COVERS_DIR / f"{post.slug}.svg",
              *[SITE / "public" / "diagrams" / n for n in post.diagrams]]:
        x.unlink(missing_ok=True)


async def build_site() -> tuple[bool, str]:
    if not (SITE / "node_modules").exists():
        p = await asyncio.create_subprocess_exec("npm", "ci", cwd=SITE, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT)
        await p.communicate()
    p = await asyncio.create_subprocess_exec("npm", "run", "build", cwd=SITE, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    return p.returncode == 0, out.decode(errors="replace")[-6000:]


class Tester(Agent):
    role = "tester"

    async def static(self, post: Post) -> list[str]:
        post.body = sanitize_mdx(post.body)
        problems = check_post(post)
        post.note(self.name, "static checks passed" if not problems else f"static issues: {problems}")
        return problems

    async def fix_build(self, post: Post, error: str) -> None:
        user = f"""The Astro/MDX build failed on this post. Fix ONLY what breaks the build; keep content otherwise identical.
Build output (tail):
{error}

{MDX_RULES}

<body>
{post.body}
</body>
Return the fixed MDX body inside <body></body>."""
        out = await self.llm.chat(self.role, "You fix MDX syntax errors precisely.", user)
        m = re.search(r"<body>\s*(.*?)\s*</body>", out, re.S)
        if m:
            post.body = sanitize_mdx(strip_fences(m.group(1)))
        post.note(self.name, "attempted build fix")
