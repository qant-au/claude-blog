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
    python3 list_pending_rewrites.py --brand redbridgecyber

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument(
        "--brand",
        required=True,
        help="Brand slug (e.g. redbridgecyber). Scoped to brands/{slug}/drafts/.",
    )
    args = ap.parse_args()

    project, key_path = _env()

    try:
        from google.cloud import firestore  # type: ignore
        from google.cloud.firestore_v1.base_query import FieldFilter  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:
        sys.stderr.write(
            f"error: required Python package missing ({exc}). "
            "Install with `pip install google-cloud-firestore`.\n"
        )
        return 2

    creds = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project, credentials=creds)

    drafts_path = f"brands/{args.brand}/drafts"
    try:
        query = client.collection(drafts_path).where(
            filter=FieldFilter("review_state", "==", "needs_rewrite")
        )
        rows: list[dict] = []
        for snap in query.stream():
            data = snap.to_dict() or {}
            rows.append(
                {
                    "brand_slug": args.brand,
                    "draft_id": snap.id,
                    "draft_path": f"{drafts_path}/{snap.id}",
                    "slug": data.get("slug") or data.get("article_slug") or "",
                    "title": data.get("title") or "",
                    "author_slug": _author_slug(data),
                    "category": data.get("category") or "",
                    "review_state": data.get("review_state") or "",
                    "word_count": _word_count(data),
                }
            )
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write(f"error: Firestore query failed: {exc}\n")
        return 1

    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
