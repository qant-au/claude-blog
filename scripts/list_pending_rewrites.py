#!/usr/bin/env python3
"""List draft articles flagged for rewrite via the QANT brand-blog API.

``/blog rewrite --from-queue`` drains this queue. Each brand is queried
with its own key (``GET /brand/blog/rewrites``); ``--all-brands``
enumerates every brand directory under qant/brands/ whose env file
carries a brand key and merges the per-brand queues.

Row shape matches the legacy queue contract:
    {brand_slug, draft_id, draft_path, slug, title, author_slug,
     category, review_state, review_targets, word_count}

Usage:
    python3 list_pending_rewrites.py --brand redbridgecyber
    python3 list_pending_rewrites.py --all-brands

Exit codes: 0 ok · 1 API failure · 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qant_api  # noqa: E402


def _row(brand_slug: str, article: dict) -> dict:
    """Shape one queue row from an article response. ``review_targets``
    defaults to content-only for legacy flags set before targets existed."""
    metadata = article.get("metadata") or {}
    author = article.get("author") or {}
    body = article.get("body_markdown") or ""
    article_id = article.get("id") or ""
    return {
        "brand_slug":     brand_slug,
        "draft_id":       article_id,
        "draft_path":     f"/brand/blog/articles/{article_id}",
        "slug":           article.get("slug") or "",
        "title":          article.get("title") or "",
        "author_slug":    author.get("slug") or "",
        "category":       article.get("category") or "",
        "review_state":   metadata.get("review_state") or "",
        "review_targets": metadata.get("review_targets") or {"content": True, "image": False},
        "word_count":     len(body.split()) if body else 0,
    }


def query_brand(request_fn, brand_slug: str) -> list[dict]:
    """Return the flagged-article rows for one brand."""
    resp = request_fn(brand_slug, "GET", "/brand/blog/rewrites", None)
    return [_row(brand_slug, a) for a in (resp or {}).get("items", [])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--brand",
        help="Brand slug (e.g. redbridgecyber).",
    )
    grp.add_argument(
        "--all-brands",
        action="store_true",
        help="Merge the rewrite queue of every brand under qant/brands/ that "
             "has a brand key. Default for `/blog rewrite` with no args.",
    )
    args = ap.parse_args()

    rows: list[dict] = []
    try:
        if args.all_brands:
            for slug in qant_api.list_brands_with_keys():
                try:
                    rows.extend(query_brand(qant_api.request, slug))
                except Exception as exc:  # noqa: BLE001 — drain the rest of the queue
                    sys.stderr.write(f"warn: skipping brand {slug}: {exc}\n")
        else:
            rows.extend(query_brand(qant_api.request, args.brand))
    except qant_api.ApiError as exc:
        sys.stderr.write(f"error: API query failed: {exc}\n")
        return 1
    except RuntimeError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
