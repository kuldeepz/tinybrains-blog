"""Paths and environment settings."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("TB_ROOT", Path(__file__).resolve().parent.parent))
SITE = ROOT / "site"
POSTS_DIR = SITE / "src" / "content" / "posts"
COVERS_DIR = SITE / "public" / "covers"
TOPICS_FILE = ROOT / "ops" / "topics.json"
RUNS_DIR = ROOT / "ops" / "runs"
MODELS_FILE = Path(__file__).resolve().parent / "models.yaml"

SITE_URL = os.environ.get("TB_SITE_URL", "https://kuldeepz.github.io/tinybrains-blog")
REPO = os.environ.get("GITHUB_REPOSITORY", "kuldeepz/tinybrains-blog")
MAX_PARALLEL = int(os.environ.get("TB_MAX_PARALLEL", "4"))
MAX_REVIEW_ROUNDS = int(os.environ.get("TB_MAX_REVIEW_ROUNDS", "2"))
AUTHOR = os.environ.get("TB_AUTHOR", "Kuldeep Rao")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default
