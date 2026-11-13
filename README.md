# tinybrains.ai

An AI-engineering blog written by a team of AI agents that you drive from Telegram.

- **Site:** https://kuldeepz.github.io/tinybrains-blog (Astro, GitHub Pages)
- **Bot:** Telegram → Cloudflare Worker → GitHub Actions agent teams → PR → you approve → live
- **LLMs:** OpenRouter primary, Azure OpenAI fallback (`agents/models.yaml`)
- **Storage:** public content + topic tracker in this repo; private material (chat logs, uploads) in your Google Drive, deleted after the post is published or rejected

```
Telegram ──▶ Cloudflare Worker (bot/worker)
              ├─ /idea /ideas /topics /status /drop   → edits ops/topics.json directly (instant)
              └─ /write, files, free text             → repository_dispatch → .github/workflows/agents.yml
                                                         ├─ Head splits request → N parallel teams
                                                         │   PM → Researcher(web) → Writer → Editor → Designer → Reviewer ⇄ Editor → Tester
                                                         ├─ shared Tester: astro build of all new posts
                                                         └─ Publisher: one PR per post + Telegram preview [Approve][Reject]
Approve ─▶ Worker merges PR ─▶ pages.yml deploys site; finalize.yml marks published + purges Drive uploads
```

## Talking to the bot

| You send | What happens |
|---|---|
| `/idea Speculative decoding in vLLM` | Stored as an idea (T00N) and nothing is written. Warns about similar existing topics |
| "save this for later: …" | Same: the router treats store/save/later as **store only** |
| `/write T003` or `/write KV cache quantization` | One lean team writes it |
| `/write T003 T007 T009` or several topics in one message | One team per topic, run in parallel (up to `TB_MAX_PARALLEL`, default 4) |
| a file or image (+ optional caption) | Saved privately to Drive, read (text/PDF/code; images via a vision model) and turned into an idea. Put "write" in the caption to write it now |
| `/topics`, `/status`, `/ideas` | What's covered, in review, in progress, and pending |
| `/drop T004` | Discard an idea |
| ✅ / ❌ under a draft | Merge (publish) or close (reject) the PR |

Topic lifecycle (`ops/topics.json`): `idea → queued → in_progress → in_review → published | rejected`.
Each run writes a non-personal audit file to `ops/runs/` with agents, review scores and token usage.

## Repo layout

```
site/                  Astro site (posts: site/src/content/posts/*.mdx, config: site/src/config.ts)
agents/                Python agent team (cli.py, orchestrator.py, roles/, llm.py, drive.py, telegram.py)
agents/models.yaml     model per role; override with env MODEL_<ROLE>
bot/worker/            Cloudflare Worker (Telegram webhook)
ops/topics.json        topic tracker (public: titles + status only)
.github/workflows/     pages.yml · agents.yml · finalize.yml · ci.yml
tests/                 offline tests (fake LLM, no keys needed)
```

## One-time setup

### 1. Telegram bot
1. In Telegram, message **@BotFather**, send `/newbot`, and copy the **bot token**.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`. That's your **chat ID**. The bot only ever responds to this chat.

### 2. LLM keys
- **OpenRouter:** create a key at openrouter.ai/keys.
- **Azure OpenAI (fallback):** endpoint `https://<resource>.openai.azure.com`, key, and a deployment name (optionally a second, cheaper deployment for small roles).

### 3. Google Drive (private storage)
Service account route (recommended, needs a **Shared Drive**, because service accounts have no My-Drive storage quota):
1. Google Cloud console → new project → enable **Google Drive API**.
2. IAM → Service accounts → create → Keys → add JSON key.
3. Create a folder inside a Shared Drive, add the service account email as **Content manager**, and copy the folder ID from its URL.

Personal My Drive instead? Use an OAuth client and refresh token: set `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET` and `GDRIVE_REFRESH_TOKEN` instead of `GDRIVE_SA_JSON`.

### 4. GitHub secrets & variables (repo → Settings → Secrets and variables → Actions)
Secrets: `OPENROUTER_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GDRIVE_FOLDER_ID`, `GDRIVE_SA_JSON` (paste the whole JSON).
Variables: `AZURE_OPENAI_DEPLOYMENT`, optional `AZURE_OPENAI_DEPLOYMENT_SMALL`, `AZURE_OPENAI_API_VERSION`, `TB_MAX_PARALLEL`.

Or from a terminal:
```bash
gh secret set OPENROUTER_API_KEY -R kuldeepz/tinybrains-blog
```

### 5. Cloudflare Worker
Create a fine-grained GitHub token: repo **tinybrains-blog only**, with permissions Contents: read/write, Pull requests: read/write, and Metadata: read. Then:
```bash
cd bot/worker && npm install && npx wrangler login
```
```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN && npx wrangler secret put TELEGRAM_CHAT_ID && npx wrangler secret put TELEGRAM_WEBHOOK_SECRET && npx wrangler secret put GITHUB_TOKEN
```
```bash
npx wrangler deploy
```
Point Telegram at the worker (use the same random string you stored as `TELEGRAM_WEBHOOK_SECRET`):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" -d "url=https://tinybrains-bot.<your-subdomain>.workers.dev/telegram" -d "secret_token=<WEBHOOK_SECRET>" -d 'allowed_updates=["message","callback_query"]'
```

## Privacy
- Chat text and uploads are **never committed**. The workflow reads the Telegram payload from `$GITHUB_EVENT_PATH` and never echoes it or puts it in `env:` (env blocks show up in public Actions logs).
- Drive layout: `conversations/<date>/*.json` (inbound + bot replies) and `uploads/<topic-id>/…`.
- A topic's uploads are deleted when its PR is merged or closed. Conversation logs older than `TB_CONV_RETENTION_DAYS` (default 7) are purged every week.
- **Public:** idea titles and statuses in `ops/topics.json`, and the posts themselves. Don't put anything personal in an idea title.

## Local development
```bash
cd site && npm install && npm run dev
```
```bash
python3 -m venv .venv && .venv/bin/pip install -r agents/requirements.txt
```
```bash
.venv/bin/python -m unittest discover -s tests -t .
```
```bash
OPENROUTER_API_KEY=... TB_NO_PUSH=1 .venv/bin/python -m agents write "How KV caching works" --no-pr
```
```bash
cd bot/worker && npm test
```

Custom domain later: set `site`/`base` in `site/astro.config.mjs`, add `site/public/CNAME`, and update `SITE_URL` in `bot/worker/wrangler.toml` and `TB_SITE_URL`.
