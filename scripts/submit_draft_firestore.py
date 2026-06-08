#!/usr/bin/env python3
"""Write a finished blog draft + upsert its author into the qant-blog-drafts Firestore project.

Replaces the HTTP-based ``submit_draft.py`` for QANT workflows. Used by
``/blog write --brand <slug>`` after the FLOW review passes: the
orchestrator constructs the payload JSON from article state, then invokes
this script to ship it. See the producer-side plan at
``/Users/adam/.claude/plans/please-review-the-work-harmonic-cosmos.md``
for the architecture rationale (credential-blast-radius split: writer-only
SA on contributor machines; reader+deleter SA mounted into instance API
containers).

Data shape (Phase E4.5)
───────────────────────
The script writes two Firestore docs per call (sometimes one if the
author hasn't changed):

  brands/{brand_slug}/authors/{author_slug}     — upserted from the
      on-disk author bundle (bio.md + style.md + byline.md). Content-
      hashed so unchanged bundles are no-ops.

  brands/{brand_slug}/drafts/{auto_id}          — the article. ``author``
      field is just ``{slug, name}`` — bio and byline live on the author
      doc above and are joined client-side at render time.

The orchestrator MUST NOT include ``author.bio`` or ``author.byline``
in the payload; this script strips them defensively (with a stderr warning)
to enforce the shape.

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
        --author-bundle /path/to/brands/<brand>/authors/<author>/ \\
        --payload path/to/draft.json

The script:
* Validates the payload file is readable JSON and an object.
* Validates the author bundle directory has the three expected files.
* Computes a SHA-256 hash of the bundle (bio + style + byline) and
  upserts ``brands/{brand_slug}/authors/{author_slug}`` only when the
  hash differs from what's deployed (one read per submit; one write
  only on first run or when the bundle changes).
* Strips ``author.bio`` and ``author.byline`` from the draft payload
  if present (defensive — they belong on the author doc).
* Pins ``brand_slug`` and stamps producer-side telemetry
  (``submittedBy`` skill + hostname, ``submittedAt`` server timestamp,
  ``keyId`` writer-SA client_email).
* Writes the draft to ``brands/{brand_slug}/drafts/{auto_id}``.
* On any Firestore error: prints the exception to stderr, exits 1.

Requires the ``google-cloud-firestore`` package
(``pip install google-cloud-firestore``). Add the ``qant`` extra in
``pyproject.toml`` to install it alongside the skill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any

PLAN_REF = "/Users/adam/.claude/plans/please-review-the-work-harmonic-cosmos.md"
SKILL_VERSION = "claude-blog/submit_draft_firestore.py v2"

BUNDLE_FILES = ("bio.md", "style.md", "byline.md")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


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


def _parse_byline(text: str) -> tuple[str, str]:
    """Extract ``name`` and ``byline`` from byline.md's YAML frontmatter.

    Minimal parser — only the two keys we need. Returns ('', '') on miss
    so the caller can surface a clearer error.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return "", ""
    fm = m.group(1)
    name = byline = ""
    for line in fm.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k == "name":
            name = v
        elif k == "byline":
            byline = v
    return name, byline


def _load_bundle(bundle_dir: Path) -> dict[str, str]:
    """Read the three bundle files and the byline frontmatter.

    Returns a dict with: bio_md, style_md, byline_md, name, byline.
    """
    if not bundle_dir.is_dir():
        raise FileNotFoundError(f"author bundle directory not found: {bundle_dir}")
    contents: dict[str, str] = {}
    for fname in BUNDLE_FILES:
        p = bundle_dir / fname
        if not p.is_file():
            raise FileNotFoundError(f"author bundle missing {fname}: {p}")
        contents[fname.replace(".md", "_md")] = p.read_text(encoding="utf-8")
    name, byline = _parse_byline(contents["byline_md"])
    if not name:
        raise ValueError(
            f"author bundle {bundle_dir}/byline.md is missing the 'name:' "
            f"frontmatter field — cannot determine display name"
        )
    contents["name"] = name
    contents["byline"] = byline
    return contents


def _bundle_hash(bundle: dict[str, str]) -> str:
    """SHA-256 of bio+style+byline file bodies concatenated in fixed order."""
    h = hashlib.sha256()
    for key in ("bio_md", "style_md", "byline_md"):
        h.update(bundle[key].encode("utf-8"))
        h.update(b"\n--bundle-sep--\n")
    return h.hexdigest()


def _upsert_author(
    client,
    SERVER_TIMESTAMP,
    brand_slug: str,
    author_slug: str,
    bundle: dict[str, str],
) -> str:
    """Upsert the per-author doc. Returns one of: 'created', 'updated', 'noop'."""
    bundle_hash = _bundle_hash(bundle)
    author_ref = (
        client.collection("brands").document(brand_slug)
        .collection("authors").document(author_slug)
    )
    snap = author_ref.get()
    if snap.exists:
        existing = snap.to_dict() or {}
        if existing.get("bundle_hash") == bundle_hash:
            return "noop"
        author_ref.update(
            {
                "name": bundle["name"],
                "byline": bundle["byline"],
                "bio": bundle["bio_md"],
                "bundle_hash": bundle_hash,
                "updated_at": SERVER_TIMESTAMP,
            }
        )
        return "updated"
    author_ref.set(
        {
            "slug": author_slug,
            "brand_slug": brand_slug,
            "name": bundle["name"],
            "byline": bundle["byline"],
            "bio": bundle["bio_md"],
            "bundle_hash": bundle_hash,
            "created_at": SERVER_TIMESTAMP,
            "updated_at": SERVER_TIMESTAMP,
        }
    )
    return "created"


def submit(
    project_id: str,
    key_path: str,
    brand_slug: str,
    bundle_dir: Path,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Upsert the author, write the draft, return paths for both.

    Returns ``{"author_path", "author_action", "draft_id", "draft_path"}``.

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

    # The author slug is the bundle directory name.
    author_slug = bundle_dir.name
    bundle = _load_bundle(bundle_dir)

    creds = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project_id, credentials=creds)

    # Phase 1: author upsert.
    action = _upsert_author(client, SERVER_TIMESTAMP, brand_slug, author_slug, bundle)

    # Phase 2: build the draft doc. Strip any bio/byline the caller leaked
    # into author{} — they belong on the author doc, not on every draft.
    doc: dict[str, Any] = dict(payload)
    author = dict(doc.get("author") or {})
    leaked = [k for k in ("bio", "byline") if k in author]
    if leaked:
        print(
            f"warn: dropping author.{','.join(leaked)} from draft payload "
            f"(they live on brands/{brand_slug}/authors/{author_slug})",
            file=sys.stderr,
        )
        for k in leaked:
            author.pop(k, None)
    # The orchestrator may pass author.slug + author.name; enforce them
    # against the bundle's canonical values so the join key + UI label
    # always match.
    author["slug"] = author_slug
    author["name"] = bundle["name"]
    doc["author"] = author

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
    return {
        "author_path": f"brands/{brand_slug}/authors/{author_slug}",
        "author_action": action,
        "draft_id": auto_ref.id,
        "draft_path": f"brands/{brand_slug}/drafts/{auto_ref.id}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--brand-slug",
        required=True,
        help="Brand slug for the doc (e.g. redbridgecyber). Pinned into the payload.",
    )
    parser.add_argument(
        "--author-bundle",
        required=True,
        type=Path,
        help="Path to the author bundle directory (brands/<brand>/authors/<author>/) — "
             "the directory name is the author slug; contents are upserted into "
             "brands/{brand_slug}/authors/{author_slug}.",
    )
    parser.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="Path to a JSON file with the draft payload (matches BlogDraft shape, "
             "minus author.bio / author.byline — those live on the author doc).",
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
        result = submit(project_id, key_path, args.brand_slug, args.author_bundle, payload)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  — surface raw Firestore errors
        print(f"Error: Firestore write failed: {e!r}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
