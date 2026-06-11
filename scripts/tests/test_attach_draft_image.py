"""Behavioral tests for scripts/attach_draft_image.py (API-over-brand-key)."""

from __future__ import annotations

import base64
import importlib.util
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


def test_build_image_doc_encodes_base64_and_sizes():
    mod = _import_helper()
    doc = mod.build_image_doc(b"hello-webp", mime="image/webp",
                              width=1200, height=630, source="banana", state="generated")
    assert doc["data"] == base64.b64encode(b"hello-webp").decode("ascii")
    assert doc["size_bytes"] == len(b"hello-webp")
    assert doc["mime"] == "image/webp"
    assert doc["state"] == "generated"


def test_build_image_doc_rejects_oversize_payload():
    mod = _import_helper()
    big = b"x" * (1_000_000)  # > 900 KiB binary
    with pytest.raises(mod.PayloadTooLarge):
        mod.build_image_doc(big, mime="image/webp", width=1, height=1,
                            source="banana", state="generated")


def test_attach_posts_hero_image():
    mod = _import_helper()
    request_fn = MagicMock(return_value={"state": "generated", "kind": "hero"})
    doc = mod.build_image_doc(b"hello", mime="image/webp", width=10, height=5,
                              source="banana", state="generated")
    image_path = mod.attach(request_fn, "redbridgecyber", "d1", doc)
    assert image_path == "/brand/blog/articles/d1/image"
    args = request_fn.call_args.args
    assert args[1] == "POST"
    assert args[2] == "/brand/blog/articles/d1/image"
    assert args[3]["data"] == doc["data"]
