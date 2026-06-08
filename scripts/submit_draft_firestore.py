#!/usr/bin/env python3
"""Write a finished blog draft directly into the qant-blog-drafts Firestore project.

Replaces the HTTP-based ``submit_draft.py`` for QANT workflows. Used by
``/blog write --brand <slug>`` after the FLOW review passes: the
orchestrator constructs the payload JSON from article state, then invokes
this script to ship it. See the producer-side plan at
``/Users/adam/.claude/plans/please-review-the-work-harmonic-cosmos.md``
for the architecture rationale (credential-blast-radius split: writer-only
SA on contributor machines; reader+deleter SA mounted into instance API
containers).

Why a separate script and not a flag on submit_draft.py
───────────────────────────────────────────────────────
The old path posts to ``${api_url}/private/blog/drafts`` and authenticates
with a brand-bearer key (``brk_...``). The new path writes to a separate
Firebase project and authenticates with a service-account JSON. The
contracts are completely different — no shared auth, no shared transport,
no shared error model. Keeping them as two scripts makes the lifecycle
clear: ``submit_draft.py`` is legacy / non-QANT consumers; this script is
the QANT path.

Environment
───────────
* ``QANT_BLOG_DRAFTS_PROJECT_ID`` — Firebase project ID, e.g. ``qant-blog-drafts``.
* ``QANT_BLOG_DRAFTS_WRITER_KEY`` — path to the writer-SA JSON key.

Both are required. If either is unset the script exits 2 with a hint
pointing at the plan file.

Usage
─────
    python3 submit_draft_firestore.py \\
        --brand-slug redbridgecyber \\
        --payload path/to/draft.json

The script:
* Validates the payload file is readable JSON and an object.
* Pins ``brand_slug`` into the payload (sanity check) and stamps the
  producer-side telemetry fields ``submittedBy`` (skill + hostname),
  ``submittedAt`` (server timestamp), and ``keyId`` (the writer-SA's
  ``client_email`` so a future rotation UI can identify which key was
  used).
* Writes to ``brands/{brand_slug}/drafts/{auto_id}`` with an auto-generated
  document ID, returns the path to stdout as JSON ``{"path": "...", "id": "..."}``.
* On Firestore error: prints the exception to stderr, exits 1.

Requires the ``google-cloud-firestore`` package
(``pip install google-cloud-firestore``). Add the ``qant`` extra in
``pyproject.toml`` to install it alongside the skill.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

PLAN_REF = "/Users/adam/.claude/plans/please-review-the-work-harmonic-cosmos.md"
SKILL_VERSION = "claude-blog/submit_draft_firestore.py v1"


def _read_env() -> tuple[str, str]:
    project_id = os.environ.get("QANT_BLOG_DRAFTS_PROJECT_ID")
    key_path = os.environ.get("QANT_BLOG_DRAFTS_WRITER_KEY")
    missing: list[str] = []
    if not project_id:
        missing.append("QANT_BLOG_DRAFTS_PROJECT_ID")
    if not key_path:
        missing.append("QANT_BLOG_DRAFTS_WRITER_KEY")
    if missing:
        print(
            f"Error: missing env var(s): {', '.join(missing)}.\n"
            f"See {PLAN_REF} § 'Firestore credential placement' for setup.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not Path(key_path).is_file():  # type: ignore[arg-type]
        print(
            f"Error: QANT_BLOG_DRAFTS_WRITER_KEY points at non-existent file: {key_path}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return project_id, key_path  # type: ignore[return-value]


def _key_email(key_path: str) -> str:
    """Pull ``client_email`` from the SA JSON so we can stamp it as keyId."""
    try:
        data = json.loads(Path(key_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return data.get("client_email", "") or ""


def submit(
    project_id: str,
    key_path: str,
    brand_slug: str,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Write the payload as a new doc under ``brands/{brand_slug}/drafts/``.

    Returns ``{"id": auto_id, "path": "brands/{slug}/drafts/{auto_id}"}``.

    Imports ``google.cloud.firestore`` lazily so the script's --help works
    even when the dep is not installed.
    """
    try:
        from google.cloud import firestore  # type: ignore[import-not-found]
        from google.cloud.firestore_v1 import SERVER_TIMESTAMP  # type: ignore[import-not-found]
        from google.oauth2 import service_account  # type: ignore[import-not-found]
    except ImportError as e:
        print(
            f"Error: required Python package missing ({e}). "
            f"Install with: pip install google-cloud-firestore",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    creds = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project_id, credentials=creds)

    # Pin brand_slug + producer telemetry. We do NOT overwrite caller-supplied
    # values for the article fields — that's the orchestrator's responsibility.
    doc: dict[str, Any] = dict(payload)
    doc["brand_slug"] = brand_slug
    doc.setdefault("contentType", "blog_post")
    doc["submittedBy"] = f"{SKILL_VERSION} on {socket.gethostname()}"
    doc["submittedAt"] = SERVER_TIMESTAMP
    doc["keyId"] = _key_email(key_path)

    drafts_col = (
        client.collection("brands").document(brand_slug).collection("drafts")
    )
    auto_ref = drafts_col.document()  # auto-id
    auto_ref.set(doc)
    return {"id": auto_ref.id, "path": f"brands/{brand_slug}/drafts/{auto_ref.id}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--brand-slug",
        required=True,
        help="Brand slug for the doc (e.g. redbridgecyber). Pinned into the payload.",
    )
    parser.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="Path to a JSON file with the draft payload (matches BlogDraft shape).",
    )
    args = parser.parse_args()

    project_id, key_path = _read_env()

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
        print(
            f"Error: payload must be a JSON object, got {type(payload).__name__}",
            file=sys.stderr,
        )
        return 2

    try:
        result = submit(project_id, key_path, args.brand_slug, payload)
    except Exception as e:  # noqa: BLE001  — surface raw Firestore errors
        print(f"Error: Firestore write failed: {e!r}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
