import assert from "node:assert/strict";
import { test } from "node:test";
import { addIdea, parseCommand, similar, summary, type TopicsFile } from "../src/topics.ts";

const fresh = (): TopicsFile => ({ version: 1, next_id: 1, topics: [] });

test("addIdea assigns sequential ids and idea status", () => {
  const f = fresh();
  assert.equal(addIdea(f, "KV cache explained").id, "T001");
  assert.equal(addIdea(f, "Speculative decoding").id, "T002");
  assert.equal(f.topics[0].status, "idea");
});

test("similar flags near-duplicates", () => {
  const f = fresh();
  addIdea(f, "Hybrid retrieval with BM25 and embeddings");
  assert.equal(similar(f, "Hybrid retrieval: BM25 and embeddings").length, 1);
  assert.equal(similar(f, "Fine-tuning small models with LoRA").length, 0);
});

test("parseCommand handles bot suffix and multiline", () => {
  assert.deepEqual(parseCommand("/idea@tinybrains_bot KV cache\nmore"), { cmd: "idea", arg: "KV cache\nmore" });
  assert.equal(parseCommand("hello"), null);
});

test("summary counts", () => {
  const f = fresh();
  addIdea(f, "a topic");
  assert.match(summary(f), /💡 1 ideas/);
});
