#!/usr/bin/env python3
"""Clear the rewrite flag on a draft article via the QANT brand-blog API.

Image-only rewrites attach a fresh hero over the SAME article (no new doc,
no delete) — afterwards the queue flag must clear so the article reappears
in the Axiom review queue. POSTs
``/brand/blog/articles/{id}/clear-review-state``; the server removes
``review_state`` / ``review_instructions`` / ``review_targets`` and stamps
``review_state_cleared_at`` (+ the optional reason).

Usage:
    python3 clear_review_state.py --brand-slug redbridgecyber \
        --draft-id <id> [--reason "image regenerated"]

Exit codes: 0 ok · 1 API failure · 2 bad input / article missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qant_api  # noqa: E402


def clear_flags(request_fn, brand_slug: str, draft_id: str, *, reason: str | None) -> bool:
    """POST the clear. Returns False when the article doesn't exist."""
    body = {"reason": reason} if reason else {}
    try:
        request_fn(brand_slug, "POST", f"/brand/blog/articles/{draft_id}/clear-review-state", body)
    except qant_api.ApiError as e:
        if e.status == 404:
            return False
        raise
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--brand-slug", required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--reason", default="",
                        help="Optional audit note stored as review_state_cleared_reason.")
    args = parser.parse_args()

    try:
        ok = clear_flags(qant_api.request, args.brand_slug, args.draft_id,
                         reason=args.reason or None)
    except qant_api.ApiError as e:
        print(f"Error: API write failed: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not ok:
        print(f"Error: draft {args.draft_id} not found for brand {args.brand_slug}", file=sys.stderr)
        return 2
    print(json.dumps({"cleared": True, "draft_id": args.draft_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
