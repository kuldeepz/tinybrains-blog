"""Minimal Telegram Bot API client (outbound only; inbound arrives via the Cloudflare Worker)."""
from __future__ import annotations

import html
import logging
from typing import Any

import httpx

from .settings import env

log = logging.getLogger("tb.telegram")
API = "https://api.telegram.org"


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


class Telegram:
    def __init__(self, chat_id: str | int | None = None):
        self.token = env("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or env("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.token and self.chat_id)
        self.on_send = None  # optional callback(text) e.g. to log replies to private Drive

    def _post(self, method: str, **payload: Any) -> dict[str, Any] | None:
        if not self.enabled:
            log.info("[telegram disabled] %s", method)
            return None
        try:
            r = httpx.post(f"{API}/bot{self.token}/{method}", json=payload, timeout=30)
            data = r.json()
            if not data.get("ok"):
                log.warning("telegram %s failed: %s", method, data.get("description"))
            return data
        except httpx.HTTPError as e:
            log.warning("telegram %s error: %s", method, type(e).__name__)
            return None

    def send(self, text: str, *, buttons: list[list[dict[str, str]]] | None = None, reply_to: int | None = None) -> None:
        """text is HTML (escape user content with esc()). Splits >4000 chars."""
        if self.on_send:
            self.on_send(text)
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML",
                                       "disable_web_page_preview": True}
            if reply_to and i == 0:
                payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
            if buttons and i == len(chunks) - 1:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            self._post("sendMessage", **payload)

    def typing(self) -> None:
        self._post("sendChatAction", chat_id=self.chat_id, action="typing")

    def download(self, file_id: str) -> tuple[bytes, str]:
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        info = httpx.get(f"{API}/bot{self.token}/getFile", params={"file_id": file_id}, timeout=30).json()
        if not info.get("ok"):
            raise RuntimeError(f"getFile failed: {info.get('description')}")
        path = info["result"]["file_path"]
        data = httpx.get(f"{API}/file/bot{self.token}/{path}", timeout=120).content
        return data, path.rsplit("/", 1)[-1]
