"""Behavioral tests for scripts/copy_draft_image.py.

Stdlib + pytest only. Firestore is a MagicMock.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "copy_draft_image.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("copy_draft_image", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


SRC_DOC = {
    "data":       "aGVsbG8td2VicA==",
    "mime":       "image/webp",
    "width":      1200,
    "height":     630,
    "size_bytes": 16,
    "kind":       "hero",
    "state":      "approved",
    "source":     "banana",
}


# ---------------------------------------------------------------------------
# build_copied_doc — pure core
# ---------------------------------------------------------------------------


def test_build_copied_doc_sets_source_and_preserves_state():
    mod = _import_helper()
    doc = mod.build_copied_doc(SRC_DOC, "orig_draft_42")
    assert doc["source"] == "copied:orig_draft_42"
    assert doc["state"] == "approved"          # operator approval survives the copy
    assert doc["data"] == SRC_DOC["data"]
    assert doc["mime"] == "image/webp"
    assert "createdAt" not in doc              # stamped fresh at write time
    assert "reviewedAt" not in doc             # review stamp belongs to the original


# ---------------------------------------------------------------------------
# copy — against a mocked client
# ---------------------------------------------------------------------------


def _mock_client(*, src_doc=None):
    """Two draft refs under the same brand; the helper navigates
    brands/{slug}/drafts/{id}/images/hero for both source and target."""
    refs: dict[str, MagicMock] = {}

    def _draft_ref(draft_id):
        if draft_id not in refs:
            image_ref = MagicMock()
            snap = MagicMock()
            if draft_id == "src" and src_doc is not None:
                snap.exists = True
                snap.to_dict.return_value = dict(src_doc)
            else:
                snap.exists = False
            image_ref.get.return_value = snap
            images_col = MagicMock()
            images_col.document.return_value = image_ref
            ref = MagicMock()
            ref.collection.return_value = images_col
            ref._image_ref = image_ref
            refs[draft_id] = ref
        return refs[draft_id]

    drafts_col = MagicMock()
    drafts_col.document.side_effect = _draft_ref

    brand_doc = MagicMock()
    brand_doc.collection.return_value = drafts_col

    brands_col = MagicMock()
    brands_col.document.return_value = brand_doc

    client = MagicMock()
    client.collection.return_value = brands_col
    client._refs = refs
    return client


def test_copy_noop_when_source_image_absent():
    mod = _import_helper()
    client = _mock_client(src_doc=None)
    result = mod.copy_image(client, "redbridgecyber", "src", "dst")
    assert result is None
    # nothing written to the target
    assert "dst" not in client._refs or \
        not client._refs["dst"]._image_ref.set.called


def test_copy_copies_to_target():
    mod = _import_helper()
    client = _mock_client(src_doc=SRC_DOC)
    result = mod.copy_image(client, "redbridgecyber", "src", "dst")
    assert result == "brands/redbridgecyber/drafts/dst/images/hero"
    written = client._refs["dst"]._image_ref.set.call_args.args[0]
    assert written["source"] == "copied:src"
    assert written["state"] == "approved"
    assert written["data"] == SRC_DOC["data"]
    assert "createdAt" in written
