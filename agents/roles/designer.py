from __future__ import annotations

import hashlib
import html
import math
import textwrap
import xml.etree.ElementTree as ET

from .base import MDX_RULES, Agent, Post, split_tagged
from .writer import strip_fences


class Designer(Agent):
    """Layout pass (callouts, pull quote, terminal blocks, one diagram) + generated cover art."""
    role = "designer"

    async def design(self, post: Post) -> None:
        user = f"""You are the designer for tinybrains.ai (dark UI, violet #7C5CFF to cyan #22D3EE accents, Geist font).
Improve the reading experience of this post WITHOUT changing its meaning or removing content:
- add at most 3 Callouts and at most 1 PullQuote where they genuinely help scanning,
- convert shell output examples into <Terminal> blocks,
- optionally design ONE explanatory diagram as an SVG (viewBox width 800, dark background #0B0C10,
  strokes/text in #E6E8EE / #7C5CFF / #22D3EE, font-family "Geist, ui-sans-serif, sans-serif", no external refs,
  no scripts) and reference it as <Diagram src="diagrams/{post.slug}-1.svg" caption="..." />.

{MDX_RULES}

Post:
<draft>
{post.body}
</draft>

Return:
<body>...full MDX body...</body>
<diagram>...svg markup or empty...</diagram>"""
        out = await self.llm.chat(self.role, "You are a meticulous editorial designer.", user)
        body = split_tagged(out, "body")
        svg = (split_tagged(out, "diagram") or "").strip()
        name = f"{post.slug}-1.svg"
        if svg and valid_svg(svg):
            post.diagrams[name] = svg
        if body:
            post.body = strip_fences(body)
        if name not in post.diagrams:  # diagram missing/invalid -> remove reference
            post.body = "\n".join(l for l in post.body.splitlines() if f"diagrams/{name}" not in l) + "\n"
        post.cover_svg = cover_svg(post.meta.get("title") or post.brief.get("title", ""), post.brief.get("topic", ""), post.slug)
        post.note(self.name, f"layout pass done, cover generated, {len(post.diagrams)} diagram(s)")


def valid_svg(svg: str) -> bool:
    if "<script" in svg.lower() or "href=\"http" in svg or len(svg) > 200_000:
        return False
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return False
    return root.tag.endswith("svg")


def cover_svg(title: str, topic: str, seed: str) -> str:
    """Deterministic 1200x630 'attention grid' cover in the site's style."""
    h = hashlib.sha256(seed.encode()).digest()
    cells = []
    cols, rows, size, gap = 16, 9, 26, 10
    x0, y0 = 1200 - cols * (size + gap) - 40, 70
    for r in range(rows):
        for c in range(cols):
            b = h[(r * cols + c) % len(h)]
            d = math.hypot(c - (h[0] % cols), r - (h[1] % rows))
            o = max(0.06, min(0.95, (b / 255) * 0.5 + 0.5 / (1 + d * 0.6)))
            fill = "url(#g)" if o > 0.55 else "#7C5CFF"
            cells.append(f'<rect x="{x0 + c * (size + gap)}" y="{y0 + r * (size + gap)}" width="{size}" height="{size}" '
                         f'rx="6" fill="{fill}" opacity="{o:.2f}"/>')
    lines = textwrap.wrap(title, 26)[:4]
    text = "".join(f'<text x="64" y="{250 + i * 62}" font-size="52" font-weight="700" fill="#F4F5F8">{html.escape(l)}</text>'
                   for i, l in enumerate(lines))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630" font-family="Geist, ui-sans-serif, system-ui, sans-serif">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7C5CFF"/><stop offset="1" stop-color="#22D3EE"/></linearGradient>
<radialGradient id="bg" cx="0.8" cy="0.2" r="1"><stop offset="0" stop-color="#151230"/><stop offset="1" stop-color="#030304"/></radialGradient></defs>
<rect width="1200" height="630" fill="url(#bg)"/>
<g opacity="0.55">{''.join(cells)}</g>
<rect x="0" y="0" width="760" height="630" fill="#030304" opacity="0.55"/>
<text x="64" y="120" font-family="Geist Mono, ui-monospace, monospace" font-size="22" fill="#22D3EE" letter-spacing="3">// {html.escape(topic.upper() or 'AI ENGINEERING')}</text>
{text}
<text x="64" y="570" font-family="Geist Mono, ui-monospace, monospace" font-size="22" fill="#8B92A3">tinybrains.ai</text>
<rect x="64" y="590" width="120" height="4" rx="2" fill="url(#g)"/>
</svg>
"""


