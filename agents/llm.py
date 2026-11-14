"""LLM access: OpenRouter primary, Azure OpenAI fallback (both via the OpenAI SDK)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
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
    azure: str | None = "mini"
    prefer_paid: bool = False
    prefer_paid_in: list[str] = field(default_factory=list)
    temperature: float = 0.4
    max_tokens: int = 8000
    web: bool = False
    reasoning_effort: str | None = None  # Azure reasoning models only (low|medium|high); hidden thinking counts toward max_tokens


AZURE_TIERS = {
    "mini": ("GEMINI_DEPLOYMENT",),
    "architect": ("GEMINI_DEPLOYMENT_ARCHITECT", "GEMINI_DEPLOYMENT"),
    "small": ("GEMINI_DEPLOYMENT_SMALL", "GEMINI_DEPLOYMENT"),
}


def azure_deployment(tier: str | None) -> str | None:
    for name in AZURE_TIERS.get(tier or "mini", AZURE_TIERS["mini"]):
        if env(name):
            return env(name)
    return None


def load_role(role: str) -> RoleConfig:
    cfg = yaml.safe_load(MODELS_FILE.read_text())
    base = dict(cfg.get("defaults", {}))
    base.update(cfg["roles"].get(role, cfg["roles"]["editor"]))
    if env(f"MODEL_{role.upper()}_FREE") is not None:
        base["free"] = [m.strip() for m in env(f"MODEL_{role.upper()}_FREE", "").split(",") if m.strip()]
    if env(f"MODEL_{role.upper()}_AZURE"):
        base["azure"] = env(f"MODEL_{role.upper()}_AZURE")
    base.setdefault("free", [])
    base["free"] = [m for m in base["free"] if m.endswith(":free")]  # OpenRouter is free-only by policy
    return RoleConfig(**{k: v for k, v in base.items() if k in RoleConfig.__annotations__})


class LLM:
    """Free OpenRouter models + paid Azure OpenAI, gated by the owner's choice for the run.

    Run modes (chosen in Telegram per /write, see approval.Approver):
      senior / mini : Azure allowed; roles with prefer_paid use Azure first, free models as fallback.
      free (or None): free models only; if they fail the owner is asked once before Azure is used.
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
        if env("GEMINI_API_KEY") and env("GEMINI_ENDPOINT") and self.force != "openrouter":
            self._az = AsyncAzureOpenAI(
                azure_endpoint=env("GEMINI_ENDPOINT"),
                api_key=env("GEMINI_API_KEY"),
                api_version=env("GEMINI_API_VERSION", "2025-04-01-preview"),
                timeout=600,
                max_retries=1,
            )
        if not (self._or or self._az):
            raise LLMError("No LLM provider configured: set OPENROUTER_API_KEY and/or GEMINI_API_KEY + GEMINI_ENDPOINT")
        self.usage: dict[str, Any] = {"calls": 0, "free_calls": 0, "paid_calls": 0, "fallbacks": 0,
                                      "prompt_tokens": 0, "completion_tokens": 0, "models": {}}

    @property
    def mode(self) -> str:
        return (getattr(self.approver, "mode", None) or env("TB_MODE") or "free").lower()

    @property
    def azure_ready(self) -> bool:
        return self._az is not None and azure_deployment("mini") is not None

    async def _paid_ok(self, role: str, model: str, reason: str) -> bool:
        if self.mode in ("senior", "mini") or env("TB_PAID_APPROVED") == "1":
            return True
        if self.approver is None:
            return False
        return await self.approver.allow_paid(role, model, reason)

    async def chat(self, role: str, system: str, user: str | list[dict[str, Any]], *, json_mode: bool = False) -> str:
        rc = load_role(role)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        errors: list[str] = []
        prefer_azure = self.mode in ("senior", "mini") and (rc.prefer_paid or self.mode in rc.prefer_paid_in) and self._az
        if prefer_azure:
            try:
                return await self._call_azure(rc, messages, json_mode)
            except Exception as e:  # noqa: BLE001
                errors.append(f"paid[{rc.azure}]: {type(e).__name__}: {str(e)[:160]}")
                log.warning("Paid model failed for %s, trying free models: %s", role, errors[-1])
        if self._or and rc.free:
            # OpenRouter's native fallback only covers errors; an empty or broken answer from the first model
            # (common on free tiers) must still move on to the next one.
            for i in range(len(rc.free)):
                try:
                    out = await self._call_openrouter(rc, rc.free[i:], messages, json_mode)
                    self.usage["fallbacks"] += bool(errors)
                    return out
                except Exception as e:  # noqa: BLE001
                    errors.append(f"free[{rc.free[i]}]: {type(e).__name__}: {str(e)[:160]}")
                    log.warning("free model failed for %s: %s", role, errors[-1])
        if prefer_azure or not self._az:
            raise LLMError("; ".join(errors) or f"no model available for {role}")
        if not await self._paid_ok(role, f"paid {rc.azure}", errors[-1] if errors else "no free model for this role"):
            raise LLMError("paid models not approved; " + "; ".join(errors))
        try:
            out = await self._call_azure(rc, messages, json_mode)
            self.usage["fallbacks"] += 1
            return out
        except Exception as e:  # noqa: BLE001
            errors.append(f"paid[{rc.azure}]: {type(e).__name__}: {str(e)[:160]}")
        raise LLMError("; ".join(errors))

    async def _call_openrouter(self, rc: RoleConfig, models: list[str], messages, json_mode: bool) -> str:
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
        used = getattr(resp, "model", None) or models[0]
        if not used.endswith(":free") and not any(m == used for m in models):
            log.warning("OpenRouter served non-listed model %s", used)
        out = self._content(resp)
        self.usage["free_calls"] += 1
        self.usage["models"][used] = self.usage["models"].get(used, 0) + 1
        return out

    async def _call_azure(self, rc: RoleConfig, messages, json_mode: bool) -> str:
        dep = azure_deployment(rc.azure)
        if not dep:
            raise LLMError("GEMINI_DEPLOYMENT not set")
        kwargs: dict[str, Any] = dict(model=dep, messages=messages, max_completion_tokens=rc.max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if rc.reasoning_effort:
            kwargs["reasoning_effort"] = rc.reasoning_effort
        for attempt in range(3):
            try:
                resp = await self._az.chat.completions.create(**kwargs)
            except Exception as e:  # older API versions / non-reasoning deployments reject reasoning_effort
                if "reasoning_effort" in kwargs and "reasoning_effort" in str(e):
                    kwargs.pop("reasoning_effort")
                    continue
                raise
            choice = resp.choices[0] if resp.choices else None
            truncated = choice is not None and choice.finish_reason == "length" and not (choice.message.content or "").strip()
            if truncated and attempt < 2:
                # A reasoning model spent the whole budget thinking: give it more room once, then think less.
                self._content_usage(resp)
                kwargs["max_completion_tokens"] = min(kwargs["max_completion_tokens"] * 2, 100000)
                if attempt == 1 and kwargs.get("reasoning_effort") == "high":
                    kwargs["reasoning_effort"] = "medium"
                continue
            break
        out = self._content(resp)
        self.usage["paid_calls"] += 1
        self.usage["models"][f"azure:{dep}"] = self.usage["models"].get(f"azure:{dep}", 0) + 1
        return out

    def _content_usage(self, resp) -> None:
        self.usage["calls"] += 1
        if getattr(resp, "usage", None):
            self.usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            self.usage["completion_tokens"] += resp.usage.completion_tokens or 0

    def _content(self, resp) -> str:
        self._content_usage(resp)
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
