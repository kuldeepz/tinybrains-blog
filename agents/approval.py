"""Owner approval for paid (Azure) model use, via Telegram buttons.

1) choose_mode(): at the start of every /write the owner picks
     🏛 Senior  - architect brief + Azure mini writer + strongest Azure reviewer (playbook)
     💡 Mini    - Azure mini writer following the playbook, free reviewer
     🆓 Free    - OpenRouter free models only
   No answer within TB_APPROVAL_TIMEOUT -> Free.
2) allow_paid(): in Free mode, if free models fail, ask once more before touching Azure.

The Cloudflare Worker stores button presses in KV; this run polls GET {TB_BOT_URL}/approval/<key>.
Auth: header X-Approval-Auth = sha256(TELEGRAM_BOT_TOKEN + ":" + key).
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
MODES = ("senior", "mini", "free")
EST_PER_POST = {"senior": "≈ $0.20–0.60", "mini": "≈ $0.05–0.20", "free": "$0 (+ ≈$0.02 web search)"}


def auth_for(key: str) -> str:
    return hashlib.sha256(f"{env('TELEGRAM_BOT_TOKEN', '')}:{key}".encode()).hexdigest()


class Approver:
    def __init__(self, tg: Telegram | None = None):
        self.tg = tg or Telegram()
        self.url = (env("TB_BOT_URL") or "").rstrip("/")
        self.base_key = f"run-{env('GITHUB_RUN_ID') or os.getpid()}-{int(time.time())}"
        self.timeout = int(env("TB_APPROVAL_TIMEOUT", "1800"))
        self.mode: str | None = (env("TB_MODE") or "").lower() or None   # preset for manual runs
        self.decision: bool | None = True if env("TB_PAID_APPROVED") == "1" else None
        self._lock = asyncio.Lock()

    @property
    def channel_ok(self) -> bool:
        return bool(self.tg.enabled and self.url)

    async def choose_mode(self, titles: list[str], azure_ready: bool) -> str:
        if self.mode in MODES:
            return self.mode
        if not azure_ready:
            self.mode = "free"
            self.tg.send("ℹ️ Paid models aren't configured yet, so this run uses 🆓 free models only.")
            return self.mode
        if not self.channel_ok:
            self.mode = "free"
            return self.mode
        key = f"{self.base_key}-mode"
        n = len(titles)
        lines = "\n".join(f"• {esc(t)}" for t in titles[:10])
        self.tg.send(
            f"🧭 <b>Choose quality for {n} post{'s' if n > 1 else ''}</b>\n{lines}\n\n"
            f"🏛 <b>Senior</b>: architect brief + playbook + strong reviewer ({EST_PER_POST['senior']} per post, paid)\n"
            f"💡 <b>Mini</b>: paid mini + playbook ({EST_PER_POST['mini']} per post)\n"
            f"🆓 <b>Free</b>: free models only ({EST_PER_POST['free']})\n"
            f"No answer in {self.timeout // 60} min = Free.",
            buttons=[[{"text": "🏛 Senior", "callback_data": f"paid:{key}:senior"},
                      {"text": "💡 Mini", "callback_data": f"paid:{key}:mini"},
                      {"text": "🆓 Free", "callback_data": f"paid:{key}:free"}]],
        )
        answer = await self._wait(key, MODES)
        self.mode = answer or "free"
        if self.mode in ("senior", "mini"):
            self.decision = True
        self.tg.send(f"👍 Running in <b>{self.mode}</b> mode.")
        return self.mode

    async def allow_paid(self, role: str, model: str, reason: str) -> bool:
        if self.mode in ("senior", "mini"):
            return True
        if self.decision is not None:
            return self.decision
        async with self._lock:                  # parallel teams share one question
            if self.decision is not None:
                return self.decision
            if not self.channel_ok:
                log.warning("paid fallback needed for %s but approval channel not configured -> denied", role)
                self.decision = False
                return False
            key = f"{self.base_key}-paid"
            self.tg.send(
                f"💸 <b>Free models failed</b> for <i>{esc(role)}</i> ({esc(reason[:160])}).\n"
                f"Use the paid model (<code>{esc(model)}</code>) for the rest of this run?\n"
                f"No answer in {self.timeout // 60} min = No.",
                buttons=[[{"text": "✅ Approve paid", "callback_data": f"paid:{key}:yes"},
                          {"text": "❌ No, stop", "callback_data": f"paid:{key}:no"}]],
            )
            self.decision = (await self._wait(key, ("yes", "no"))) == "yes"
            self.tg.send("✅ Paid model approved for this run." if self.decision else "⏹ Paid model not approved; stopping affected posts.")
            return self.decision

    async def _wait(self, key: str, allowed: tuple[str, ...]) -> str | None:
        deadline = time.monotonic() + self.timeout
        async with httpx.AsyncClient(timeout=20) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(f"{self.url}/approval/{key}", headers={"X-Approval-Auth": auth_for(key)})
                    if r.status_code == 200 and r.text.strip() in allowed:
                        return r.text.strip()
                except httpx.HTTPError as e:
                    log.warning("approval poll error: %s", type(e).__name__)
                await asyncio.sleep(8)
        return None
