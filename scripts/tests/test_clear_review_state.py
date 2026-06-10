"""Behavioral tests for scripts/clear_review_state.py.

Stdlib + pytest; Firestore client is a MagicMock (the real
google-cloud-firestore module supplies DELETE_FIELD sentinels).
"""

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


def _mock_client(*, draft_exists=True):
    draft_ref = MagicMock()
    draft_ref.get.return_value = MagicMock(exists=draft_exists)
    drafts_col = MagicMock()
    drafts_col.document.return_value = draft_ref
    brand_doc = MagicMock()
    brand_doc.collection.return_value = drafts_col
    brands_col = MagicMock()
    brands_col.document.return_value = brand_doc
    client = MagicMock()
    client.collection.return_value = brands_col
    client._draft_ref = draft_ref
    return client


def test_clears_state_instructions_and_targets():
    from google.cloud import firestore

    mod = _import_helper()
    client = _mock_client()
    ok = mod.clear_flags(client, "redbridgecyber", "d1", reason=None)
    assert ok is True
    written = client._draft_ref.update.call_args.args[0]
    assert written["review_state"] is firestore.DELETE_FIELD
    assert written["review_instructions"] is firestore.DELETE_FIELD
    assert written["review_targets"] is firestore.DELETE_FIELD


def test_clear_records_reason_when_given():
    mod = _import_helper()
    client = _mock_client()
    mod.clear_flags(client, "redbridgecyber", "d1", reason="image regenerated")
    written = client._draft_ref.update.call_args.args[0]
    assert written["review_state_cleared_reason"] == "image regenerated"


def test_clear_returns_false_when_draft_missing():
    mod = _import_helper()
    client = _mock_client(draft_exists=False)
    ok = mod.clear_flags(client, "redbridgecyber", "gone", reason=None)
    assert ok is False
    client._draft_ref.update.assert_not_called()
