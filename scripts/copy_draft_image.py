#!/usr/bin/env python3
"""Copy the hero image from one draft article to another via the API.

Content-only rewrites submit a NEW article and delete the original — the
hero (possibly operator-approved) must travel. Reads the source image via
``GET /brand/blog/articles/{from}/image`` and re-attaches it to the target
with ``source`` rewritten to ``copied:{from_draft_id}``. The approval
``state`` travels unchanged.

Legacy drafts may have no image doc — that is a soft miss
(``{"result": "no_image_to_copy"}``, exit 0), not an error.

Usage:
    python3 copy_draft_image.py --brand-slug redbridgecyber \
        --from-draft-id <old> --to-draft-id <new>

Exit codes: 0 ok / nothing to copy · 1 API failure · 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qant_api  # noqa: E402


def copy_image(request_fn, brand_slug: str, from_draft_id: str, to_draft_id: str) -> dict:
    """GET the source hero and POST it onto the target. Returns
    {"image_path": ...} or {"result": "no_image_to_copy"}."""
    source_doc = request_fn(
        brand_slug, "GET", f"/brand/blog/articles/{from_draft_id}/image",
        None, none_on_404=True,
    )
    if source_doc is None:
        return {"result": "no_image_to_copy"}

    payload = {
        "mime":       source_doc.get("mime", "image/webp"),
        "data":       source_doc.get("data", ""),
        "state":      source_doc.get("state", "generated"),
        "width":      source_doc.get("width"),
        "height":     source_doc.get("height"),
        "size_bytes": source_doc.get("size_bytes"),
        "source":     f"copied:{from_draft_id}",
    }
    target_path = f"/brand/blog/articles/{to_draft_id}/image"
    request_fn(brand_slug, "POST", target_path, payload)
    return {"image_path": target_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--brand-slug", required=True)
    parser.add_argument("--from-draft-id", required=True)
    parser.add_argument("--to-draft-id", required=True)
    args = parser.parse_args()

    try:
        result = copy_image(qant_api.request, args.brand_slug, args.from_draft_id, args.to_draft_id)
    except qant_api.ApiError as e:
        if e.status == 404:
            print(f"Error: target draft {args.to_draft_id} not found for brand {args.brand_slug}", file=sys.stderr)
            return 2
        print(f"Error: API copy failed: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
