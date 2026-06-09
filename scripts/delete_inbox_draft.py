#!/usr/bin/env python3
"""Delete a draft from the qant-blog-drafts inbox.

Used by ``/blog rewrite --from-queue`` after the rewritten draft has been
successfully submitted (Phase 5.6) — the original flagged doc is now
superseded and has no reason to exist. Replaces the older
``clear_review_state.py`` step in the queue-drain flow; the cleared-flag
approach left both pre- and post-rewrite copies in the inbox, which the
operator saw as duplicates in the Blog Manager UI.

This script unconditionally deletes the doc. The orchestrator is
responsible for ordering the call AFTER a confirmed submit so that a
submit failure cannot strand the original.

Environment
-----------
* ``QANT_BLOG_DRAFTS_PROJECT_ID``
* ``QANT_BLOG_DRAFTS_WRITER_KEY``

Both required; exits 2 if missing.

Usage
-----
    python3 delete_inbox_draft.py \\
        --brand-slug redbridgecyber \\
        --draft-id  Y14iwD70ljgFIEW5Mihi \\
        --reason    "superseded by rewrite via /blog rewrite --from-queue"

The ``--reason`` flag is optional and is purely audit-side: it's printed
to stdout alongside the success line so it lands in the orchestrator's
log. Firestore receives only the delete; no tombstone is written.

Exit codes
----------
* 0 — doc deleted, or already absent (idempotent).
* 1 — Firestore error (network / permissions / unexpected).
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
        help="Optional audit note printed alongside the success line.",
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
        # Idempotent: nothing to delete is success. The orchestrator might
        # call this twice (e.g. after a partial retry) and that should not
        # be a hard failure.
        print(f"already_absent brands/{args.brand_slug}/drafts/{args.draft_id}")
        return 0

    try:
        ref.delete()
    except Exception as exc:  # pylint: disable=broad-except
        sys.stderr.write(f"error: Firestore delete failed: {exc}\n")
        return 1

    suffix = f" reason={args.reason!r}" if args.reason else ""
    print(f"deleted brands/{args.brand_slug}/drafts/{args.draft_id}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
