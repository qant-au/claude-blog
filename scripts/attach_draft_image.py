#!/usr/bin/env python3
"""Attach a hero image to a qant-blog-drafts draft as a Firestore doc.

Writes the image bytes (base64) to
``brands/{brand_slug}/drafts/{draft_id}/images/hero`` — a fixed-id
subcollection doc, one hero per draft, overwritten in place on re-attach.
Companion to ``submit_draft_firestore.py``: the blog-write orchestrator
submits the draft first, then attaches the reviewed hero with the
returned draft id (Phase 7.6).

Doc shape (shared contract with the API + Blog Manager UI):

    {
      "data":       "<base64 of the WebP bytes>",
      "mime":       "image/webp",
      "width":      1200,
      "height":     630,
      "size_bytes": <raw byte count>,
      "kind":       "hero",
      "state":      "generated" | "approved" | "rejected",
      "source":     "banana" | "gemini-direct" | "stock" | "copied:<id>",
      "createdAt":  SERVER_TIMESTAMP
    }

Size gate: Firestore documents cap at 1 MiB. The base64 payload is
limited to 900 KiB (921,600 chars); larger input exits 3 so the
orchestrator can re-encode at a lower WebP quality (80 -> 65 -> 50)
and retry.

Environment
-----------
* ``QANT_BLOG_DRAFTS_PROJECT_ID``
* ``QANT_BLOG_DRAFTS_WRITER_KEY``

Both required; exits 2 if missing.

Usage
-----
    python3 attach_draft_image.py \\
        --brand-slug redbridgecyber \\
        --draft-id   Y14iwD70ljgFIEW5Mihi \\
        --image      /path/to/hero.webp \\
        --mime       image/webp \\
        --width 1200 --height 630 \\
        --source banana [--state generated]

Exit codes
----------
* 0 — image doc written; prints {"image_path": ...} JSON.
* 1 — Firestore error.
* 2 — env/args invalid, image file unreadable, or draft doc missing.
* 3 — image too large even for the base64 gate (re-encode and retry).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

MAX_BASE64_CHARS = 921_600  # 900 KiB of base64 ≈ 675 KiB raw image


class PayloadTooLarge(ValueError):
    """Encoded image exceeds the Firestore-doc safety gate."""


class DraftNotFound(LookupError):
    """Parent draft doc does not exist in qant-blog-drafts."""


def build_image_doc(
    image_bytes: bytes,
    *,
    mime: str,
    width: int,
    height: int,
    source: str,
    state: str = "generated",
) -> dict:
    """Pure core: shape the image doc (sans createdAt, stamped at write)."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    if len(encoded) > MAX_BASE64_CHARS:
        raise PayloadTooLarge(
            f"base64 payload is {len(encoded)} chars (max {MAX_BASE64_CHARS}); "
            f"re-encode the image at a lower quality and retry"
        )
    return {
        "data":       encoded,
        "mime":       mime,
        "width":      width,
        "height":     height,
        "size_bytes": len(image_bytes),
        "kind":       "hero",
        "state":      state,
        "source":     source,
    }


def attach(client, brand_slug: str, draft_id: str, doc: dict) -> str:
    """Verify the draft exists, then set images/hero. Returns the doc path."""
    from google.cloud.firestore_v1 import SERVER_TIMESTAMP  # type: ignore[import-not-found]

    draft_ref = (
        client.collection("brands").document(brand_slug)
        .collection("drafts").document(draft_id)
    )
    if not draft_ref.get().exists:
        raise DraftNotFound(
            f"draft '{draft_id}' does not exist under brand '{brand_slug}' — "
            f"submit the draft before attaching its image"
        )
    image_ref = draft_ref.collection("images").document("hero")
    image_ref.set({**doc, "createdAt": SERVER_TIMESTAMP})
    return f"brands/{brand_slug}/drafts/{draft_id}/images/hero"


def _read_env() -> tuple[str, str]:
    project_id = os.environ.get("QANT_BLOG_DRAFTS_PROJECT_ID")
    key_path   = os.environ.get("QANT_BLOG_DRAFTS_WRITER_KEY")
    missing = [
        name for name, val in (
            ("QANT_BLOG_DRAFTS_PROJECT_ID", project_id),
            ("QANT_BLOG_DRAFTS_WRITER_KEY", key_path),
        ) if not val
    ]
    if missing:
        print(f"Error: missing env var(s): {', '.join(missing)}.", file=sys.stderr)
        raise SystemExit(2)
    if not Path(key_path).is_file():  # type: ignore[arg-type]
        print(
            f"Error: QANT_BLOG_DRAFTS_WRITER_KEY points at non-existent file: {key_path}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return project_id, key_path  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--brand-slug", required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--image", required=True, type=Path,
                        help="Path to the converted hero image (WebP, 1200x630).")
    parser.add_argument("--mime", default="image/webp")
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--source", required=True,
                        help="banana | gemini-direct | stock | copied:<draft_id>")
    parser.add_argument("--state", default="generated",
                        choices=["generated", "approved", "rejected"])
    args = parser.parse_args()

    project_id, key_path = _read_env()

    try:
        image_bytes = args.image.read_bytes()
    except OSError as e:
        print(f"Error: cannot read image file {args.image}: {e}", file=sys.stderr)
        return 2

    try:
        doc = build_image_doc(
            image_bytes, mime=args.mime, width=args.width, height=args.height,
            source=args.source, state=args.state,
        )
    except PayloadTooLarge as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3

    try:
        from google.cloud import firestore  # type: ignore[import-not-found]
        from google.oauth2 import service_account  # type: ignore[import-not-found]
    except ImportError as e:
        print(
            f"Error: required Python package missing ({e}). "
            f"Install with: pip install google-cloud-firestore",
            file=sys.stderr,
        )
        return 2

    creds  = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project_id, credentials=creds)

    try:
        image_path = attach(client, args.brand_slug, args.draft_id, doc)
    except DraftNotFound as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — surface raw Firestore errors
        print(f"Error: Firestore write failed: {e!r}", file=sys.stderr)
        return 1

    print(json.dumps({"image_path": image_path, "size_bytes": doc["size_bytes"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
