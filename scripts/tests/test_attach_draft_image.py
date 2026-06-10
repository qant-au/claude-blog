"""Behavioral tests for scripts/attach_draft_image.py.

Stdlib + pytest only. No network — Firestore is a MagicMock; env-handling
is exercised via subprocess (matching test_load_brand_context.py style).
"""

from __future__ import annotations

import base64
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "attach_draft_image.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("attach_draft_image", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


WEBP_BYTES = b"RIFF....WEBPVP8 fake-webp-payload"


# ---------------------------------------------------------------------------
# build_image_doc — pure core
# ---------------------------------------------------------------------------


def test_build_image_doc_shape():
    mod = _import_helper()
    doc = mod.build_image_doc(
        WEBP_BYTES, mime="image/webp", width=1200, height=630, source="banana",
    )
    assert doc["mime"] == "image/webp"
    assert doc["width"] == 1200
    assert doc["height"] == 630
    assert doc["size_bytes"] == len(WEBP_BYTES)
    assert doc["kind"] == "hero"
    assert doc["state"] == "generated"
    assert doc["source"] == "banana"
    # data round-trips
    assert base64.b64decode(doc["data"]) == WEBP_BYTES


def test_build_image_doc_rejects_oversize_payload():
    mod = _import_helper()
    # 900 KiB of base64 ≈ 675 KiB raw; go comfortably past it.
    big = b"\xff" * 800_000
    with pytest.raises(mod.PayloadTooLarge):
        mod.build_image_doc(
            big, mime="image/webp", width=1200, height=630, source="banana",
        )


def test_build_image_doc_accepts_explicit_state():
    mod = _import_helper()
    doc = mod.build_image_doc(
        WEBP_BYTES, mime="image/webp", width=1200, height=630,
        source="copied:abc123", state="approved",
    )
    assert doc["state"] == "approved"
    assert doc["source"] == "copied:abc123"


# ---------------------------------------------------------------------------
# attach — write path against a mocked client
# ---------------------------------------------------------------------------


def _mock_client(*, draft_exists=True):
    image_ref = MagicMock()
    images_col = MagicMock()
    images_col.document.return_value = image_ref

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
    client._image_ref = image_ref
    return client


def test_attach_writes_hero_doc():
    mod = _import_helper()
    client = _mock_client()
    doc = mod.build_image_doc(
        WEBP_BYTES, mime="image/webp", width=1200, height=630, source="banana",
    )
    path = mod.attach(client, "redbridgecyber", "draft_001", doc)
    assert path == "brands/redbridgecyber/drafts/draft_001/images/hero"
    client._image_ref.set.assert_called_once()
    written = client._image_ref.set.call_args.args[0]
    assert written["mime"] == "image/webp"
    assert "createdAt" in written


def test_attach_raises_when_draft_missing():
    mod = _import_helper()
    client = _mock_client(draft_exists=False)
    doc = mod.build_image_doc(
        WEBP_BYTES, mime="image/webp", width=1200, height=630, source="banana",
    )
    with pytest.raises(mod.DraftNotFound):
        mod.attach(client, "redbridgecyber", "nope", doc)
    client._image_ref.set.assert_not_called()


# ---------------------------------------------------------------------------
# main — env handling via subprocess
# ---------------------------------------------------------------------------


def test_main_exit_2_when_env_missing(tmp_path: Path):
    img = tmp_path / "hero.webp"
    img.write_bytes(WEBP_BYTES)
    proc = subprocess.run(
        [sys.executable, str(HELPER),
         "--brand-slug", "redbridgecyber", "--draft-id", "d1",
         "--image", str(img), "--mime", "image/webp",
         "--width", "1200", "--height", "630", "--source", "banana"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 2
    assert "QANT_BLOG_DRAFTS" in proc.stderr
