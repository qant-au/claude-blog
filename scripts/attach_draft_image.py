#!/usr/bin/env python3
"""Attach a hero image to a draft article via the QANT brand-blog API.

POSTs the base64-encoded image to ``/brand/blog/articles/{id}/image``
with the brand key. The 900 KiB binary ceiling matches the server's
payload limit (hero images are stored inline in Firestore, 1 MiB doc cap)
— oversize images exit 3 so the orchestrator re-encodes at lower quality.

Usage:
    python3 attach_draft_image.py --brand-slug redbridgecyber \
        --draft-id <id> --image /tmp/hero.webp --mime image/webp \
        --width 1200 --height 630 --source banana [--state generated]

Exit codes: 0 ok · 1 API failure · 2 bad input / missing draft · 3 oversize.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qant_api  # noqa: E402

MAX_IMAGE_BYTES = 921_600  # 900 KiB binary — matches the API's base64 cap


class PayloadTooLarge(ValueError):
    pass


def build_image_doc(
    image_bytes: bytes, *, mime: str, width: int, height: int, source: str, state: str,
) -> dict:
    """Base64-encode and shape the attach payload. Raises PayloadTooLarge
    when the binary exceeds the inline-storage ceiling."""
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise PayloadTooLarge(
            f"image is {len(image_bytes)} bytes — exceeds the {MAX_IMAGE_BYTES} byte "
            f"(900 KiB) inline ceiling. Re-encode at lower quality and retry."
        )
    return {
        "mime":       mime,
        "data":       base64.b64encode(image_bytes).decode("ascii"),
        "state":      state,
        "width":      width,
        "height":     height,
        "size_bytes": len(image_bytes),
        "source":     source,
    }


def attach(request_fn, brand_slug: str, draft_id: str, doc: dict) -> str:
    """POST the image doc. Returns the API image path."""
    path = f"/brand/blog/articles/{draft_id}/image"
    request_fn(brand_slug, "POST", path, doc)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--brand-slug", required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--image", required=True, type=Path,
                        help="Path to the encoded image file (typically WebP).")
    parser.add_argument("--mime", default="image/webp")
    parser.add_argument("--width", required=True, type=int)
    parser.add_argument("--height", required=True, type=int)
    parser.add_argument("--source", required=True,
                        help="Generator provenance (banana | gemini-direct | stock | copied:<id>).")
    parser.add_argument("--state", default="generated",
                        choices=["generated", "approved", "rejected"])
    args = parser.parse_args()

    try:
        image_bytes = args.image.read_bytes()
    except OSError as e:
        print(f"Error: cannot read image file {args.image}: {e}", file=sys.stderr)
        return 2

    try:
        doc = build_image_doc(
            image_bytes, mime=args.mime, width=args.width, height=args.height,
            source=args.source, state=args.state,
        )
    except PayloadTooLarge as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3

    try:
        image_path = attach(qant_api.request, args.brand_slug, args.draft_id, doc)
    except qant_api.ApiError as e:
        if e.status == 404:
            print(f"Error: draft {args.draft_id} not found for brand {args.brand_slug}", file=sys.stderr)
            return 2
        print(f"Error: API write failed: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(json.dumps({"image_path": image_path, "size_bytes": doc["size_bytes"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
