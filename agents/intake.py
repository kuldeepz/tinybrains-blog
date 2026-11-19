"""Inbound processing: free-text routing and file uploads.

Uploads are never stored by us: Telegram keeps the file, the tracker keeps only its opaque file id (useless without
the bot token), and each run downloads it into memory, uses it and lets it vanish with the throwaway runner."""
from __future__ import annotations

import base64
import io
import logging
import mimetypes
from typing import Any

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


def file_ref(file_id: str, name: str, mime: str) -> dict[str, str]:
    """What the (public) tracker keeps for an upload: Telegram's file id, type and extension. No file name."""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    return {"id": file_id, "mime": mime or mimetypes.guess_type(name)[0] or "", "ext": ext[:8]}


async def load_private_context(tg: Telegram, llm: LLM, topic: dict) -> tuple[str, int]:
    """Re-download a topic's uploads from Telegram into memory and turn them into text. Returns (text, files_failed)."""
    import asyncio
    parts, failed = [], 0
    for n, f in enumerate(topic.get("files") or [], 1):
        try:
            data, _ = await asyncio.to_thread(tg.download, f["id"])
            parts.append(f"### Attachment {n}\n" + await describe(llm, f"upload{f.get('ext', '')}", data, f.get("mime", "")))
        except Exception as e:  # noqa: BLE001
            failed += 1
            log.warning("could not read upload %d: %s", n, type(e).__name__)
    return "\n\n".join(parts)[:60000], failed


def notify_unsupported(tg: Telegram, name: str) -> None:
    tg.send(f"I can't read that file type yet ({name}). Send text, markdown, PDF, code or an image.")
