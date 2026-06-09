#!/usr/bin/env python3
"""Clear the ``review_state`` field on a draft after a successful rewrite.

Used by ``/blog rewrite --from-queue`` after Phase 7.5 submits the rewritten
draft. Removes the ``review_state`` field from the original (flagged)
Firestore doc so a subsequent ``list_pending_rewrites.py`` call does not
re-surface it.

This script does NOT delete the draft doc itself; only the ``review_state``
field. The draft remains visible in the Blog Manager UI under whatever
lifecycle position it occupies. If the orchestrator chose to re-submit the
rewritten content as a new doc (the current submit_draft_firestore.py
behaviour — no slug-based upsert), the old flagged doc and the new
rewritten doc both exist; clearing the flag on the old one stops it being
re-queued. The deduplication of the two docs is a separate concern handled
elsewhere (see the slug-based dedupe script in the qant workspace).

Environment
-----------
* ``QANT_BLOG_DRAFTS_PROJECT_ID``
* ``QANT_BLOG_DRAFTS_WRITER_KEY``

Both required; exits 2 if missing.

Usage
-----
    python3 clear_review_state.py \\
        --brand-slug redbridgecyber \\
        --draft-id  Y14iwD70ljgFIEW5Mihi

Optional ``--reason "<text>"`` records a short note on the doc as
``review_state_cleared_at`` (server timestamp) and ``review_state_cleared_reason``,
for audit visibility. Omit to clear silently.

Exit codes
----------
* 0 — field cleared (or already absent).
* 1 — Firestore error / doc missing.
* 2 — env vars missing or SA key path unreadable.
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--brand-slug", required=True)
    ap.add_argument("--draft-id", required=True)
    ap.add_argument(
        "--reason",
        default=None,
        help="Optional audit note recorded as review_state_cleared_reason.",
    )
    args = ap.parse_args()

    project, key_path = _env()

    try:
        from google.cloud import firestore  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except ImportError as exc:
        sys.stderr.write(
            f"error: required Python package missing ({exc}). "
            "Install with `pip install google-cloud-firestore`.\n"
        )
        return 2

    creds = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project, credentials=creds)

    ref = (
        client.collection("brands")
        .document(args.brand_slug)
        .collection("drafts")
        .document(args.draft_id)
    )

    try:
        snap = ref.get()
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write(f"error: Firestore read failed: {exc}\n")
        return 1

    if not snap.exists:
        sys.stderr.write(
            f"error: draft {args.draft_id} not found under "
            f"brands/{args.brand_slug}/drafts.\n"
        )
        return 1

    update: dict = {"review_state": firestore.DELETE_FIELD}
    if args.reason:
        update["review_state_cleared_reason"] = args.reason
    update["review_state_cleared_at"] = firestore.SERVER_TIMESTAMP

    try:
        ref.update(update)
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write(f"error: Firestore update failed: {exc}\n")
        return 1

    print(
        f"cleared review_state on brands/{args.brand_slug}/drafts/{args.draft_id}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
