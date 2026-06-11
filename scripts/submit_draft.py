#!/usr/bin/env python3
"""Submit a finished blog draft to the QANT brand-blog API.

Successor to submit_draft_firestore.py: drafts now POST to
``/brand/blog/articles`` authenticated with the brand's key (resolved from
``brands/<slug>/.env*`` by scripts/qant_api.py) instead of being written
into the retired qant-blog-drafts Firestore project.

The server validates the author and joins the canonical name from the
author doc — the payload carries only ``author_slug``. Any ``author`` /
``brand_slug`` / ``contentType`` keys the orchestrator left in the payload
are stripped (the key names the brand; the server stamps the rest).

Usage:
    python3 submit_draft.py --brand-slug redbridgecyber \
        --author adam-burgess --payload /tmp/draft.json

Prints ``{"author_slug", "draft_id", "draft_path"}`` on success.
Exit codes: 0 ok · 1 API failure · 2 bad input / unknown author.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qant_api  # noqa: E402

SKILL_VERSION = "claude-blog/2.0"


def submit(request_fn, brand_slug: str, author_slug: str, payload: dict[str, Any]) -> dict[str, str]:
    """POST the draft. Returns {author_slug, draft_id, draft_path}.

    ``request_fn(brand_slug, method, path, body, **kw)`` — qant_api.request
    in production; a mock in tests. Raises ValueError when the API rejects
    the author (404) so the orchestrator gets an actionable message.
    """
    body: dict[str, Any] = dict(payload)
    for stripped in ("author", "brand_slug", "contentType", "submittedAt", "submittedBy", "keyId"):
        body.pop(stripped, None)
    body["author_slug"] = author_slug

    metadata = dict(body.get("metadata") or {})
    metadata["submitted_by"] = f"{SKILL_VERSION} on {socket.gethostname()}"
    body["metadata"] = metadata

    try:
        article = request_fn(brand_slug, "POST", "/brand/blog/articles", body)
    except qant_api.ApiError as e:
        if e.status == 404:
            raise ValueError(
                f"author '{author_slug}' does not exist for brand "
                f"'{brand_slug}'. Create or edit authors in Axiom "
                f"(Instances → Brands → {brand_slug} → Authors) before "
                f"submitting drafts for this author."
            ) from None
        raise

    draft_id = article.get("id") or ""
    return {
        "author_slug": author_slug,
        "draft_id":    draft_id,
        "draft_path":  f"/brand/blog/articles/{draft_id}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--brand-slug",
        required=True,
        help="Brand slug (e.g. redbridgecyber). Selects the brand key from brands/<slug>/.env*.",
    )
    parser.add_argument(
        "--author",
        required=True,
        help="Author slug (e.g. adam-burgess). Must exist for the brand — "
             "create it in Axiom (Instances → Brands → Authors) first.",
    )
    parser.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="Path to a JSON file with the draft payload (title, slug, category, "
             "target_keyword, og, body_markdown, flow_score, metadata).",
    )
    args = parser.parse_args()

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
        print(f"Error: payload must be a JSON object, got {type(payload).__name__}", file=sys.stderr)
        return 2

    try:
        result = submit(qant_api.request, args.brand_slug, args.author, payload)
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except qant_api.ApiError as e:
        print(f"Error: API submission failed: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
