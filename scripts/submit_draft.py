#!/usr/bin/env python3
"""POST a finished blog draft to the qant private API.

Used by `/blog write --brand <slug> --staging` after FLOW review passes:
the orchestrator constructs the payload JSON from article state, then
invokes this script to ship it. See the spec at
`/Users/adam/Projects/qant/docs/superpowers/specs/2026-06-03-blog-module-restructure-design.md`
Phase B3 for the payload shape and the receiving endpoint contract.

Usage:
    python3 submit_draft.py \\
        --api-url https://api-stg.qant.au \\
        --brand-key brk_... \\
        --brand-slug redbridgecyber \\
        --payload path/to/draft.json

The script:
* Validates the payload file is readable JSON.
* POSTs to `${api_url}/private/blog/drafts` with bearer auth and
  `Content-Type: application/json`.
* On transient network failure (timeout, connection reset), retries ONCE
  with a short backoff. 4xx and 5xx HTTP responses surface immediately;
  they are not retried.
* On 2xx: prints the response body to stdout, exits 0.
* On failure: prints the response body (or exception) to stderr, exits 1.

The brand_key is never logged. Errors mention the URL and status code but
not the auth header.

Stdlib only — uses `urllib.request`. No network calls happen at import time.
"""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
DRAFTS_PATH = "/private/blog/drafts"

# Network errors we treat as transient and retry once.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    socket.timeout,
    ConnectionResetError,
    ConnectionAbortedError,
    http.client.RemoteDisconnected,
    http.client.IncompleteRead,
    urllib.error.URLError,
)


class SubmitError(Exception):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"{url} returned {status}: {body[:500]}")
        self.status = status
        self.body = body
        self.url = url


def _do_post(url: str, brand_key: str, body_bytes: bytes, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=body_bytes,
        method="POST",
        headers={
            "Authorization": f"Bearer {brand_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "claude-blog/submit_draft.py",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            response_body = resp.read().decode("utf-8", errors="replace")
            return status, response_body
    except urllib.error.HTTPError as e:
        # Non-2xx: read body for diagnostics but DO NOT retry.
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<unreadable body>"
        raise SubmitError(status=e.code, body=body, url=url) from None


def submit(
    api_url: str,
    brand_key: str,
    brand_slug: str,
    payload: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """POST the payload and return the parsed JSON response.

    Retries ONCE on transient network failures. Surfaces HTTP errors
    immediately via SubmitError. Raises ValueError for malformed responses.
    """
    if not api_url.startswith(("http://", "https://")):
        raise ValueError(f"api_url must be absolute http(s): {api_url!r}")
    url = api_url.rstrip("/") + DRAFTS_PATH

    # Sanity-pin brand_slug into the payload if absent (the spec requires it).
    payload.setdefault("brand_slug", brand_slug)

    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    attempts = 0
    last_transient: BaseException | None = None
    while attempts < 2:
        attempts += 1
        try:
            status, body = _do_post(url, brand_key, body_bytes, timeout)
        except SubmitError:
            # HTTP error — surface immediately.
            raise
        except TRANSIENT_ERRORS as e:
            last_transient = e
            if attempts >= 2:
                break
            time.sleep(retry_backoff)
            continue

        if not (200 <= status < 300):
            # Defensive: _do_post should have raised SubmitError already.
            raise SubmitError(status=status, body=body, url=url)

        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            raise ValueError(
                f"API returned 2xx but body is not valid JSON: {e}"
            ) from None

    assert last_transient is not None
    raise SubmitError(
        status=0,
        body=f"transient network failure after 2 attempts: {last_transient}",
        url=url,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api-url", required=True, help="Base API URL, e.g. https://api-stg.qant.au")
    parser.add_argument("--brand-key", required=True, help="Brand bearer token (brk_...)")
    parser.add_argument("--brand-slug", required=True, help="Brand slug for the payload (and sanity check)")
    parser.add_argument("--payload", required=True, type=Path, help="Path to a JSON file with the draft payload")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds (default {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF_SECONDS,
        help=f"Sleep between the first and second attempt (default {DEFAULT_RETRY_BACKOFF_SECONDS}s).",
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
        response = submit(
            args.api_url,
            args.brand_key,
            args.brand_slug,
            payload,
            timeout=args.timeout,
            retry_backoff=args.retry_backoff,
        )
    except SubmitError as e:
        # Status + body to stderr (URL only, no brand_key).
        print(f"Error: POST {e.url} failed with status {e.status}", file=sys.stderr)
        print(e.body, file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
