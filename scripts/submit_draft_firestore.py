#!/usr/bin/env python3
"""Write a finished blog draft into the qant-blog-drafts Firestore project.

Replaces the HTTP-based ``submit_draft.py`` for QANT workflows. Used by
``/blog write --brand <slug>`` after the FLOW review passes: the
orchestrator constructs the payload JSON from article state, then invokes
this script to ship it.

Phase F-post — author docs are managed via the Blog Manager UI
─────────────────────────────────────────────────────────────
Before Phase F, this script ALSO upserted the per-author doc from an
on-disk bundle (bio.md + style.md + byline.md). Phase F shipped the
operator-side Author Profile UI in the consumer app, and the on-disk
bundles were retired in Phase F-post.

This script now ONLY writes the draft. The author doc is assumed to
already exist in ``qant-blog-drafts.brands/{brand_slug}/authors/{author_slug}``
because either:
  * an operator created it via the Blog Manager UI (the regular path), OR
  * one of the migration scripts (api/qant-api/scripts/backfill-blog-authors.py
    or the one-shot migrate-disk-authors.py) seeded it.

If the author doc isn't there, this script fails fast with a clear
"create the author via the Blog Manager UI first" message — no implicit
creation, no disk fallback.

Data shape (Phase F-post)
─────────────────────────
The script writes ONE Firestore doc per call:

  brands/{brand_slug}/drafts/{auto_id}          — the article. ``author``
      is just ``{slug, name}`` — bio + byline + writing style live on
      ``brands/{brand_slug}/authors/{author_slug}`` and are joined
      client-side at render time.

The orchestrator MUST NOT include ``author.bio`` or ``author.byline`` in
the payload; this script strips them defensively (with a stderr warning)
to enforce the shape.

Environment
───────────
* ``QANT_BLOG_DRAFTS_PROJECT_ID`` — Firebase project ID, e.g. ``qant-blog-drafts``.
* ``QANT_BLOG_DRAFTS_WRITER_KEY`` — path to the writer-SA JSON key. The
  SA needs read AND write on ``brands/*/authors/*`` (read to verify the
  author exists; write was never required for authors on this code path).
  Drafts collection write permission is required as it always was.

Both are required. If either is unset the script exits 2.

Usage
─────
    python3 submit_draft_firestore.py \\
        --brand-slug redbridgecyber \\
        --author adam-burgess \\
        --payload path/to/draft.json

The script:
* Validates the payload file is readable JSON and an object.
* Reads ``brands/{brand_slug}/authors/{author_slug}`` from
  qant-blog-drafts. If the doc is missing, exits 2 with a message
  telling the operator to create the author via the Blog Manager UI.
* Strips ``author.bio`` and ``author.byline`` from the draft payload if
  present (defensive — they belong on the author doc).
* Pins ``brand_slug`` and stamps producer-side telemetry (``submittedBy``
  skill + hostname, ``submittedAt`` server timestamp, ``keyId`` writer-SA
  client_email).
* Writes the draft to ``brands/{brand_slug}/drafts/{auto_id}``.
* On any Firestore error: prints the exception to stderr, exits 1.

Requires the ``google-cloud-firestore`` package
(``pip install google-cloud-firestore``).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

SKILL_VERSION = "claude-blog/submit_draft_firestore.py v3"


def _read_env() -> tuple[str, str]:
    project_id = os.environ.get("QANT_BLOG_DRAFTS_PROJECT_ID")
    key_path   = os.environ.get("QANT_BLOG_DRAFTS_WRITER_KEY")
    missing: list[str] = []
    if not project_id:
        missing.append("QANT_BLOG_DRAFTS_PROJECT_ID")
    if not key_path:
        missing.append("QANT_BLOG_DRAFTS_WRITER_KEY")
    if missing:
        print(
            f"Error: missing env var(s): {', '.join(missing)}.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not Path(key_path).is_file():  # type: ignore[arg-type]
        print(
            f"Error: QANT_BLOG_DRAFTS_WRITER_KEY points at non-existent file: {key_path}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return project_id, key_path  # type: ignore[return-value]


def _key_email(key_path: str) -> str:
    """Pull ``client_email`` from the SA JSON so we can stamp it as keyId."""
    try:
        data = json.loads(Path(key_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return data.get("client_email", "") or ""


def submit(
    project_id: str,
    key_path: str,
    brand_slug: str,
    author_slug: str,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Verify author exists, write the draft, return paths.

    Returns ``{"author_path", "draft_id", "draft_path"}``.

    Imports ``google.cloud.firestore`` lazily so the script's ``--help``
    works even when the dep isn't installed.
    """
    try:
        from google.cloud import firestore  # type: ignore[import-not-found]
        from google.cloud.firestore_v1 import SERVER_TIMESTAMP  # type: ignore[import-not-found]
        from google.oauth2 import service_account  # type: ignore[import-not-found]
    except ImportError as e:
        print(
            f"Error: required Python package missing ({e}). "
            f"Install with: pip install google-cloud-firestore",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    creds  = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project_id, credentials=creds)

    # Phase 1: verify the author exists.
    author_ref = (
        client.collection("brands").document(brand_slug)
        .collection("authors").document(author_slug)
    )
    snap = author_ref.get()
    if not snap.exists:
        raise ValueError(
            f"author '{author_slug}' does not exist in qant-blog-drafts under "
            f"brand '{brand_slug}'. Create it via the Blog Manager UI in the "
            f"consumer app (Brands → {brand_slug} → New Author) before "
            f"submitting drafts for this author."
        )
    author_doc = snap.to_dict() or {}
    canonical_name = author_doc.get("name") or author_slug

    # Phase 2: build the draft doc. Strip any bio/byline the caller leaked
    # into author{} — they belong on the author doc, not on every draft.
    doc: dict[str, Any] = dict(payload)
    author = dict(doc.get("author") or {})
    leaked = [k for k in ("bio", "byline") if k in author]
    if leaked:
        print(
            f"warn: dropping author.{','.join(leaked)} from draft payload "
            f"(they live on brands/{brand_slug}/authors/{author_slug})",
            file=sys.stderr,
        )
        for k in leaked:
            author.pop(k, None)
    # The orchestrator may pass author.slug + author.name; enforce them
    # against the author doc's canonical values so the join key + UI
    # label always match.
    author["slug"] = author_slug
    author["name"] = canonical_name
    doc["author"] = author

    doc["brand_slug"]  = brand_slug
    doc.setdefault("contentType", "blog_post")
    doc["submittedBy"] = f"{SKILL_VERSION} on {socket.gethostname()}"
    doc["submittedAt"] = SERVER_TIMESTAMP
    doc["keyId"]       = _key_email(key_path)

    drafts_col = client.collection("brands").document(brand_slug).collection("drafts")
    auto_ref   = drafts_col.document()  # auto-id
    auto_ref.set(doc)
    return {
        "author_path": f"brands/{brand_slug}/authors/{author_slug}",
        "draft_id":    auto_ref.id,
        "draft_path":  f"brands/{brand_slug}/drafts/{auto_ref.id}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--brand-slug",
        required=True,
        help="Brand slug for the doc (e.g. redbridgecyber). Pinned into the payload.",
    )
    parser.add_argument(
        "--author",
        required=True,
        help="Author slug (e.g. adam-burgess). MUST already exist in "
             "qant-blog-drafts.brands/{brand_slug}/authors/{author_slug} — "
             "create it via the Blog Manager UI first if it doesn't.",
    )
    parser.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="Path to a JSON file with the draft payload (matches BlogDraft shape, "
             "minus author.bio / author.byline — those live on the author doc).",
    )
    args = parser.parse_args()

    project_id, key_path = _read_env()

    try:
        payload_text = args.payload.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error: cannot read payload file {args.payload}: {e}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as e:
        print(f"Error: payload is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print(
            f"Error: payload must be a JSON object, got {type(payload).__name__}",
            file=sys.stderr,
        )
        return 2

    try:
        result = submit(project_id, key_path, args.brand_slug, args.author, payload)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  — surface raw Firestore errors
        print(f"Error: Firestore write failed: {e!r}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
