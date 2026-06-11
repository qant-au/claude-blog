"""Behavioral tests for scripts/delete_inbox_draft.py (API-over-brand-key)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "delete_inbox_draft.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("delete_inbox_draft", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_delete_issues_api_delete():
    mod = _import_helper()
    request_fn = MagicMock(return_value=None)
    result = mod.delete_draft(request_fn, "redbridgecyber", "d1")
    assert result["deleted"] is True
    args = request_fn.call_args.args
    assert args[1] == "DELETE"
    assert args[2] == "/brand/blog/articles/d1"
    assert request_fn.call_args.kwargs.get("none_on_404") is True


def test_delete_is_idempotent_on_missing_article():
    mod = _import_helper()
    # none_on_404=True means the helper returns None for a missing article;
    # the delete still reports success (idempotent cleanup).
    request_fn = MagicMock(return_value=None)
    result = mod.delete_draft(request_fn, "redbridgecyber", "already-gone")
    assert result["deleted"] is True
