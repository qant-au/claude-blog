"""Behavioral tests for scripts/list_approved_articles.py (API-over-brand-key)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "list_approved_articles.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("list_approved_articles", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _article(**over):
    d = {
        "id": "bpost_1",
        "slug": "test-post",
        "title": "Test Post",
        "category": "security",
        "kind": "perspective",
        "status": "approved",
        "author": {"slug": "adam-burgess", "name": "Adam Burgess"},
        "hero_image_url": "https://cdn/x.webp",
        "body_markdown": "one two three",
        "metadata": {},
    }
    d.update(over)
    return d


def test_rows_hit_the_approved_endpoint_and_carry_kind():
    mod = _import_helper()
    request_fn = MagicMock(return_value={"items": [_article()]})
    rows = mod.query_brand(request_fn, "redbridgecyber")
    assert request_fn.call_args.args[1] == "GET"
    assert request_fn.call_args.args[2] == "/brand/blog/approved"
    row = rows[0]
    assert row["brand_slug"] == "redbridgecyber"
    assert row["draft_id"] == "bpost_1"
    assert row["slug"] == "test-post"
    assert row["title"] == "Test Post"
    assert row["author_slug"] == "adam-burgess"
    assert row["category"] == "security"
    assert row["kind"] == "perspective"
    assert row["status"] == "approved"
    assert row["hero_image_url"] == "https://cdn/x.webp"
    assert row["word_count"] == 3


def test_kind_defaults_to_spoke_for_legacy_drafts():
    mod = _import_helper()
    art = _article()
    art.pop("kind")
    request_fn = MagicMock(return_value={"items": [art]})
    rows = mod.query_brand(request_fn, "redbridgecyber")
    assert rows[0]["kind"] == "spoke"
