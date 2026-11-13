"""Offline tests: run with  python -m unittest discover -s tests  (no API keys or network needed)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="tb-test-"))
os.environ["TB_ROOT"] = str(TMP)
os.environ["TB_NO_PUSH"] = "1"
for k in ("TELEGRAM_BOT_TOKEN", "GDRIVE_FOLDER_ID", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(k, None)

from agents import llm as llm_mod  # noqa: E402
from agents import orchestrator  # noqa: E402
from agents.cli import add_ideas  # noqa: E402
from agents.roles.designer import cover_svg  # noqa: E402
from agents.roles.tester import sanitize_mdx  # noqa: E402
from agents.topics import Tracker  # noqa: E402

BODY = "Intro paragraph about agents.\n\n## Why\n\n" + ("Agents call tools in a loop and that is fine. " * 120) + \
       "\n\n```python\nprint({'a': 1})\n```\n\nLatency is <5ms and uses {braces}.\n"


class FakeLLM:
    azure_ready = True

    def __init__(self, *a, approver=None, **k):
        self.approver = approver
        self.roles_called = []
        self.usage = {"calls": 0}
        self.active = 0
        self.max_active = 0
        self.version = 0

    async def _tick(self):
        self.usage["calls"] += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1

    async def json(self, role, system, user):
        await self._tick()
        if role == "pm":
            title = "Tool calling agents " + str(abs(hash(user)) % 1000)
            return {"title": title, "topic": "Agents", "level": "Practitioner", "type": "Tutorial", "tags": ["agents"]}
        if role == "researcher":
            return {"notes": "facts", "sources": [{"title": "Docs", "url": "https://example.com"}]}
        if role == "reviewer":
            if getattr(self, "scores", None):
                sc = self.scores.pop(0)
                return {"approved": sc >= 9, "score": sc, "required_changes": [f"fix {sc}"], "body_seen": self.version}
            return {"approved": True, "score": 9, "issues": []}
        if role == "router":
            return {"intent": "store_idea", "topics": [{"title": "x"}]}
        return {}

    async def chat(self, role, system, user, json_mode=False):
        await self._tick()
        self.roles_called.append(role)
        if role in ("editor", "reviser"):
            self.version += 1
            return ('<meta>{"title": "T", "description": "D", "tldr": "TL", "takeaways": ["a"], "tags": ["agents"]}</meta><body>'
                    + BODY + f"\n\nversion {self.version}\n</body>")
        if role == "architect":
            return "## Thesis\nX"
        if role in ("editor", "reviser"):
            return '<meta>{"title": "T", "description": "D", "tldr": "TL", "takeaways": ["a"], "tags": ["agents"]}</meta><body>' + BODY + "</body>"
        if role == "designer":
            return "<body>" + BODY + "</body><diagram></diagram>"
        return BODY


class TestPipeline(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        (TMP / "ops").mkdir(parents=True)

    def test_idea_only_stores(self):
        added = add_ideas([{"title": "Speculative decoding explained"}], "cli")
        t = Tracker()
        self.assertEqual(t.topics[0]["status"], "idea")
        self.assertEqual(added[0][0]["id"], "T001")
        self.assertFalse((TMP / "site" / "src" / "content" / "posts").exists(), "storing an idea must not write a post")

    def test_duplicate_detection(self):
        add_ideas([{"title": "Hybrid retrieval with BM25 and embeddings"}], "cli")
        added = add_ideas([{"title": "Hybrid retrieval: BM25 and embeddings"}], "cli")
        self.assertTrue(added[0][1], "should flag similar topic")

    def test_parallel_teams(self):
        add_ideas([{"title": f"topic {i}"} for i in range(3)], "cli")
        fake = FakeLLM()
        with mock.patch.object(orchestrator, "make_llm", return_value=fake):
            posts = asyncio.run(orchestrator.run_write(["T001", "T002", "T003"], open_pr=False, build=False))
        self.assertEqual(len(posts), 3)
        self.assertTrue(all(p.ok for p in posts), [p.error for p in posts])
        self.assertGreaterEqual(fake.max_active, 2, "teams should run concurrently")
        self.assertEqual(len({p.slug for p in posts}), 3)
        files = list((TMP / "site" / "src" / "content" / "posts").glob("*.mdx"))
        self.assertEqual(len(files), 3)
        text = files[0].read_text()
        self.assertTrue(text.startswith("---\ntitle:"))
        self.assertIn("&lt;5ms", text)
        self.assertIn("\\{braces\\}", text)
        self.assertIn("print({'a': 1})", text, "code blocks must not be escaped")
        self.assertEqual({t["status"] for t in Tracker().topics}, {"in_progress"})  # no PR in local mode
        self.assertTrue(list((TMP / "ops" / "runs").glob("*.json")))


    def test_senior_mode_adds_architect_and_playbook(self):
        add_ideas([{"title": "kv cache"}], "cli")

        class SeniorApprover:
            mode = "senior"

            async def choose_mode(self, titles, azure_ready):
                return "senior"
        fake = FakeLLM(approver=SeniorApprover())
        with mock.patch.object(orchestrator, "make_llm", return_value=fake):
            posts = asyncio.run(orchestrator.run_write(["T001"], open_pr=False, build=False))
        self.assertTrue(posts[0].ok, posts[0].error)
        self.assertIn("architect", fake.roles_called)
        self.assertEqual(posts[0].architect_brief, "## Thesis\nX")

    def test_free_mode_skips_architect(self):
        add_ideas([{"title": "kv cache"}], "cli")
        fake = FakeLLM()
        with mock.patch.object(orchestrator, "make_llm", return_value=fake):
            asyncio.run(orchestrator.run_write(["T001"], open_pr=False, build=False))
        self.assertNotIn("architect", fake.roles_called)


class TestHelpers(unittest.TestCase):
    def test_sanitize_keeps_components(self):
        src = '<Callout type="tip">Use x <= 3 and {y}</Callout>\n<Terminal lines={`$ ls\nok {x}`} />\nsee `a<b>` and [l](https://x.y/{z})'
        out = sanitize_mdx(src)
        self.assertIn('<Callout type="tip">', out)
        self.assertIn("</Callout>", out)
        self.assertIn("&lt;= 3", out)
        self.assertIn("\\{y\\}", out)
        self.assertIn("<Terminal lines={`$ ls\nok {x}`} />", out)
        self.assertIn("`a<b>`", out)
        self.assertIn("(https://x.y/{z})", out)

    def test_cover_is_valid_svg(self):
        ET.fromstring(cover_svg("A <title> & more", "Agents", "seed"))

    def _client(self, approver=None):
        os.environ.update(OPENROUTER_API_KEY="x", GEMINI_API_KEY="y", GEMINI_ENDPOINT="https://e.openai.azure.com",
                          GEMINI_DEPLOYMENT="gpt-mini", GEMINI_DEPLOYMENT_ARCHITECT="gpt-big")
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in
                                 ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "GEMINI_ENDPOINT",
                                  "GEMINI_DEPLOYMENT", "GEMINI_DEPLOYMENT_ARCHITECT")])
        client = llm_mod.LLM(approver=approver)
        self.calls = []

        async def orr(rc, models, messages, json_mode):
            self.calls.append(("free", tuple(models)))
            if getattr(self, "free_fails", False):
                raise RuntimeError("429 rate limited")
            return "free answer"

        async def az(rc, messages, json_mode):
            self.calls.append(("azure", llm_mod.azure_deployment(rc.azure)))
            return "azure answer"
        client._call_openrouter = orr
        client._call_azure = az
        return client

    class _Ap:
        def __init__(self, mode=None, allow=False):
            self.mode, self.allow, self.asked = mode, allow, 0

        async def allow_paid(self, role, model, reason):
            self.asked += 1
            return self.allow

    def test_openrouter_is_free_only(self):
        os.environ["MODEL_WRITER_FREE"] = "openai/gpt-5-mini,nvidia/nemotron-3-ultra-550b-a55b:free"
        self.addCleanup(lambda: os.environ.pop("MODEL_WRITER_FREE", None))
        self.assertEqual(llm_mod.load_role("writer").free, ["nvidia/nemotron-3-ultra-550b-a55b:free"])

    def test_free_mode_uses_free_models(self):
        client = self._client(self._Ap(mode="free"))
        self.assertEqual(asyncio.run(client.chat("writer", "s", "u")), "free answer")
        self.assertEqual(self.calls[0][0], "free")
        self.assertTrue(all(m.endswith(":free") for m in self.calls[0][1]))

    def test_free_mode_failure_needs_approval(self):
        ap = self._Ap(mode="free", allow=False)
        client = self._client(ap)
        self.free_fails = True
        with self.assertRaises(llm_mod.LLMError):
            asyncio.run(client.chat("writer", "s", "u"))
        self.assertEqual(ap.asked, 1)
        self.assertNotIn("azure", [c[0] for c in self.calls])

    def test_free_mode_failure_approved_goes_to_azure(self):
        client = self._client(self._Ap(mode="free", allow=True))
        self.free_fails = True
        self.assertEqual(asyncio.run(client.chat("writer", "s", "u")), "azure answer")
        self.assertEqual([c[0] for c in self.calls], ["free", "azure"])

    def test_senior_mode_tiers(self):
        client = self._client(self._Ap(mode="senior"))
        asyncio.run(client.chat("writer", "s", "u"))
        asyncio.run(client.chat("reviewer", "s", "u"))
        asyncio.run(client.chat("architect", "s", "u"))
        asyncio.run(client.chat("router", "s", "u"))
        self.assertEqual(self.calls, [("azure", "gpt-mini"), ("azure", "gpt-big"), ("azure", "gpt-big"),
                                      ("free", ("google/gemma-4-26b-a4b-it:free", "google/gemma-4-31b-it:free", "baidu/ernie-5.5-flash-preview:free"))])

    def test_mini_mode_reviewer_stays_free(self):
        client = self._client(self._Ap(mode="mini"))
        asyncio.run(client.chat("writer", "s", "u"))
        asyncio.run(client.chat("reviewer", "s", "u"))
        self.assertEqual([c[0] for c in self.calls], ["azure", "free"])

    def test_choose_mode_without_azure_is_free(self):
        from agents import approval
        ap = approval.Approver()
        ap.tg = mock.Mock(enabled=True)
        ap.url = "https://bot.example"
        self.assertEqual(asyncio.run(ap.choose_mode(["T001 x"], azure_ready=False)), "free")

    def test_choose_mode_uses_button_answer(self):
        from agents import approval
        ap = approval.Approver()
        ap.tg = mock.Mock(enabled=True)
        ap.url = "https://bot.example"

        async def wait(key, allowed):
            self.assertTrue(key.endswith("-mode"))
            return "senior"
        ap._wait = wait
        self.assertEqual(asyncio.run(ap.choose_mode(["T001 x"], azure_ready=True)), "senior")
        self.assertTrue(asyncio.run(ap.allow_paid("writer", "m", "r")))

    def test_approver_asks_once_for_parallel_teams(self):
        from agents import approval
        ap = approval.Approver()
        ap.tg = mock.Mock(enabled=True)
        ap.url = "https://bot.example"
        asked = []

        async def wait(key, allowed):
            asked.append(1)
            await asyncio.sleep(0.01)
            return "yes"
        ap._wait = wait

        async def many():
            return await asyncio.gather(*(ap.allow_paid("writer", "m", "429") for _ in range(4)))
        self.assertEqual(asyncio.run(many()), [True] * 4)
        self.assertEqual(len(asked), 1)

    def test_approver_denies_without_channel(self):
        from agents import approval
        ap = approval.Approver()
        ap.url = ""
        self.assertFalse(asyncio.run(ap.allow_paid("writer", "m", "429")))

    def test_parse_json(self):
        self.assertEqual(llm_mod.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm_mod.parse_json('sure! {"a": 2} hope that helps'), {"a": 2})


class _Msg:
    def __init__(self, content): self.content = content
class _Choice:
    def __init__(self, content, finish): self.message = _Msg(content); self.finish_reason = finish
class _Resp:
    def __init__(self, content, finish="stop"): self.choices = [_Choice(content, finish)]; self.usage = None


class TestAzureReasoning(unittest.TestCase):
    def _llm(self, responses):
        calls = []
        async def create(**kw):
            calls.append(dict(kw))
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        llm = llm_mod.LLM.__new__(llm_mod.LLM)
        llm.usage = {"calls": 0, "paid_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "models": {}}
        llm._az = mock.Mock()
        llm._az.chat.completions.create = create
        return llm, calls

    def test_architect_and_reviewer_have_reasoning_budget(self):
        a, r = llm_mod.load_role("architect"), llm_mod.load_role("reviewer")
        self.assertEqual(a.reasoning_effort, "high"); self.assertGreaterEqual(a.max_tokens, 32000)
        self.assertEqual(r.reasoning_effort, "medium"); self.assertGreaterEqual(r.max_tokens, 20000)
        self.assertIsNone(llm_mod.load_role("writer").reasoning_effort)

    def test_reasoning_effort_sent_and_dropped_if_rejected(self):
        llm, calls = self._llm([Exception("Unsupported parameter: reasoning_effort"), _Resp("ok")])
        with mock.patch.dict(os.environ, {"GEMINI_DEPLOYMENT": "mini", "GEMINI_DEPLOYMENT_ARCHITECT": "sol"}):
            out = asyncio.run(llm._call_azure(llm_mod.load_role("architect"), [], False))
        self.assertEqual(out, "ok")
        self.assertEqual(calls[0]["reasoning_effort"], "high"); self.assertEqual(calls[0]["model"], "sol")
        self.assertNotIn("reasoning_effort", calls[1])

    def test_budget_exhausted_by_thinking_retries_bigger(self):
        llm, calls = self._llm([_Resp("", "length"), _Resp("", "length"), _Resp("brief")])
        with mock.patch.dict(os.environ, {"GEMINI_DEPLOYMENT": "mini"}):
            out = asyncio.run(llm._call_azure(llm_mod.load_role("architect"), [], False))
        self.assertEqual(out, "brief")
        self.assertEqual([c["max_completion_tokens"] for c in calls], [32000, 64000, 100000])
        self.assertEqual(calls[2]["reasoning_effort"], "medium")


class TestRevisionLoop(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        (TMP / "ops").mkdir(parents=True)

    def _run(self, scores, mode):
        add_ideas([{"title": "kv cache"}], "cli")

        class A:
            async def choose_mode(self, titles, azure_ready):
                return mode
        A.mode = mode
        fake = FakeLLM(approver=A())
        fake.scores = list(scores)
        with mock.patch.object(orchestrator, "make_llm", return_value=fake):
            posts = asyncio.run(orchestrator.run_write(["T001"], open_pr=False, build=False))
        return posts[0], fake

    def test_keeps_best_version_when_revisions_get_worse(self):
        post, fake = self._run([7, 8, 6], "senior")
        self.assertTrue(post.ok, post.error)
        self.assertEqual(post.review["score"], 8)
        self.assertIn("version 2", post.body)          # round-2 body (scored 8), not the final round-3 body
        self.assertEqual(fake.roles_called.count("reviser"), 2, "senior revisions use the strongest model")
        run = json.loads(next((TMP / "ops" / "runs").glob("*.json")).read_text())
        self.assertEqual([r["score"] for r in run["posts"][0]["reviews"]], [7, 8, 6])
        self.assertEqual(run["posts"][0]["reviews"][0]["issues"], ["fix 7"])

    def test_mini_mode_revises_with_editor(self):
        post, fake = self._run([7, 9], "mini")
        self.assertNotIn("reviser", fake.roles_called)
        self.assertEqual(post.review["score"], 9)

    def test_style_issues_catch_meta_talk_and_bloat(self):
        from agents.roles.base import Post
        from agents.roles.tester import style_issues
        p = Post(topic={"id": "T1"}, body="Intro.\n\n```python\n" + "x = 1\n" * 150 + "```\n" + "word " * 3400,
                 meta={"tldr": "This revised post explains caching.", "takeaways": ["Tested combinations: gpt2"]})
        issues = " | ".join(style_issues(p))
        self.assertIn("this revised post", issues)
        self.assertIn("tested combinations", issues)
        self.assertIn("code block is 150 lines", issues)
        self.assertIn("words", issues)
        self.assertEqual(style_issues(Post(topic={}, body="Plain senior prose about caching.", meta={"tldr": "KV cache trades memory for compute."})), [])

    def test_reviser_role_uses_architect_tier(self):
        rc = llm_mod.load_role("reviser")
        self.assertEqual(rc.azure, "architect")
        self.assertTrue(rc.prefer_paid)


if __name__ == "__main__":
    unittest.main()
