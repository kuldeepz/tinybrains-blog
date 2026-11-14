"""Runs one team per topic concurrently, then a shared build test and sequential publishing."""
from __future__ import annotations

import asyncio
import json
import logging

import yaml
from datetime import datetime, timezone

from . import gitops
from .drive import Drive
from .intake import load_private_context
from .llm import LLM, gather_limited, make_llm
from .roles.architect import Architect
from .roles.base import Post
from .roles.designer import Designer
from .roles.editor import Editor
from .roles.head import Head
from .roles.pm import PM
from .roles.publisher import Publisher
from .roles.reviewer import Reviewer
from .roles.tester import Tester, build_site, remove_files, style_issues, write_files
from .roles.writer import Researcher, Writer
from .settings import MAX_PARALLEL, MAX_REVIEW_ROUNDS, POSTS_DIR, RUNS_DIR, ROOT
from .telegram import Telegram, esc
from .topics import Tracker

log = logging.getLogger("tb.orchestrator")


async def team_pipeline(llm: LLM, post: Post, published: list[dict], tg: Telegram, mode: str = "free") -> Post:
    i = post.team.split("-")[-1]
    pm, res, wr = PM(llm, f"PM#{i}"), Researcher(llm, f"Researcher#{i}"), Writer(llm, f"Writer#{i}")
    ed, de, rv, te = Editor(llm, f"Editor#{i}"), Designer(llm, f"Designer#{i}"), Reviewer(llm, f"Reviewer#{i}"), Tester(llm, f"Tester#{i}")
    try:
        await pm.plan(post, published)
        await res.research(post)
        if mode == "senior":
            await Architect(llm, f"Architect#{i}").plan(post)
        await wr.write(post)
        await ed.edit(post)
        await de.design(post)
        reviser = "reviser" if mode == "senior" else "editor"   # Senior: the strongest model applies the review
        best = None
        for rnd in range(MAX_REVIEW_ROUNDS + 1):
            r = await rv.review(post)
            problems = await te.static(post)
            style = style_issues(post)
            if best is None or r["score"] >= best[0]:
                best = (r["score"], post.body, dict(post.meta), dict(post.diagrams), len(post.reviews))
            if r["approved"] and not problems and not style:
                break
            if rnd == MAX_REVIEW_ROUNDS:
                if best[0] > r["score"]:   # revisions made it worse: ship the best-scoring version, not the last one
                    _, post.body, post.meta, post.diagrams, idx = best
                    post.final_review = post.reviews[idx - 1]
                    post.note("Head", f"kept round {idx} version (score {best[0]}) over the final one (score {r['score']})")
                post.note("Head", f"review rounds exhausted (score {post.review.get('score')}); sending to owner with notes")
                break
            if style:
                post.note(te.name, f"style issues: {style}")
            await ed.edit(post, (r.get("required_changes") or r.get("issues") or []) + problems + style, role=reviser)
        if te_problems := await te.static(post):
            raise RuntimeError(f"unfixable: {te_problems}")
        tg.send(f"🧩 {esc(post.team)} finished <b>{esc(post.meta.get('title', post.brief.get('title', '')))}</b> "
                f"(review {post.review.get('score', '?')}/10)")
    except Exception as e:  # noqa: BLE001 - isolate team failures
        post.ok, post.error = False, f"{type(e).__name__}: {e}"
        post.note("Head", f"team failed: {post.error}")
    return post


def _live_frontmatter(slug: str) -> dict:
    """date/version of the live post, so a rewrite keeps its original date and bumps the version."""
    f = POSTS_DIR / f"{slug}.mdx"
    if not slug or not f.exists():
        return {}
    try:
        fm = yaml.safe_load(f.read_text().split("---", 2)[1]) or {}
    except Exception:  # noqa: BLE001
        return {}
    return {"date": fm.get("date"), "version": fm.get("version", 1)}


async def run_write(topic_ids: list[str], *, open_pr: bool = True, build: bool = True, rewrite: bool = False) -> list[Post]:
    llm, tg, drive = make_llm(), Telegram(), Drive()
    head = Head(llm)

    def start(t: Tracker):
        out = []
        for tid in topic_ids:
            topic = t.get(tid)
            if not topic:
                continue
            if rewrite:
                if topic["status"] == "published" or (topic["status"] == "in_progress" and topic.get("rewriting")):
                    t.set(topic, "in_progress", rewriting=True)
                    out.append(dict(topic))
            elif topic["status"] in ("idea", "queued", "rejected", "in_progress") and not topic.get("rewriting"):
                t.set(topic, "in_progress")
                out.append(dict(topic))
        mine = {o["id"] for o in out}
        return out, [dict(p) for p in t.by_status("published") if p["id"] not in mine]

    topics, published = gitops.sync_tracker(start, f"tracker: start {', '.join(topic_ids)}")
    if not topics:
        tg.send("Nothing to rewrite: /rewrite only works on published topics (see /topics)." if rewrite
                else "Nothing to write: those topics are unknown or already in review/published.")
        return []
    mode = "free"
    if llm.approver is not None:
        mode = await llm.approver.choose_mode([f"{t['id']} {t['title']}" for t in topics], llm.azure_ready)
    tg.send(f"🚀 [{mode}] {esc(head.team_plan(len(topics), MAX_PARALLEL, mode))}\n"
            + "\n".join(f"• {t['id']} {esc(t['title'])}" for t in topics))

    posts = []
    for n, topic in enumerate(topics, 1):
        ctx = await load_private_context(drive, llm, topic) if topic.get("private_files") else ""
        post = Post(topic=topic, team=f"team-{n}", context=ctx)
        if topic.get("rewriting"):
            post.rewrite_of = {"slug": topic.get("slug"), **_live_frontmatter(topic.get("slug", ""))}
        posts.append(post)
    await gather_limited(MAX_PARALLEL, [team_pipeline(llm, p, published, tg, mode) for p in posts])

    # dedupe slugs between parallel teams
    seen: set[str] = set()
    for p in posts:
        while p.ok and p.slug in seen:
            p.slug += "-2"
        seen.add(p.slug)

    ok = [p for p in posts if p.ok]
    if build and ok:
        tester = Tester(llm, "Tester")
        for p in ok:
            write_files(p)
        passed, out = await build_site()
        if not passed:
            for p in ok:
                if p.slug in out:
                    await tester.fix_build(p, out)
                    write_files(p)
            passed, out = await build_site()
        if not passed:  # isolate: drop the posts named in the error, else drop all
            culprits = [p for p in ok if p.slug in out] or ok
            for p in culprits:
                p.ok, p.error = False, "site build failed: " + out[-400:]
                remove_files(p)
        for p in posts:
            remove_files(p)  # publisher rewrites the files onto each post branch

    pub = Publisher(llm, tg, "Publisher", open_pr=open_pr)
    for p in posts:
        if p.ok:
            try:
                await pub.publish(p)
            except Exception as e:  # noqa: BLE001
                p.ok, p.error = False, f"publish failed: {e}"

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_file = RUNS_DIR / f"{run_id}.json"
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_file.write_text(json.dumps({
        "run": run_id, "mode": mode, "usage": llm.usage,
        "posts": [{"topic": p.topic["id"], "slug": p.slug, "ok": p.ok, "pr": p.pr, "error": p.error[:300],
                   "scores": [r.get("score") for r in p.reviews],
                   "reviews": [{"score": r.get("score"), "rubric": r.get("rubric"),
                                "issues": (r.get("required_changes") or r.get("issues") or [])[:10]} for r in p.reviews],
                   "log": p.log} for p in posts],
    }, indent=2) + "\n")

    def finish(t: Tracker):
        for p in posts:
            topic = t.get(p.topic["id"])
            if not topic:
                continue
            if p.ok and (p.pr or not open_pr):
                t.set(topic, "in_review" if p.pr else "in_progress", slug=p.slug, pr=p.pr,
                      title=p.meta.get("title") or topic["title"])
            elif topic.get("rewriting"):   # failed rewrite: the live post stays as it is
                t.set(topic, "published", rewriting=False)
            else:
                t.set(topic, "idea", notes=(topic.get("notes", "") + f"\n[last run failed: {p.error[:150]}]").strip()[:1000])

    gitops.sync_tracker(finish, f"tracker: run {run_id}", [str(run_file.relative_to(ROOT))])
    tg.send(esc(Head.summary(posts)))
    return posts
