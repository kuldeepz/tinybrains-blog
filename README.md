# tinybrains.ai

An AI-engineering blog written by a team of AI agents that you drive from Telegram.

- **Site:** https://kuldeepz.github.io/tinybrains-blog (Astro, GitHub Pages)
- **Bot:** Telegram → Cloudflare Worker → GitHub Actions agent teams → PR → you approve → live
- **LLMs:** OpenRouter **free models only**, and your **Azure OpenAI** deployments for paid work. Every `/write` asks you to choose **🏛 Senior / 💡 Mini / 🆓 Free** in Telegram. Nothing on Azure runs without your tap; no answer in 30 min = Free
- **Quality:** a one-time senior-architect playbook (`agents/playbook/senior-architect.md`) is followed by every writer, editor and reviewer. In Senior mode, your strongest Azure model also writes a per-post *architect brief* that the mini model executes
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

## One-time setup (browser only — nothing runs on your computer)

Where things run: the **Telegram bot** runs on Cloudflare Workers; the **agent teams and the site build** run on GitHub Actions; the **site** is served by GitHub Pages. All secrets go in **GitHub → repo → Settings → Secrets and variables → Actions → New repository secret**.

### Step 1 — Telegram (≈3 min)
1. In Telegram open **@BotFather** → `/newbot` → pick a name → copy the token → secret **`TELEGRAM_BOT_TOKEN`**.
2. Open **@userinfobot** → it replies with your numeric id → secret **`TELEGRAM_CHAT_ID`**. (The bot answers only this id.)

### Step 2 — LLM keys (≈5 min)

| Mode | Architect brief | Writer / Editor / Designer / Researcher | Reviewer | PM, Router, Tester, Vision |
|---|---|---|---|---|
| 🏛 Senior | Azure `ARCHITECT` deployment | Azure mini | Azure `ARCHITECT` deployment | free |
| 💡 Mini | none | Azure mini | free (Gemma: a different model family) | free |
| 🆓 Free | none | free (Nemotron Ultra / ERNIE) | free | free |

Free models are used as fallback when Azure errors; in Free mode, if the free models fail, the bot asks before using Azure.

1. openrouter.ai → Keys → Create → secret **`OPENROUTER_API_KEY`** (only free models are used; a little credit raises the free-tier daily limit and pays for web search).
2. Azure portal → your Azure OpenAI resource → Keys and Endpoint:
   - secret **`AZURE_OPENAI_ENDPOINT`** (e.g. `https://myres.openai.azure.com`)
   - secret **`AZURE_OPENAI_API_KEY`**
   - **Variables** tab:
     - **`AZURE_OPENAI_DEPLOYMENT`** = your **mini** deployment name (e.g. `gpt-5-mini`): writes the posts
     - **`AZURE_OPENAI_DEPLOYMENT_ARCHITECT`** = your **strongest** deployment (e.g. `gpt-5`): writes the brief and reviews in Senior mode (falls back to the mini one if unset)
     - optional `AZURE_OPENAI_DEPLOYMENT_SMALL` (cheapest, for helper roles) and `AZURE_OPENAI_API_VERSION` (default `2024-10-21`)

### Step 3 — GitHub token for the bot (≈2 min)
github.com → Settings → Developer settings → **Fine-grained tokens** → Generate:
- Repository access: **Only select repositories → tinybrains-blog**
- Permissions: **Contents: Read and write**, **Pull requests: Read and write** (Metadata read is automatic)
- Copy → secret **`BOT_GITHUB_PAT`** (GitHub doesn't allow secret names starting with `GITHUB_`)

### Step 4 — Cloudflare (≈4 min)
1. dash.cloudflare.com → sign up / log in (the free plan is enough).
2. Open **Workers & Pages** once and accept the free **workers.dev subdomain** it offers.
3. Copy your **Account ID** (right sidebar on Workers & Pages) → secret **`CLOUDFLARE_ACCOUNT_ID`**.
4. My Profile → **API Tokens** → Create Token → template **"Edit Cloudflare Workers"** → Continue → Create → secret **`CLOUDFLARE_API_TOKEN`**.

### Step 5 — Google Drive for private data (≈8 min), pick ONE
**A. You have Google Workspace (Shared Drives available)**: service account
1. console.cloud.google.com → new project → APIs & Services → **Enable "Google Drive API"**.
2. IAM & Admin → Service Accounts → Create → Keys → Add key → JSON (downloads a file; open it, copy all text) → secret **`GDRIVE_SA_JSON`**.
3. In Drive create a **Shared Drive** → a folder inside it → Share it with the service account email as **Content manager** → copy the folder id from the URL (`…/folders/<THIS>`) → secret **`GDRIVE_FOLDER_ID`**.

**B. Personal Gmail / My Drive**: OAuth refresh token (all in the browser)
1. console.cloud.google.com → new project → **Enable "Google Drive API"** → OAuth consent screen (External, add yourself as test user) → Credentials → Create **OAuth client ID** → type *Web application* → Authorized redirect URI `https://developers.google.com/oauthplayground` → copy id/secret → secrets **`GDRIVE_CLIENT_ID`**, **`GDRIVE_CLIENT_SECRET`**.
2. Open developers.google.com/oauthplayground → ⚙️ → "Use your own OAuth credentials" (paste id/secret) → scope `https://www.googleapis.com/auth/drive` → Authorize → Exchange code → copy **Refresh token** → secret **`GDRIVE_REFRESH_TOKEN`**. (Publish the consent screen to "In production", otherwise the token expires after 7 days.)
3. Create a folder in My Drive → copy its id from the URL → secret **`GDRIVE_FOLDER_ID`**.

### Step 6 — Turn it on (≈1 min)
GitHub → **Actions** → **"Deploy Telegram bot (Cloudflare Worker)"** → **Run workflow**.
It deploys the Worker, stores its secrets in Cloudflare, generates the webhook secret and registers the webhook with Telegram. Your bot then messages you *"tinybrains bot deployed"*. Send `/help`.

### Step 7 — First test
1. `/idea Speculative decoding explained`: the reply includes T001, and `ops/topics.json` gets a commit. No post is written.
2. `/write T001`: watch **Actions → Agents**. After about 5–15 min a draft arrives in Telegram with ✅/❌.
3. Tap ✅: the post appears on the site about 2 minutes later.

Optional tuning (Variables tab): `TB_MAX_PARALLEL` (default 4 teams at once), `TB_APPROVAL_TIMEOUT` (seconds, default 1800), and `TB_REVIEW_MIN` (reviewer pass score, default 9), and per-role overrides such as `MODEL_WRITER_FREE` = `nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-31b-it:free` (only `:free` ids are accepted) or `MODEL_REVIEWER_AZURE` = `mini|architect|small`. `TB_BOT_URL` (the Worker URL) must be set for paid-model approval to work.

## Privacy
- Chat text and uploads are **never committed**. The workflow reads the Telegram payload from `$GITHUB_EVENT_PATH` and never echoes it or puts it in `env:` (env blocks show up in public Actions logs).
- Drive layout: `conversations/<date>/*.json` (inbound + bot replies) and `uploads/<topic-id>/…`.
- A topic's uploads are deleted when its PR is merged or closed. Conversation logs older than `TB_CONV_RETENTION_DAYS` (default 7) are purged every week.
- **Public:** idea titles and statuses in `ops/topics.json`, and the posts themselves. Don't put anything personal in an idea title.

## Local development (optional, for code changes only)
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
