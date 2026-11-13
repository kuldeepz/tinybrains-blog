"""LLM access: OpenRouter primary, Azure OpenAI fallback (both via the OpenAI SDK)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import yaml
from openai import AsyncAzureOpenAI, AsyncOpenAI

from .settings import MODELS_FILE, env

log = logging.getLogger("tb.llm")


class LLMError(RuntimeError):
    pass


@dataclass
class RoleConfig:
    free: list[str]
    paid: str | None = None
    azure: str = "large"
    temperature: float = 0.4
    max_tokens: int = 8000
    web: bool = False


def load_role(role: str) -> RoleConfig:
    cfg = yaml.safe_load(MODELS_FILE.read_text())
    base = dict(cfg.get("defaults", {}))
    base.update(cfg["roles"].get(role, cfg["roles"]["editor"]))
    if "model" in base and "free" not in base:  # legacy single-model config
        base["paid"] = base.pop("model")
        base["free"] = []
    if env(f"MODEL_{role.upper()}_FREE") is not None:
        base["free"] = [m.strip() for m in env(f"MODEL_{role.upper()}_FREE", "").split(",") if m.strip()]
    if env(f"MODEL_{role.upper()}_PAID"):
        base["paid"] = env(f"MODEL_{role.upper()}_PAID")
    base.setdefault("free", [])
    return RoleConfig(**{k: v for k, v in base.items() if k in RoleConfig.__annotations__})


class LLM:
    """Shared client: free OpenRouter models -> (owner approval) -> paid OpenRouter -> Azure OpenAI.

    `approver` must have `async allow_paid(role, model, reason) -> bool`. Without one, paid use is denied
    unless TB_PAID_APPROVED=1.
    """

    def __init__(self, force: str | None = None, approver=None):
        self.force = force or env("TB_LLM_FORCE")
        self.approver = approver
        self._or = None
        self._az = None
        if env("OPENROUTER_API_KEY") and self.force != "azure":
            self._or = AsyncOpenAI(
                base_url=env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                api_key=env("OPENROUTER_API_KEY"),
                default_headers={"HTTP-Referer": "https://github.com/kuldeepz/tinybrains-blog", "X-Title": "tinybrains.ai"},
                timeout=300,
                max_retries=1,
            )
        if env("AZURE_OPENAI_API_KEY") and env("AZURE_OPENAI_ENDPOINT") and self.force != "openrouter":
            self._az = AsyncAzureOpenAI(
                azure_endpoint=env("AZURE_OPENAI_ENDPOINT"),
                api_key=env("AZURE_OPENAI_API_KEY"),
                api_version=env("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                timeout=300,
                max_retries=1,
            )
        if not (self._or or self._az):
            raise LLMError("No LLM provider configured: set OPENROUTER_API_KEY and/or AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT")
        self.usage: dict[str, Any] = {"calls": 0, "free_calls": 0, "paid_calls": 0, "fallbacks": 0,
                                      "prompt_tokens": 0, "completion_tokens": 0, "models": {}}

    async def _paid_ok(self, role: str, model: str, reason: str) -> bool:
        if env("TB_PAID_APPROVED") == "1":
            return True
        if self.approver is None:
            return False
        return await self.approver.allow_paid(role, model, reason)

    async def chat(self, role: str, system: str, user: str | list[dict[str, Any]], *, json_mode: bool = False) -> str:
        rc = load_role(role)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        errors: list[str] = []
        # 1) free models (OpenRouter tries the list in order)
        if self._or and rc.free:
            try:
                return await self._call_openrouter(rc, rc.free, messages, json_mode, paid=False)
            except Exception as e:  # noqa: BLE001 - any failure moves on
                errors.append(f"free[{rc.free[0]}…]: {type(e).__name__}: {str(e)[:160]}")
                log.warning("free models failed for %s: %s", role, errors[-1])
        # 2) paid models only with owner approval
        paid_label = rc.paid or "Azure OpenAI"
        if not await self._paid_ok(role, paid_label, errors[-1] if errors else "no free model configured"):
            raise LLMError("paid models not approved; " + "; ".join(errors))
        if self._or and rc.paid:
            try:
                out = await self._call_openrouter(rc, [rc.paid], messages, json_mode, paid=True)
                self.usage["fallbacks"] += bool(errors)
                return out
            except Exception as e:  # noqa: BLE001
                errors.append(f"openrouter[{rc.paid}]: {type(e).__name__}: {str(e)[:160]}")
                log.warning("paid OpenRouter failed for %s: %s", role, errors[-1])
        if self._az:
            try:
                out = await self._call_azure(rc, messages, json_mode)
                self.usage["fallbacks"] += 1
                return out
            except Exception as e:  # noqa: BLE001
                errors.append(f"azure: {type(e).__name__}: {str(e)[:160]}")
        raise LLMError("; ".join(errors))

    async def _call_openrouter(self, rc: RoleConfig, models: list[str], messages, json_mode: bool, *, paid: bool) -> str:
        extra: dict[str, Any] = {}
        if len(models) > 1:
            extra["models"] = models[1:]  # OpenRouter native fallback list
        if rc.web:
            extra["plugins"] = [{"id": "web", "max_results": 6}]
        kwargs: dict[str, Any] = dict(model=models[0], messages=messages, temperature=rc.temperature, max_tokens=rc.max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await self._or.chat.completions.create(**kwargs, extra_body=extra or None)
        except Exception as e:  # some models don't support response_format -> retry without (we parse JSON ourselves)
            if json_mode and ("response_format" in str(e) or "No endpoints" in str(e) or "structured" in str(e).lower()):
                kwargs.pop("response_format")
                resp = await self._or.chat.completions.create(**kwargs, extra_body=extra or None)
            else:
                raise
        self.usage["paid_calls" if paid else "free_calls"] += 1
        used = getattr(resp, "model", None) or models[0]
        self.usage["models"][used] = self.usage["models"].get(used, 0) + 1
        return self._content(resp)

    async def _call_azure(self, rc: RoleConfig, messages, json_mode: bool) -> str:
        dep = env("AZURE_OPENAI_DEPLOYMENT")
        if rc.azure == "small":
            dep = env("AZURE_OPENAI_DEPLOYMENT_SMALL", dep)
        if not dep:
            raise LLMError("AZURE_OPENAI_DEPLOYMENT not set")
        kwargs: dict[str, Any] = dict(model=dep, messages=messages, max_completion_tokens=rc.max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._az.chat.completions.create(**kwargs)
        self.usage["paid_calls"] += 1
        self.usage["models"][f"azure:{dep}"] = self.usage["models"].get(f"azure:{dep}", 0) + 1
        return self._content(resp)

    def _content(self, resp) -> str:
        self.usage["calls"] += 1
        if getattr(resp, "usage", None):
            self.usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            self.usage["completion_tokens"] += resp.usage.completion_tokens or 0
        if not resp.choices or not resp.choices[0].message.content:
            raise LLMError("empty completion")
        return resp.choices[0].message.content

    async def json(self, role: str, system: str, user: str | list[dict[str, Any]]) -> dict[str, Any]:
        """Chat expecting a JSON object; one repair retry on parse failure."""
        sys = system + "\n\nRespond with a single valid JSON object only. No prose, no markdown fences."
        raw = await self.chat(role, sys, user, json_mode=True)
        try:
            return parse_json(raw)
        except ValueError:
            raw2 = await self.chat(role, "Fix this into one valid JSON object. Output only JSON.", raw[:30000], json_mode=True)
            return parse_json(raw2)


def parse_json(text: str) -> dict[str, Any]:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("not valid JSON")


async def gather_limited(limit: int, coros):
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)


_APPROVER = None


def make_llm() -> LLM:
    """LLM wired to the process-wide Telegram approver (one paid-approval question per run)."""
    global _APPROVER
    if _APPROVER is None:
        from .approval import Approver
        _APPROVER = Approver()
    return LLM(approver=_APPROVER)
