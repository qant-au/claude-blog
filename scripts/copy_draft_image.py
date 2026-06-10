#!/usr/bin/env python3
"""Copy the hero image doc from one qant-blog-drafts draft to another.

Used by ``/blog rewrite --from-queue`` when the rewrite targets content
only (``review_targets.image == false``): the rewritten article is
submitted as a new doc, and the original's hero image is carried across
without regenerating it (no wasted image-gen credits). The operator's
approval state survives the copy.

If the source draft has no image doc, this is a NO-OP success
(``no_image_to_copy``) — legacy drafts predate hero images and the
rewrite flow must not fail on them.

Environment
-----------
* ``QANT_BLOG_DRAFTS_PROJECT_ID``
* ``QANT_BLOG_DRAFTS_WRITER_KEY``

Both required; exits 2 if missing.

Usage
-----
    python3 copy_draft_image.py \\
        --brand-slug    redbridgecyber \\
        --from-draft-id Y14iwD70ljgFIEW5Mihi \\
        --to-draft-id   A1SkBgH1c6OgwIeBkxp9

Exit codes
----------
* 0 — copied (prints {"image_path": ...}) or nothing to copy
      (prints ``no_image_to_copy``).
* 1 — Firestore error.
* 2 — env vars missing or SA key path unreadable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def build_copied_doc(src: dict, from_draft_id: str) -> dict:
    """Pure core: reshape the source image doc for the target draft.

    Preserves data/dimensions/state; rewrites source to ``copied:<id>``;
    drops timestamps (createdAt is stamped fresh at write, reviewedAt
    belongs to the original's review event).
    """
    doc = {k: v for k, v in src.items() if k not in ("createdAt", "reviewedAt")}
    doc["source"] = f"copied:{from_draft_id}"
    return doc


def copy_image(client, brand_slug: str, from_draft_id: str, to_draft_id: str) -> str | None:
    """Read src images/hero; if present, write it to dst. Returns the new
    doc path, or None when the source has no image."""
    from google.cloud.firestore_v1 import SERVER_TIMESTAMP  # type: ignore[import-not-found]

    drafts_col = client.collection("brands").document(brand_slug).collection("drafts")
    src_snap = (
        drafts_col.document(from_draft_id).collection("images").document("hero").get()
    )
    if not src_snap.exists:
        return None
    doc = build_copied_doc(src_snap.to_dict() or {}, from_draft_id)
    dst_ref = drafts_col.document(to_draft_id).collection("images").document("hero")
    dst_ref.set({**doc, "createdAt": SERVER_TIMESTAMP})
    return f"brands/{brand_slug}/drafts/{to_draft_id}/images/hero"


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
    parser.add_argument("--from-draft-id", required=True)
    parser.add_argument("--to-draft-id", required=True)
    args = parser.parse_args()

    project_id, key_path = _read_env()

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
        image_path = copy_image(
            client, args.brand_slug, args.from_draft_id, args.to_draft_id
        )
    except Exception as e:  # noqa: BLE001 — surface raw Firestore errors
        print(f"Error: Firestore copy failed: {e!r}", file=sys.stderr)
        return 1

    if image_path is None:
        print("no_image_to_copy")
    else:
        print(json.dumps({"image_path": image_path}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
