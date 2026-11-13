"""Inbound processing: free-text routing and file uploads (stored privately on Drive)."""
from __future__ import annotations

import base64
import io
import logging
import mimetypes
from typing import Any

from .drive import Drive
from .llm import LLM
from .telegram import Telegram

log = logging.getLogger("tb.intake")
TEXT_EXT = (".txt", ".md", ".mdx", ".csv", ".json", ".py", ".ts", ".js", ".yaml", ".yml", ".html", ".log", ".ipynb")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")

ROUTER_SYSTEM = """You route messages sent to the tinybrains.ai blog bot by its owner.
Intents:
- store_idea: owner wants to save/park/remember an idea for later (words like store, save, note, later, idea, park). NEVER write.
- write_now: owner explicitly wants a post written/published now.
- status: asks what's covered, pending, progress.
- chat: anything else (question, feedback).
If ambiguous between store and write, choose store_idea.
Return JSON: {"intent": "...", "topics": [{"title": "short working title", "notes": "details from message"}], "reply": "one-line acknowledgement"}"""


async def route(llm: LLM, text: str) -> dict[str, Any]:
    r = await llm.json("router", ROUTER_SYSTEM, text)
    if r.get("intent") not in ("store_idea", "write_now", "status", "chat"):
        r["intent"] = "chat"
    r["topics"] = [t for t in r.get("topics", []) if isinstance(t, dict) and t.get("title")][:10]
    return r


async def describe(llm: LLM, name: str, data: bytes, mime: str) -> str:
    """Extract text from an upload (text, PDF, image via vision model)."""
    lower = name.lower()
    if lower.endswith(TEXT_EXT) or mime.startswith("text/"):
        return data.decode("utf-8", errors="replace")[:60000]
    if lower.endswith(".pdf") or mime == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:60])[:60000]
    if lower.endswith(IMG_EXT) or mime.startswith("image/"):
        b64 = base64.b64encode(data).decode()
        content = [{"type": "text", "text": "Describe this image in detail for a technical blog writer: all visible text, "
                                            "numbers, chart data, code, product names, and what it shows. Do not identify people."},
                   {"type": "image_url", "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}}]
        return await llm.chat("vision", "You extract information from images precisely.", content)
    return ""


async def summarize_upload(llm: LLM, text: str, caption: str) -> dict[str, Any]:
    return await llm.json("pm", "You turn source material into a blog idea for tinybrains.ai (AI engineering blog).",
                          f"Owner caption: {caption or '-'}\nMaterial:\n{text[:20000]}\n\n"
                          'Return JSON: {"title": "working title for a post based on this", "notes": "2-3 sentence angle (no personal details)", "tags": ["..."]}')


async def load_private_context(drive: Drive, llm: LLM, topic: dict) -> str:
    """Pull a topic's uploads back from Drive as text for the writing team."""
    import asyncio
    if not drive.enabled:
        return ""
    parts = []
    for f in await asyncio.to_thread(drive.list, f"uploads/{topic['id']}"):
        try:
            data = await asyncio.to_thread(drive.download, f["id"])
            mime = f.get("mimeType") or mimetypes.guess_type(f["name"])[0] or ""
            parts.append(f"### {f['name']}\n" + await describe(llm, f["name"], data, mime))
        except Exception as e:  # noqa: BLE001
            log.warning("could not read upload: %s", type(e).__name__)
    return "\n\n".join(parts)[:60000]


def notify_unsupported(tg: Telegram, name: str) -> None:
    tg.send(f"I can't read that file type yet ({name}). Send text, markdown, PDF, code or an image.")
