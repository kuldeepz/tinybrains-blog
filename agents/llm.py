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
    model: str
    azure: str = "large"
    temperature: float = 0.4
    max_tokens: int = 8000
    web: bool = False


def load_role(role: str) -> RoleConfig:
    cfg = yaml.safe_load(MODELS_FILE.read_text())
    base = dict(cfg.get("defaults", {}))
    base.update(cfg["roles"].get(role, cfg["roles"]["editor"]))
    override = env(f"MODEL_{role.upper()}")
    if override:
        base["model"] = override
    return RoleConfig(**{k: v for k, v in base.items() if k in RoleConfig.__annotations__})


class LLM:
    """Shared client. `force` = "openrouter" | "azure" restricts providers (used in tests)."""

    def __init__(self, force: str | None = None):
        self.force = force or env("TB_LLM_FORCE")
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
        self.usage: dict[str, int] = {"calls": 0, "fallbacks": 0, "prompt_tokens": 0, "completion_tokens": 0}

    async def chat(self, role: str, system: str, user: str | list[dict[str, Any]], *, json_mode: bool = False) -> str:
        rc = load_role(role)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        errors: list[str] = []
        if self._or:
            try:
                return await self._call_openrouter(rc, messages, json_mode)
            except Exception as e:  # noqa: BLE001 - any provider failure triggers fallback
                errors.append(f"openrouter[{rc.model}]: {type(e).__name__}: {str(e)[:200]}")
                log.warning("OpenRouter failed for %s, falling back to Azure: %s", role, errors[-1])
        if self._az:
            try:
                out = await self._call_azure(rc, messages, json_mode)
                if errors:
                    self.usage["fallbacks"] += 1
                return out
            except Exception as e:  # noqa: BLE001
                errors.append(f"azure: {type(e).__name__}: {str(e)[:200]}")
        raise LLMError("; ".join(errors))

    async def _call_openrouter(self, rc: RoleConfig, messages, json_mode: bool) -> str:
        extra: dict[str, Any] = {}
        if rc.web:
            extra["plugins"] = [{"id": "web", "max_results": 6}]
        kwargs: dict[str, Any] = dict(model=rc.model, messages=messages, temperature=rc.temperature, max_tokens=rc.max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._or.chat.completions.create(**kwargs, extra_body=extra or None)
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
