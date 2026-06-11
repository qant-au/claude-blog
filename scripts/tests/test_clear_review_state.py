"""Behavioral tests for scripts/clear_review_state.py (API-over-brand-key)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "clear_review_state.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("clear_review_state", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_clear_posts_clear_review_state():
    mod = _import_helper()
    request_fn = MagicMock(return_value={"cleared": True, "id": "d1"})
    ok = mod.clear_flags(request_fn, "redbridgecyber", "d1", reason=None)
    assert ok is True
    args = request_fn.call_args.args
    assert args[1] == "POST"
    assert args[2] == "/brand/blog/articles/d1/clear-review-state"


def test_clear_records_reason_when_given():
    mod = _import_helper()
    request_fn = MagicMock(return_value={"cleared": True, "id": "d1"})
    mod.clear_flags(request_fn, "redbridgecyber", "d1", reason="image regenerated")
    body = request_fn.call_args.args[3]
    assert body == {"reason": "image regenerated"}


def test_clear_missing_article_returns_false():
    mod = _import_helper()
    qant_api = mod.qant_api
    request_fn = MagicMock(side_effect=qant_api.ApiError(404, "Article not found"))
    ok = mod.clear_flags(request_fn, "redbridgecyber", "nope", reason=None)
    assert ok is False
