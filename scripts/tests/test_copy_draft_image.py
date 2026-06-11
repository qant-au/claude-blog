"""Behavioral tests for scripts/copy_draft_image.py (API-over-brand-key)."""

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


def _image_doc(state="approved"):
    return {
        "mime": "image/webp", "data": "aGVsbG8=", "state": state,
        "width": 1200, "height": 630, "size_bytes": 100, "source": "banana",
    }


def test_copy_reads_source_and_posts_to_target():
    mod = _import_helper()
    calls = []

    def request_fn(brand, method, path, body=None, **kw):
        calls.append((method, path, body))
        if method == "GET":
            return _image_doc()
        return {"state": "approved", "kind": "hero"}

    result = mod.copy_image(request_fn, "redbridgecyber", "old1", "new1")
    assert result["image_path"] == "/brand/blog/articles/new1/image"
    get_call, post_call = calls[0], calls[1]
    assert get_call[0] == "GET" and get_call[1] == "/brand/blog/articles/old1/image"
    assert post_call[0] == "POST" and post_call[1] == "/brand/blog/articles/new1/image"
    assert post_call[2]["source"] == "copied:old1"
    assert post_call[2]["state"] == "approved"   # approval state travels
    assert post_call[2]["data"] == "aGVsbG8="


def test_copy_reports_no_image_to_copy_when_source_absent():
    mod = _import_helper()
    request_fn = MagicMock(return_value=None)   # GET with none_on_404 → None
    result = mod.copy_image(request_fn, "redbridgecyber", "old1", "new1")
    assert result["result"] == "no_image_to_copy"
