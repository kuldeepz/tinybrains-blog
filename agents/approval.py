"""Ask the owner in Telegram before spending money on paid models.

Flow: free models fail -> Telegram message with [Approve paid] [No] buttons -> the Cloudflare Worker
stores the answer in KV -> this run polls the Worker for it. One answer covers the whole run.
Auth for polling: header X-Approval-Auth = sha256(TELEGRAM_BOT_TOKEN + ":" + key) (both sides know the token).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time

import httpx

from .settings import env
from .telegram import Telegram, esc

log = logging.getLogger("tb.approval")


def auth_for(key: str) -> str:
    return hashlib.sha256(f"{env('TELEGRAM_BOT_TOKEN', '')}:{key}".encode()).hexdigest()


class Approver:
    def __init__(self, tg: Telegram | None = None):
        self.tg = tg or Telegram()
        self.url = (env("TB_BOT_URL") or "").rstrip("/")
        self.key = f"run-{env('GITHUB_RUN_ID') or os.getpid()}-{int(time.time())}"
        self.timeout = int(env("TB_APPROVAL_TIMEOUT", "1800"))
        self.decision: bool | None = None
        self._lock = asyncio.Lock()
        if env("TB_PAID_APPROVED") == "1":      # explicit pre-approval (manual runs)
            self.decision = True

    async def allow_paid(self, role: str, model: str, reason: str) -> bool:
        if self.decision is not None:
            return self.decision
        async with self._lock:                  # parallel teams share one question
            if self.decision is not None:
                return self.decision
            if not (self.tg.enabled and self.url):
                log.warning("paid fallback needed for %s but approval channel not configured -> denied", role)
                self.decision = False
                return False
            self.tg.send(
                f"💸 <b>Free models failed</b> for <i>{esc(role)}</i> ({esc(reason[:160])}).\n"
                f"Use paid models for the rest of this run? (e.g. <code>{esc(model)}</code>, typically under $1 per post)\n"
                f"No answer in {self.timeout // 60} min = No.",
                buttons=[[{"text": "✅ Approve paid", "callback_data": f"paid:{self.key}:yes"},
                          {"text": "❌ No, stop", "callback_data": f"paid:{self.key}:no"}]],
            )
            self.decision = await self._wait()
            self.tg.send("✅ Paid models approved for this run." if self.decision else "⏹ Paid models not approved; stopping affected posts.")
            return self.decision

    async def _wait(self) -> bool:
        deadline = time.monotonic() + self.timeout
        async with httpx.AsyncClient(timeout=20) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(f"{self.url}/approval/{self.key}", headers={"X-Approval-Auth": auth_for(self.key)})
                    if r.status_code == 200 and r.text.strip() in ("yes", "no"):
                        return r.text.strip() == "yes"
                except httpx.HTTPError as e:
                    log.warning("approval poll error: %s", type(e).__name__)
                await asyncio.sleep(10)
        return False
