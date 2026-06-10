"""Behavioral tests for scripts/delete_inbox_draft.py (images cascade).

Stdlib + pytest only. Firestore is a MagicMock.
"""

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


def _mock_client(*, draft_exists=True, image_snaps=None):
    images_col = MagicMock()
    images_col.stream.return_value = iter(image_snaps or [])

    draft_ref = MagicMock()
    draft_ref.get.return_value = MagicMock(exists=draft_exists)
    draft_ref.collection.return_value = images_col

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


def _image_snap():
    snap = MagicMock()
    snap.reference = MagicMock()
    return snap


def test_delete_removes_images_subcollection_first():
    mod = _import_helper()
    img = _image_snap()
    client = _mock_client(draft_exists=True, image_snaps=[img])
    result = mod.delete_draft(client, "redbridgecyber", "d1")
    assert result == "deleted"
    img.reference.delete.assert_called_once()
    client._draft_ref.delete.assert_called_once()


def test_delete_still_idempotent_when_absent():
    mod = _import_helper()
    client = _mock_client(draft_exists=False)
    result = mod.delete_draft(client, "redbridgecyber", "gone")
    assert result == "already_absent"
    client._draft_ref.delete.assert_not_called()


def test_delete_heals_orphaned_images_when_parent_absent():
    """Subcollections survive parent deletion in Firestore — the sweep must
    run even when the draft doc itself is already gone."""
    mod = _import_helper()
    img = _image_snap()
    client = _mock_client(draft_exists=False, image_snaps=[img])
    result = mod.delete_draft(client, "redbridgecyber", "gone")
    assert result == "already_absent"
    img.reference.delete.assert_called_once()
