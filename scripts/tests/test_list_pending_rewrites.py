"""Behavioral tests for scripts/list_pending_rewrites.py (API-over-brand-key)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "list_pending_rewrites.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("list_pending_rewrites", HELPER)
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
        "author": {"slug": "adam-burgess", "name": "Adam Burgess"},
        "body_markdown": "one two three",
        "metadata": {
            "review_state": "needs_rewrite",
            "review_instructions": "Fix intro",
            "review_targets": {"content": True, "image": False},
        },
    }
    d.update(over)
    return d


def test_rows_match_legacy_queue_shape():
    mod = _import_helper()
    request_fn = MagicMock(return_value={"items": [_article()]})
    rows = mod.query_brand(request_fn, "redbridgecyber")
    assert request_fn.call_args.args[1] == "GET"
    assert request_fn.call_args.args[2] == "/brand/blog/rewrites"
    row = rows[0]
    assert row["brand_slug"] == "redbridgecyber"
    assert row["draft_id"] == "bpost_1"
    assert row["slug"] == "test-post"
    assert row["title"] == "Test Post"
    assert row["author_slug"] == "adam-burgess"
    assert row["category"] == "security"
    assert row["review_state"] == "needs_rewrite"
    assert row["review_targets"] == {"content": True, "image": False}
    assert row["word_count"] == 3


def test_rows_default_targets_content_only_for_legacy_flags():
    mod = _import_helper()
    art = _article()
    art["metadata"] = {"review_state": "needs_rewrite"}
    request_fn = MagicMock(return_value={"items": [art]})
    rows = mod.query_brand(request_fn, "redbridgecyber")
    assert rows[0]["review_targets"] == {"content": True, "image": False}
