#!/usr/bin/env python3
"""List drafts flagged for rewrite in qant-blog-drafts Firestore.

Reads drafts under ``brands/{brand_slug}/drafts/{*}`` where
``review_state == "needs_rewrite"`` and emits a JSON array describing each
one. Used by ``/blog rewrite --from-queue --brand <slug>`` to iterate over
the queue without the operator having to find drafts by hand.

The ``review_state`` field is set by the Blog Manager UI when an operator
flags a draft for rewrite. Until that UI ships (tracked as qnt-045 in
``/Users/adam/Projects/qant/TODO.md``), the field can be set manually for
testing via the Firebase console or a small admin script — see the SKILL.md
"Queue mode" section for the testing pattern.

Environment
-----------
* ``QANT_BLOG_DRAFTS_PROJECT_ID`` — e.g. ``qant-blog-drafts``.
* ``QANT_BLOG_DRAFTS_WRITER_KEY`` — path to a writer SA JSON. The SA needs
  read on ``brands/*/drafts/*``; no write is required for the list path.

Both are required. If either is unset, exits 2.

Usage
-----
    # Per-brand mode (legacy; useful for debugging one brand):
    python3 list_pending_rewrites.py --brand redbridgecyber

    # All-brands mode — default for `/blog rewrite` invoked with no args.
    # Enumerates every doc in the `brands` collection of the
    # qant-blog-drafts project and merges all queues into one JSON array.
    python3 list_pending_rewrites.py --all-brands

Output (JSON to stdout)::

    [
      {
        "brand_slug":   "redbridgecyber",
        "draft_id":     "<auto-id>",
        "draft_path":   "brands/redbridgecyber/drafts/<auto-id>",
        "slug":         "small-business-seo-australia",
        "title":        "Small business SEO in Australia: ...",
        "author_slug":  "red-bridge-cyber-team",
        "category":     "visibility",
        "review_state": "needs_rewrite",
        "review_targets": {"content": true, "image": false},
        "word_count":   1834
      },
      ...
    ]

Exit codes
----------
* 0 — query succeeded (the array may be empty).
* 1 — Firestore error.
* 2 — env vars missing or SA key path unreadable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _env() -> tuple[str, str]:
    project = os.environ.get("QANT_BLOG_DRAFTS_PROJECT_ID")
    key_path = os.environ.get("QANT_BLOG_DRAFTS_WRITER_KEY")
    if not project:
        sys.stderr.write("error: QANT_BLOG_DRAFTS_PROJECT_ID is not set.\n")
        sys.exit(2)
    if not key_path:
        sys.stderr.write("error: QANT_BLOG_DRAFTS_WRITER_KEY is not set.\n")
        sys.exit(2)
    if not os.path.exists(key_path):
        sys.stderr.write(f"error: SA key file not found at {key_path}.\n")
        sys.exit(2)
    return project, key_path


def _author_slug(data: dict) -> str:
    a = data.get("author_slug") or data.get("author")
    if isinstance(a, dict):
        return a.get("slug") or a.get("name") or ""
    return str(a) if a else ""


def _word_count(data: dict) -> int:
    body = data.get("body_markdown") or data.get("content") or data.get("markdown") or ""
    return len(body.split()) if body else 0


def _row(brand_slug: str, drafts_path: str, snap_id: str, data: dict) -> dict:
    """Shape one flagged-draft queue row. ``review_targets`` defaults to
    content-only for legacy drafts flagged before targets existed."""
    return {
        "brand_slug": brand_slug,
        "draft_id": snap_id,
        "draft_path": f"{drafts_path}/{snap_id}",
        "slug": data.get("slug") or data.get("article_slug") or "",
        "title": data.get("title") or "",
        "author_slug": _author_slug(data),
        "category": data.get("category") or "",
        "review_state": data.get("review_state") or "",
        "review_targets": data.get("review_targets") or {"content": True, "image": False},
        "word_count": _word_count(data),
    }


def _query_brand(client, brand_slug: str) -> list[dict]:
    """Return the flagged-draft rows for one brand.

    Helper so the same per-brand query runs both in ``--brand`` mode and in
    the ``--all-brands`` enumeration. Raises on Firestore errors; the caller
    decides whether to skip the brand or abort the whole run.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter  # type: ignore

    drafts_path = f"brands/{brand_slug}/drafts"
    query = client.collection(drafts_path).where(
        filter=FieldFilter("review_state", "==", "needs_rewrite")
    )
    return [
        _row(brand_slug, drafts_path, snap.id, snap.to_dict() or {})
        for snap in query.stream()
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--brand",
        help="Brand slug (e.g. redbridgecyber). Scoped to brands/{slug}/drafts/.",
    )
    grp.add_argument(
        "--all-brands",
        action="store_true",
        help=(
            "Enumerate every doc in the `brands` collection and merge each "
            "brand's flagged-draft queue into one JSON array. Default for "
            "`/blog rewrite` with no args."
        ),
    )
    args = ap.parse_args()

    project, key_path = _env()

    try:
        from google.cloud import firestore  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:
        sys.stderr.write(
            f"error: required Python package missing ({exc}). "
            "Install with `pip install google-cloud-firestore`.\n"
        )
        return 2

    creds = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project, credentials=creds)

    rows: list[dict] = []
    try:
        if args.all_brands:
            # list_documents() (not stream()) is required here: the
            # qant-blog-drafts schema uses `brands/{slug}/drafts/{id}` with
            # no parent-doc fields, so the brand "documents" are stub refs
            # that exist only because they own subcollections. stream()
            # skips them; list_documents() returns them.
            for brand_ref in client.collection("brands").list_documents():
                try:
                    rows.extend(_query_brand(client, brand_ref.id))
                except Exception as exc:  # pylint: disable=broad-except
                    # Don't abort the whole run because one brand's query
                    # failed — the operator wants the queue to drain.
                    sys.stderr.write(
                        f"warn: skipping brand {brand_ref.id}: {exc}\n"
                    )
        else:
            rows.extend(_query_brand(client, args.brand))
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write(f"error: Firestore query failed: {exc}\n")
        return 1

    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
