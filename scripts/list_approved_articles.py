#!/usr/bin/env python3
"""List approved articles ready to publish via the QANT brand-blog API.

``/blog publish`` drains this queue. Each brand is queried with its own key
(``GET /brand/blog/approved``); ``--all-brands`` enumerates every brand
directory under qant/brands/ whose env file carries a brand key and merges
the per-brand queues.

Row shape (every row is a `status == "approved"` article):
    {brand_slug, draft_id, draft_path, slug, title, author_slug,
     category, kind, status, hero_image_url, word_count}

``kind`` is coerced to "spoke" when absent — legacy drafts predate the
field, and a missing kind is, by definition, not a perspective/pillar.

Usage:
    python3 list_approved_articles.py --brand redbridgecyber
    python3 list_approved_articles.py --all-brands

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
    """Shape one queue row from an article response. Every row here is an
    approved item (``status == "approved"``)."""
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
        "kind":           article.get("kind") or "spoke",
        "status":         article.get("status") or "approved",
        "hero_image_url": article.get("hero_image_url") or "",
        "word_count":     len(body.split()) if body else 0,
    }


def query_brand(request_fn, brand_slug: str) -> list[dict]:
    """Return the approved-article rows for one brand."""
    resp = request_fn(brand_slug, "GET", "/brand/blog/approved", None)
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
        help="Merge the approved queue of every brand under qant/brands/ that "
             "has a brand key.",
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
