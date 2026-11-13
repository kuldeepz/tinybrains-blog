"""Command line entry point (used locally and by GitHub Actions).

  python -m agents.cli idea "title" [--notes ...]     store an idea only (no writing)
  python -m agents.cli status                          tracker summary
  python -m agents.cli write T001 T002 | "new topic"   run agent teams (parallel when >1)
         [--no-pr] [--no-build]
  python -m agents.cli event payload.json              handle a Telegram event dispatched by the worker
  python -m agents.cli finalize --pr 12 --merged true  PR closed: mark published/rejected, purge private files
  python -m agents.cli purge [--days 7]                delete old conversation logs from Drive
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import mimetypes
import re
import sys

from . import gitops
from .drive import Drive
from .intake import describe, notify_unsupported, route, summarize_upload
from .llm import make_llm
from .orchestrator import run_write
from .roles.head import Head
from .settings import SITE_URL, env
from .telegram import Telegram, esc
from .topics import Tracker

log = logging.getLogger("tb.cli")
ID_RE = re.compile(r"^T\d{3,}$", re.I)


def add_ideas(items: list[dict], source: str, status: str = "idea", private: bool = False) -> list[dict]:
    def mut(t: Tracker):
        out = []
        for it in items:
            dup = t.similar(it["title"], 0.6)
            topic = t.add(it["title"], notes=it.get("notes", ""), tags=it.get("tags", []), source=source, status=status)
            topic["private_files"] = private
            out.append((dict(topic), [(round(s, 2), d["id"], d["title"], d["status"]) for s, d in dup[:2]]))
        return out
    return gitops.sync_tracker(mut, f"tracker: add {len(items)} {status}(s)")


def fmt_added(added) -> str:
    lines = []
    for topic, dups in added:
        lines.append(f"💡 Stored <b>{topic['id']}</b> {esc(topic['title'])}")
        for s, did, dt, dst in dups:
            lines.append(f"   ↳ similar to {did} ({dst}): {esc(dt)}")
    return "\n".join(lines)


async def write_from_text(text: str, tg: Telegram) -> None:
    ids = [w.upper() for w in re.split(r"[\s,]+", text.strip()) if ID_RE.match(w)]
    if not ids:
        topics = await Head(make_llm()).split(text)
        if not topics:
            tg.send("I couldn't find a topic in that. Try /write <topic>.")
            return
        ids = [t["id"] for t, _ in add_ideas(topics, "telegram", status="queued")]
    await run_write(ids)


async def handle_event(payload: dict) -> None:
    tg, drive = Telegram(payload.get("chat_id")), Drive()
    tg.on_send = lambda txt: drive.log_event("outbound", {"text": txt})
    kind, text = payload.get("kind", "message"), (payload.get("text") or "").strip()
    drive.log_event("inbound", {"kind": kind, "text": text, "file": (payload.get("file") or {}).get("name")})

    if kind == "write":
        await write_from_text(text, tg)
        return

    if kind == "upload":
        f = payload["file"]
        tg.typing()
        data, fname = tg.download(f["id"])
        name = f.get("name") or fname
        mime = f.get("mime") or mimetypes.guess_type(name)[0] or ""
        llm = make_llm()
        content = await describe(llm, name, data, mime)
        if not content.strip():
            notify_unsupported(tg, name)
            return
        idea = await summarize_upload(llm, content, text)
        r = await route(llm, text) if text else {"intent": "store_idea"}
        status = "queued" if r["intent"] == "write_now" else "idea"
        added = add_ideas([{"title": idea.get("title") or name, "notes": idea.get("notes", ""), "tags": idea.get("tags", [])}],
                          "upload", status=status, private=drive.enabled)
        topic = added[0][0]
        if drive.enabled:
            drive.upload(f"uploads/{topic['id']}", name, data, mime or "application/octet-stream")
            where = "saved privately to your Google Drive"
        else:
            where = "⚠️ Drive not configured, the file was not kept"
        tg.send(fmt_added(added) + f"\n📎 {esc(name)} {where}.")
        if status == "queued":
            await run_write([topic["id"]])
        return

    # free text
    llm = make_llm()
    r = await route(llm, text)
    if r["intent"] == "store_idea" and r["topics"]:
        tg.send(fmt_added(add_ideas(r["topics"], "telegram")))
    elif r["intent"] == "write_now" and r["topics"]:
        ids = [t["id"] for t, _ in add_ideas(r["topics"], "telegram", status="queued")]
        await run_write(ids)
    elif r["intent"] == "status":
        tg.send(esc(Tracker().summary()))
    else:
        tg.send(esc(await Head(llm).chat(text, Tracker().summary())))


def finalize(pr: int, merged: bool) -> None:
    tg, drive = Telegram(), Drive()
    holder: dict = {}

    def mut(t: Tracker):
        topic = t.by_pr(pr)
        if not topic:
            return
        if merged:
            t.set(topic, "published", url=f"{SITE_URL}/posts/{topic['slug']}/")
        else:
            t.set(topic, "rejected")
        holder.update(topic)

    gitops.sync_tracker(mut, f"tracker: PR #{pr} {'published' if merged else 'rejected'}")
    if not holder:
        return
    purged = drive.delete_path(f"uploads/{holder['id']}") if holder.get("private_files") else False
    if merged:
        tg.send(f"🎉 Published <b>{esc(holder['title'])}</b>\n{holder['url']}\n(live in ~2 min once Pages deploys)"
                + ("\n🧹 Private uploads deleted from Drive." if purged else ""))
    else:
        tg.send(f"🗑 Rejected {holder['id']} {esc(holder['title'])}. Send /write {holder['id']} to try again."
                + ("\n🧹 Private uploads deleted from Drive." if purged else ""))


async def check_models() -> int:
    """Ping every configured model with a tiny prompt (a fraction of a cent on Azure). Names stay out of the report."""
    from .llm import AZURE_TIERS, LLM, azure_deployment, load_role
    import yaml
    from .settings import MODELS_FILE

    llm = LLM()
    lines, ok = [], True
    msgs = [{"role": "user", "content": "Reply with exactly: OK"}]
    tiers = {"mini (writer)": "mini", "architect (Senior brief + review)": "architect"}
    for label, tier in tiers.items():
        own = env(AZURE_TIERS[tier][0])
        if not llm._az or not azure_deployment(tier):
            lines.append(f"⚪ Azure {label}: not configured"); ok = ok and tier != "mini"; continue
        kw = dict(model=azure_deployment(tier), messages=msgs, max_completion_tokens=4000, reasoning_effort="low")
        try:
            try:
                r = await llm._az.chat.completions.create(**kw)
            except Exception as e:
                if "reasoning_effort" not in str(e):
                    raise
                kw.pop("reasoning_effort"); r = await llm._az.chat.completions.create(**kw)
            reply = (r.choices[0].message.content or "").strip()[:20]
            note = "" if own else " (using the mini deployment)"
            lines.append(f"✅ Azure {label}: replied '{esc(reply)}'{note}")
        except Exception as e:
            ok = False
            lines.append(f"❌ Azure {label}: {esc(type(e).__name__)}: {esc(str(e)[:200])}")
    free = []
    for rc in yaml.safe_load(MODELS_FILE.read_text())["roles"]:
        for m in load_role(rc).free:
            if m not in free:
                free.append(m)
    for m in free:
        if not llm._or:
            lines.append("⚪ OpenRouter: not configured"); break
        try:
            r = await llm._or.chat.completions.create(model=m, messages=msgs, max_tokens=200)
            lines.append(f"✅ {esc(m)}: '{esc((r.choices[0].message.content or '').strip()[:20])}'")
        except Exception as e:
            lines.append(f"⚠️ {esc(m)}: {esc(str(e)[:120])}")
    report = "🔌 <b>Model check</b>\n" + "\n".join(lines)
    print(report)
    try:
        Telegram().send(report)
    except Exception:
        pass
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=env("TB_LOG", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for noisy in ("httpx", "googleapiclient", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("idea"); a.add_argument("title"); a.add_argument("--notes", default="")
    sub.add_parser("status")
    sub.add_parser("check")
    w = sub.add_parser("write"); w.add_argument("items", nargs="+"); w.add_argument("--no-pr", action="store_true")
    w.add_argument("--no-build", action="store_true")
    e = sub.add_parser("event"); e.add_argument("payload")
    f = sub.add_parser("finalize"); f.add_argument("--pr", type=int, required=True); f.add_argument("--merged", default="true")
    p = sub.add_parser("purge"); p.add_argument("--days", type=int, default=int(env("TB_CONV_RETENTION_DAYS", "7")))
    args = ap.parse_args(argv)

    if args.cmd == "idea":
        for topic, dups in add_ideas([{"title": args.title, "notes": args.notes}], "cli"):
            print(f"stored {topic['id']}: {topic['title']}" + "".join(f"\n  similar: {d}" for d in dups))
    elif args.cmd == "status":
        print(Tracker().summary())
    elif args.cmd == "check":
        return asyncio.run(check_models())
    elif args.cmd == "write":
        ids = [i.upper() for i in args.items if ID_RE.match(i)]
        titles = [i for i in args.items if not ID_RE.match(i)]
        if titles:
            ids += [t["id"] for t, _ in add_ideas([{"title": x} for x in titles], "cli", status="queued")]
        posts = asyncio.run(run_write(ids, open_pr=not args.no_pr, build=not args.no_build))
        print(Head.summary(posts))
        return 0 if posts and all(p.ok for p in posts) else 1
    elif args.cmd == "event":
        with open(args.payload) as fh:
            asyncio.run(handle_event(json.load(fh)))
    elif args.cmd == "finalize":
        finalize(args.pr, args.merged.lower() == "true")
    elif args.cmd == "purge":
        print(f"purged {Drive().purge_conversations(args.days)} day-folders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
