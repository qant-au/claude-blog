"""Behavioral tests for scripts/submit_draft.py (API-over-brand-key)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "submit_draft.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("submit_draft", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _payload():
    return {
        "title": "Test Post",
        "slug": "test-post",
        "category": "security",
        "target_keyword": "kw",
        "author": {"slug": "adam-burgess", "name": "Adam Burgess", "bio": "leak"},
        "brand_slug": "redbridgecyber",
        "contentType": "blog_post",
        "og": {"title": None},
        "body_markdown": "# Body",
        "flow_score": 90,
        "metadata": {"word_count": 2},
    }


def test_submit_posts_article_with_author_slug():
    mod = _import_helper()
    request_fn = MagicMock(return_value={"id": "bpost_abc", "status": "draft"})
    result = mod.submit(request_fn, "redbridgecyber", "adam-burgess", _payload())

    args = request_fn.call_args.args
    assert args[0] == "redbridgecyber"
    assert args[1] == "POST"
    assert args[2] == "/brand/blog/articles"
    body = request_fn.call_args.kwargs.get("body") or request_fn.call_args.args[3]
    assert body["author_slug"] == "adam-burgess"
    assert "author" not in body          # author dict stripped — server joins name
    assert "brand_slug" not in body      # brand comes from the key
    assert "contentType" not in body
    assert body["metadata"]["submitted_by"]
    assert result["draft_id"] == "bpost_abc"


def test_submit_maps_unknown_author_404_to_value_error():
    mod = _import_helper()
    qant_api = mod.qant_api
    request_fn = MagicMock(side_effect=qant_api.ApiError(404, "Author 'x' not found"))
    with pytest.raises(ValueError, match="Axiom"):
        mod.submit(request_fn, "redbridgecyber", "x", _payload())
