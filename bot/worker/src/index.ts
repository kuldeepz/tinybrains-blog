// Telegram webhook -> quick commands handled here; heavy work dispatched to GitHub Actions (agents.yml).
import { addIdea, parseCommand, setStatus, similar, summary, type TopicsFile } from "./topics.ts";

export interface Env {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_WEBHOOK_SECRET: string;
  TELEGRAM_CHAT_ID: string;
  GITHUB_TOKEN: string;
  GITHUB_REPO: string;
  SITE_URL: string;
  APPROVALS: KVNamespace; // paid-model approvals: key -> "yes" | "no"
}

const HELP = `🧠 <b>tinybrains.ai blog bot</b>
/idea &lt;text&gt; – store an idea only (no writing)
/ideas – list stored ideas
/write &lt;topic | T001 T002&gt; – write now (several = parallel teams)
/rewrite &lt;T001&gt; – rewrite a published post from scratch (same URL; old version stays live until you approve)
/topics or /status – what's covered / pending
/drop &lt;id&gt; – discard an idea
📎 Send a file or image (caption optional; say "write" to write now, otherwise it's stored as an idea).
Plain messages are understood too, e.g. "save this for later: …"`;

const TOPICS_PATH = "ops/topics.json";

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname.startsWith("/approval/")) return approvalStatus(req, url, env);
    if (req.method === "GET") return new Response("tinybrains bot ok");
    if (url.pathname !== "/telegram" || req.method !== "POST") return new Response("not found", { status: 404 });
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    const update: any = await req.json();
    try {
      await handle(update, env);
    } catch (e) {
      const chat = update.message?.chat?.id ?? update.callback_query?.message?.chat?.id;
      if (String(chat) === String(env.TELEGRAM_CHAT_ID)) await send(env, `⚠️ ${esc(String((e as Error).message).slice(0, 300))}`);
    }
    return new Response("ok"); // always 200 so Telegram doesn't retry
  },
};

async function handle(update: any, env: Env): Promise<void> {
  if (update.callback_query) return handleCallback(update.callback_query, env);
  const msg = update.message ?? update.edited_message;
  if (!msg) return;
  if (String(msg.chat?.id) !== String(env.TELEGRAM_CHAT_ID)) return; // owner only; ignore everyone else silently

  const text: string = msg.text ?? msg.caption ?? "";
  const file = msg.document
    ? { id: msg.document.file_id, name: msg.document.file_name ?? "file", mime: msg.document.mime_type ?? "" }
    : msg.photo?.length
      ? { id: msg.photo[msg.photo.length - 1].file_id, name: `photo-${msg.message_id}.jpg`, mime: "image/jpeg" }
      : null;

  if (file) {
    await dispatch(env, { kind: "upload", text, file, chat_id: msg.chat.id, message_id: msg.message_id });
    return send(env, "📎 Got it, reading the file…");
  }

  const c = parseCommand(text);
  if (!c) {
    await dispatch(env, { kind: "message", text, chat_id: msg.chat.id, message_id: msg.message_id });
    return send(env, "🧠 On it…");
  }
  switch (c.cmd) {
    case "start":
    case "help":
      return send(env, HELP);
    case "idea": {
      if (!c.arg) return send(env, "Usage: /idea &lt;your idea&gt;");
      const [title, ...rest] = c.arg.split("\n");
      const { result } = await updateTopics(env, (f) => {
        const dups = similar(f, title);
        const t = addIdea(f, title, rest.join("\n"));
        return { t, dups };
      }, "tracker: add idea via telegram");
      const dupLines = result.dups.slice(0, 2).map((d) => `\n   ↳ similar to ${d.id} (${d.status}): ${esc(d.title)}`).join("");
      return send(env, `💡 Stored <b>${result.t.id}</b> ${esc(result.t.title)}${dupLines}\nSend /write ${result.t.id} when you want it written.`);
    }
    case "ideas": {
      const { file: f } = await getTopics(env);
      return send(env, esc(summary(f, ["idea", "queued"])));
    }
    case "topics":
    case "status": {
      const { file: f } = await getTopics(env);
      return send(env, esc(summary(f)));
    }
    case "drop": {
      const id = c.arg.toUpperCase();
      const { result } = await updateTopics(env, (f) => {
        const t = f.topics.find((x) => x.id === id);
        if (t && !["published", "in_review"].includes(t.status)) setStatus(t, "rejected");
        return t;
      }, `tracker: drop ${id}`);
      return send(env, result ? `🗑 ${id} ${result.status === "rejected" ? "dropped" : `is ${result.status}, not dropped`}` : `Unknown id ${esc(id)}`);
    }
    case "write": {
      if (!c.arg) return send(env, "Usage: /write &lt;topic&gt; or /write T001 T002");
      await dispatch(env, { kind: "write", text: c.arg, chat_id: msg.chat.id, message_id: msg.message_id });
      return send(env, "🚀 Assembling the team… I'll post progress here.");
    }
    case "rewrite": {
      const ids = (c.arg.toUpperCase().match(/T\d+/g) ?? []);
      if (!ids.length) return send(env, "Usage: /rewrite T001 (a published topic id; see /topics)");
      await dispatch(env, { kind: "rewrite", text: ids.join(" "), chat_id: msg.chat.id, message_id: msg.message_id });
      return send(env, `♻️ Rewriting ${ids.join(", ")} from scratch. The live version stays up until you approve the new one.`);
    }
    default:
      await dispatch(env, { kind: "message", text, chat_id: msg.chat.id, message_id: msg.message_id });
      return send(env, "🧠 On it…");
  }
}

async function handleCallback(q: any, env: Env): Promise<void> {
  if (String(q.from?.id) !== String(env.TELEGRAM_CHAT_ID) && String(q.message?.chat?.id) !== String(env.TELEGRAM_CHAT_ID)) return;
  const [action, prStr, answer] = String(q.data ?? "").split(":");
  const pr = Number(prStr);
  let note = "";
  const PAID_NOTES: Record<string, string> = {
    yes: "💸 Azure approved for this run.",
    no: "⏹ Azure declined.",
    senior: "🏛 Senior mode selected.",
    mini: "💡 Mini mode selected.",
    free: "🆓 Free mode selected.",
  };
  if (action === "paid" && prStr && answer in PAID_NOTES && /^[\w.-]{1,100}$/.test(prStr)) {
    if (await env.APPROVALS.get(prStr)) {
      note = "Already answered for this run.";
    } else {
      await env.APPROVALS.put(prStr, answer, { expirationTtl: 86400 });
      note = PAID_NOTES[answer];
    }
  } else if (action === "approve" && pr) {
    const r = await gh(env, `/pulls/${pr}/merge`, "PUT", { merge_method: "squash" });
    note = r.ok ? `✅ Merged PR #${pr}. Publishing…` : `⚠️ Merge failed: ${esc((await r.json<any>()).message ?? r.status)}`;
  } else if (action === "reject" && pr) {
    const r = await gh(env, `/pulls/${pr}`, "PATCH", { state: "closed" });
    note = r.ok ? `🗑 Closed PR #${pr}.` : `⚠️ Close failed (${r.status})`;
  }
  await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: note.replace(/<[^>]+>/g, "").slice(0, 190) });
  if (q.message) {
    await tg(env, "editMessageReplyMarkup", { chat_id: q.message.chat.id, message_id: q.message.message_id, reply_markup: { inline_keyboard: [] } });
  }
  if (note) await send(env, note);
}

// ---- paid-model approval polling (called by the GitHub Actions run)
async function approvalStatus(req: Request, url: URL, env: Env): Promise<Response> {
  const key = decodeURIComponent(url.pathname.slice("/approval/".length));
  if (!/^[\w.-]{1,100}$/.test(key)) return new Response("bad key", { status: 400 });
  const expected = await sha256Hex(`${env.TELEGRAM_BOT_TOKEN}:${key}`);
  if (req.headers.get("X-Approval-Auth") !== expected) return new Response("forbidden", { status: 403 });
  return new Response((await env.APPROVALS.get(key)) ?? "pending");
}

export async function sha256Hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---- GitHub
async function gh(env: Env, path: string, method = "GET", body?: unknown): Promise<Response> {
  return fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "tinybrains-bot",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

async function dispatch(env: Env, payload: Record<string, unknown>): Promise<void> {
  const r = await gh(env, "/dispatches", "POST", { event_type: "telegram", client_payload: payload });
  if (!r.ok) throw new Error(`GitHub dispatch failed (${r.status})${permHint(r.status)}`);
}

// Fine-grained PAT problems are the usual cause of 401/403/404: say exactly what to change.
export function permHint(status: number): string {
  if (status === 401) return ": BOT_GITHUB_PAT is invalid or expired. Create a new one, update the GitHub secret and re-run the Deploy Telegram bot workflow.";
  if (status === 403) return ": BOT_GITHUB_PAT needs Repository permissions → Contents: Read and write (and Pull requests: Read and write).";
  if (status === 404) return ": BOT_GITHUB_PAT has no access to this repo. Add it under Repository access.";
  return "";
}

async function getTopics(env: Env): Promise<{ file: TopicsFile; sha: string }> {
  const r = await gh(env, `/contents/${TOPICS_PATH}?ref=main`);
  if (!r.ok) throw new Error(`could not read tracker (${r.status})`);
  const j: any = await r.json();
  return { file: JSON.parse(b64decode(j.content)), sha: j.sha };
}

async function updateTopics<T>(env: Env, mutate: (f: TopicsFile) => T, message: string): Promise<{ result: T }> {
  for (let attempt = 0; attempt < 4; attempt++) {
    const { file, sha } = await getTopics(env);
    const result = mutate(file);
    const r = await gh(env, `/contents/${TOPICS_PATH}`, "PUT", {
      message, sha, branch: "main", content: b64encode(JSON.stringify(file, null, 2) + "\n"),
    });
    if (r.ok) return { result };
    if (r.status !== 409 && r.status !== 422) throw new Error(`tracker update failed (${r.status})${permHint(r.status)}`);
    await new Promise((res) => setTimeout(res, 400 * (attempt + 1))); // concurrent edit: refetch + reapply
  }
  throw new Error("tracker busy, try again");
}

// ---- Telegram
async function tg(env: Env, method: string, payload: unknown): Promise<Response> {
  return fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
}

async function send(env: Env, html: string): Promise<void> {
  for (let i = 0; i < html.length || i === 0; i += 3900) {
    await tg(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: html.slice(i, i + 3900), parse_mode: "HTML", disable_web_page_preview: true });
  }
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function b64decode(b64: string): string {
  const bin = atob(b64.replace(/\n/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function b64encode(s: string): string {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
