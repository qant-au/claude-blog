"""Behavioral tests for scripts/list_pending_rewrites.py row shaping.

Stdlib + pytest only — exercises the pure row builder, no Firestore.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "list_pending_rewrites.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("list_pending_rewrites", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _doc(**extra) -> dict:
    return {
        "title":         "Flagged draft",
        "slug":          "flagged-draft",
        "category":      "ir",
        "author":        {"slug": "adam", "name": "Adam"},
        "body_markdown": "one two three",
        "review_state":  "needs_rewrite",
        **extra,
    }


def test_row_includes_review_targets():
    mod = _import_helper()
    row = mod._row(
        "redbridgecyber", "brands/redbridgecyber/drafts", "d1",
        _doc(review_targets={"content": False, "image": True}),
    )
    assert row["review_targets"] == {"content": False, "image": True}


def test_row_defaults_targets_when_absent():
    """Legacy flagged drafts predate review_targets — default content-only."""
    mod = _import_helper()
    row = mod._row("redbridgecyber", "brands/redbridgecyber/drafts", "d1", _doc())
    assert row["review_targets"] == {"content": True, "image": False}


def test_row_keeps_existing_fields():
    mod = _import_helper()
    row = mod._row("redbridgecyber", "brands/redbridgecyber/drafts", "d1", _doc())
    assert row["brand_slug"] == "redbridgecyber"
    assert row["draft_id"] == "d1"
    assert row["draft_path"] == "brands/redbridgecyber/drafts/d1"
    assert row["slug"] == "flagged-draft"
    assert row["author_slug"] == "adam"
    assert row["word_count"] == 3
