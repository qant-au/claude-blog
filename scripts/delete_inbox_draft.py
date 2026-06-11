#!/usr/bin/env python3
"""Delete a draft article via the QANT brand-blog API.

Used by ``/blog rewrite`` to remove the original after a rewritten
replacement commits (the server cascades the images subcollection).
Idempotent: a missing article reports success so retried queue drains
don't fail on already-cleaned originals.

Usage:
    python3 delete_inbox_draft.py --brand-slug redbridgecyber \
        --draft-id <id> [--reason "superseded by rewrite <new-id>"]

Exit codes: 0 ok (deleted or already gone) · 1 API failure · 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qant_api  # noqa: E402


def delete_draft(request_fn, brand_slug: str, draft_id: str) -> dict:
    """DELETE the article (404 tolerated). Returns {"deleted": True, ...}."""
    request_fn(
        brand_slug, "DELETE", f"/brand/blog/articles/{draft_id}",
        None, none_on_404=True,
    )
    return {"deleted": True, "draft_id": draft_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--brand-slug", required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--reason", default="",
                        help="Audit note for the operator log line (not persisted server-side).")
    args = parser.parse_args()

    try:
        result = delete_draft(qant_api.request, args.brand_slug, args.draft_id)
    except qant_api.ApiError as e:
        print(f"Error: API delete failed: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.reason:
        result["reason"] = args.reason
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
