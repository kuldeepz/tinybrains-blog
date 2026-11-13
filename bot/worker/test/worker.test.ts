// Smoke test of the webhook handler with fetch() stubbed (no network).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { createHash } from "node:crypto";
import worker from "../src/index.ts";

const kv = new Map<string, string>();
const env = { TELEGRAM_BOT_TOKEN: "tok", TELEGRAM_WEBHOOK_SECRET: "sec", TELEGRAM_CHAT_ID: "42", GITHUB_TOKEN: "gh", GITHUB_REPO: "o/r", SITE_URL: "https://x",
  APPROVALS: { get: async (k: string) => kv.get(k) ?? null, put: async (k: string, v: string) => void kv.set(k, v) } };
let calls: { url: string; method: string; body: any }[] = [];
let topics = { version: 1, next_id: 1, topics: [] as any[] };

beforeEach(() => {
  calls = [];
  topics = { version: 1, next_id: 1, topics: [] };
  (globalThis as any).fetch = async (url: string, init: any = {}) => {
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url, method: init.method ?? "GET", body });
    if (url.includes("/contents/ops/topics.json") && (init.method ?? "GET") === "GET") {
      return new Response(JSON.stringify({ sha: "s1", content: btoa(JSON.stringify(topics)) }));
    }
    if (url.includes("/contents/ops/topics.json")) {
      topics = JSON.parse(atob(body.content));
      return new Response("{}", { status: 200 });
    }
    return new Response(JSON.stringify({ ok: true }), { status: url.includes("/dispatches") ? 204 : 200 });
  };
});

const post = (update: unknown, secret = "sec") =>
  worker.fetch(new Request("https://w/telegram", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": secret }, body: JSON.stringify(update) }), env as any);
const msg = (text: string, chat = 42) => ({ message: { message_id: 1, chat: { id: chat }, text } });

test("rejects bad secret", async () => {
  assert.equal((await post(msg("/help"), "nope")).status, 403);
});

test("ignores other chats", async () => {
  await post(msg("/idea steal", 7));
  assert.equal(calls.length, 0);
});

test("/idea stores without dispatching", async () => {
  await post(msg("/idea KV cache quantization"));
  assert.equal(topics.topics.length, 1);
  assert.equal(topics.topics[0].status, "idea");
  assert.ok(!calls.some((c) => c.url.includes("/dispatches")));
});

test("free text and /write dispatch to Actions", async () => {
  await post(msg("save this for later: eval harnesses"));
  await post(msg("/write T001 T002"));
  const d = calls.filter((c) => c.url.includes("/dispatches")).map((c) => c.body.client_payload.kind);
  assert.deepEqual(d, ["message", "write"]);
});

test("approve button merges PR", async () => {
  await post({ callback_query: { id: "q", data: "approve:12", from: { id: 42 }, message: { message_id: 5, chat: { id: 42 } } } });
  assert.ok(calls.some((c) => c.url.endsWith("/pulls/12/merge") && c.method === "PUT"));
});

test("paid approval: button stores answer, poll needs auth", async () => {
  const key = "run-1-2";
  const auth = createHash("sha256").update(`tok:${key}`).digest("hex");
  const get = (h: Record<string, string>) => worker.fetch(new Request(`https://w/approval/${key}`, { headers: h }), env as any);
  assert.equal(await (await get({ "X-Approval-Auth": auth })).text(), "pending");
  assert.equal((await get({ "X-Approval-Auth": "wrong" })).status, 403);
  await post({ callback_query: { id: "q", data: `paid:${key}:yes`, from: { id: 42 }, message: { message_id: 5, chat: { id: 42 } } } });
  assert.equal(await (await get({ "X-Approval-Auth": auth })).text(), "yes");
});

test("paid approval ignored from other users", async () => {
  await post({ callback_query: { id: "q", data: "paid:run-x:yes", from: { id: 7 }, message: { message_id: 5, chat: { id: 7 } } } });
  assert.equal(kv.get("run-x"), undefined);
});

test("mode buttons store senior/mini/free once", async () => {
  const key = "run-9-1-mode";
  await post({ callback_query: { id: "q", data: `paid:${key}:senior`, from: { id: 42 }, message: { message_id: 5, chat: { id: 42 } } } });
  await post({ callback_query: { id: "q", data: `paid:${key}:free`, from: { id: 42 }, message: { message_id: 5, chat: { id: 42 } } } });
  assert.equal(kv.get(key), "senior");
});
