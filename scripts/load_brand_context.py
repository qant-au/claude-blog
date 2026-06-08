#!/usr/bin/env python3
"""Resolve a qant brand directory and emit its identity + env as JSON.

Used by ``/blog write`` / ``/blog rewrite`` to inject brand identity into
the drafting prompt and to surface the brand-local author list for the
author picker. Phase E4.5 removed the env-flag selector and dropped the
HTTP-submission auth (brand_key / api_url) from the output — the new
submit path writes directly to the qant-blog-drafts Firestore project
via env-var-based SA auth, not via the per-brand bearer key.

Brand directories live at ``/Users/adam/Projects/qant/brands/<slug>/``.
Each contains:

* one of ``.env``, ``.env.stg``, ``.env.dev`` — simple KEY=VALUE env file.
* ``.brand-seo.yml`` — brand identity (display name, hosts, content scope).

Env file selection (E4.5 — flag removed)
────────────────────────────────────────
Tries ``.env`` → ``.env.stg`` → ``.env.dev`` in order and uses the first
existing file. The only field the loader cares about from env now is
``NEXT_PUBLIC_BRAND_DOMAIN`` (the canonical brand hostname). Brands run
on a single canonical domain regardless of which staging URL the team
happens to be testing today.

``.brand-seo.yml`` is parsed defensively with a minimal stdlib YAML reader
(top-level scalars + ``canonical:`` map + ``target_keywords:`` list +
``primary_author:`` scalar + v2 ``content:`` block — audience / strategy /
plan / categories / url_pattern / default_author). PyYAML is not a
dependency.

Authors
───────
Authors live in the ``qant-blog-drafts`` Firestore project under
``brands/{brand_slug}/authors/*`` (managed via the Blog Manager UI in the
consumer app). The on-disk ``brands/<slug>/authors/`` bundles were
retired in Phase F-post; the brand-context loader no longer enumerates
them.

The ``--list-authors --brand <slug>`` mode hits qant-blog-drafts directly
and emits ``[{slug, name, byline}, ...]`` for the skill's author picker.
Requires ``QANT_BLOG_DRAFTS_PROJECT_ID`` + ``QANT_BLOG_DRAFTS_WRITER_KEY``
to be set (same env vars the draft-submitter uses).

Brand enumeration
─────────────────
``--list-brands`` emits ``[{slug, display_name}, ...]`` for every brand
under the brands root that has a ``.brand-seo.yml``. The skill uses this
for the interactive brand picker when ``--brand`` is omitted.

Usage:
    python3 load_brand_context.py --brand redbridgecyber
    python3 load_brand_context.py --list-brands
    python3 load_brand_context.py --list-authors --brand redbridgecyber

Exits non-zero on:
* unknown brand slug (directory missing)
* no env file present (loader expected ``.env`` / ``.env.stg`` / ``.env.dev``)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

QANT_BRANDS_ROOT = Path("/Users/adam/Projects/qant/brands")

# Tried in order; first existing file wins. Authoritative for the loader.
ENV_FILE_PRECEDENCE: tuple[str, ...] = (".env", ".env.stg", ".env.dev")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal `.env` parser. Returns {key: value}.

    Handles:
    * comments starting with `#`
    * blank lines
    * `KEY=VALUE` and `KEY="VALUE"` and `KEY='VALUE'`
    * `export KEY=VALUE` (strips the `export ` prefix)

    Does NOT handle shell expansion, line continuations, or `${VAR}`.
    """
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip inline trailing comments only for unquoted values.
        if value and value[0] not in {'"', "'"} and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        # Strip a single matching pair of surrounding quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _parse_brand_seo_yml(path: Path) -> dict[str, Any]:
    """Defensive minimal YAML reader for `.brand-seo.yml`.

    Extracts only the fields the blog skill cares about. Returns an empty
    dict if the file is missing or malformed. Does NOT raise on bad YAML —
    brand identity is decorative; the env file is the load-bearing part.

    Fields extracted (all optional):
    * `brand` (slug)
    * `display_name`
    * `country`
    * `legal_entity`
    * `primary_author`
    * `canonical.marketing` (top-level marketing URL)
    * `target_keywords` (list of strings, top-level)
    * `content.{audience,strategy,plan,categories,url_pattern,default_author}` (Phase E E2)
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip comments and blank lines.
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level scalar `key: value`.
        if not line.startswith(" ") and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Strip inline comment.
            if " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            # Strip surrounding quotes.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if value:
                # Top-level scalar.
                if key in {
                    "brand",
                    "display_name",
                    "country",
                    "legal_entity",
                    "primary_author",
                }:
                    out[key] = value
            else:
                # Block follows. Pick up nested fields we care about.
                block_lines: list[str] = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt and not nxt.startswith((" ", "\t")) and not nxt.startswith("#"):
                        break
                    block_lines.append(nxt)
                    j += 1
                if key == "canonical":
                    for bl in block_lines:
                        bl_stripped = bl.strip()
                        if bl_stripped.startswith("marketing:"):
                            v = bl_stripped.split(":", 1)[1].strip()
                            # marketing: https://... — the colon in URL is fine
                            # because we only split once and we strip whitespace.
                            if v:
                                out.setdefault("canonical", {})["marketing"] = v
                elif key == "target_keywords":
                    kws: list[str] = []
                    for bl in block_lines:
                        bl_stripped = bl.strip()
                        if bl_stripped.startswith("- "):
                            kw = bl_stripped[2:].strip()
                            if len(kw) >= 2 and kw[0] == kw[-1] and kw[0] in {'"', "'"}:
                                kw = kw[1:-1]
                            if kw:
                                kws.append(kw)
                    if kws:
                        out["target_keywords"] = kws
                elif key == "content":
                    # v2 brand-seo schema (Phase E E2): content: { audience,
                    # strategy, plan, categories[], url_pattern,
                    # default_author }. Single-indent nested keys; categories
                    # is a list of bare strings ("- email", "- speed", ...).
                    content: dict[str, Any] = {}
                    current_list_key: str | None = None
                    current_list: list[str] = []
                    for bl in block_lines:
                        if not bl.strip() or bl.lstrip().startswith("#"):
                            continue
                        # List item belonging to the most recent scalar that
                        # opened a block.
                        if bl.lstrip().startswith("- "):
                            if current_list_key:
                                v = bl.lstrip()[2:].strip()
                                if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
                                    v = v[1:-1]
                                if v:
                                    current_list.append(v)
                            continue
                        # Scalar `  key: value` or block-opener `  key:`.
                        if ":" in bl:
                            # Commit any open list before starting the next key.
                            if current_list_key:
                                content[current_list_key] = current_list
                                current_list_key = None
                                current_list = []
                            ck, _, cv = bl.partition(":")
                            ck = ck.strip()
                            cv = cv.strip()
                            if " #" in cv:
                                cv = cv.split(" #", 1)[0].rstrip()
                            if len(cv) >= 2 and cv[0] == cv[-1] and cv[0] in {'"', "'"}:
                                cv = cv[1:-1]
                            if cv:
                                content[ck] = cv
                            else:
                                # Block opener — collect list items below.
                                current_list_key = ck
                                current_list = []
                    if current_list_key:
                        content[current_list_key] = current_list
                    if content:
                        out["content"] = content
                i = j
                continue
        i += 1
    return out


def resolve_env_file(brand_dir: Path) -> Path | None:
    """Return the first existing env file under ``brand_dir`` per ENV_FILE_PRECEDENCE.

    Returns None when no env file is present. The loader treats that as
    a soft miss (brand_domain will be derived from the YAML's
    canonical.marketing) rather than an error.
    """
    for fname in ENV_FILE_PRECEDENCE:
        candidate = brand_dir / fname
        if candidate.is_file():
            return candidate
    return None


def load_brand_context(
    slug: str,
    *,
    brands_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve the brand and return the context JSON-able dict.

    Raises FileNotFoundError if the brand dir does not exist.
    """
    root = brands_root if brands_root is not None else QANT_BRANDS_ROOT
    brand_dir = root / slug
    if not brand_dir.is_dir():
        raise FileNotFoundError(f"brand directory not found: {brand_dir}")

    env_file = resolve_env_file(brand_dir)
    env: dict[str, str] = _parse_env_file(env_file) if env_file else {}

    identity = _parse_brand_seo_yml(brand_dir / ".brand-seo.yml")

    # Canonical brand domain — single source of truth is the env var
    # (NEXT_PUBLIC_BRAND_DOMAIN), added by Phase E E2. Falls back to the
    # YAML's canonical.marketing URL host if the env var is unset (older
    # brands that haven't migrated yet).
    brand_domain = env.get("NEXT_PUBLIC_BRAND_DOMAIN") or ""
    if not brand_domain:
        canonical_marketing = (identity.get("canonical") or {}).get("marketing", "")
        if canonical_marketing:
            # Strip protocol + trailing slash for a bare hostname.
            bd = canonical_marketing.split("://", 1)[-1]
            brand_domain = bd.rstrip("/").split("/", 1)[0]

    # Authors are no longer enumerated from disk (Phase F-post retired the
    # brands/<slug>/authors/ bundles). Use --list-authors --brand <slug>
    # to fetch the current list from qant-blog-drafts.
    return {
        "brand_slug": slug,
        "brand_dir": str(brand_dir),
        "env_file": str(env_file) if env_file else None,
        "brand_domain": brand_domain,
        "brand_identity": identity,
    }


def list_brands(brands_root: Path | None = None) -> list[dict[str, str]]:
    """Enumerate every brand-dir under ``brands_root`` that has a ``.brand-seo.yml``.

    Returns sorted list of ``{slug, display_name}``. Used by the skill's
    interactive brand picker when ``--brand`` is omitted.
    """
    root = brands_root if brands_root is not None else QANT_BRANDS_ROOT
    out: list[dict[str, str]] = []
    if not root.is_dir():
        return out
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        seo_yml = p / ".brand-seo.yml"
        if not seo_yml.is_file():
            continue
        identity = _parse_brand_seo_yml(seo_yml)
        display = identity.get("display_name") or identity.get("brand") or p.name
        out.append({"slug": p.name, "display_name": display})
    return out


def list_authors_from_drafts(brand_slug: str) -> list[dict[str, str]]:
    """Fetch ``brands/{brand_slug}/authors/*`` from qant-blog-drafts.

    Returns ``[{slug, name, byline}, ...]`` sorted by slug. Used by the
    skill's author picker when ``--author`` is omitted on ``/blog write``.

    Env vars ``QANT_BLOG_DRAFTS_PROJECT_ID`` and ``QANT_BLOG_DRAFTS_WRITER_KEY``
    are required (same pair the draft-submitter uses).
    """
    project_id = os.environ.get("QANT_BLOG_DRAFTS_PROJECT_ID")
    key_path   = os.environ.get("QANT_BLOG_DRAFTS_WRITER_KEY")
    if not project_id or not key_path:
        raise RuntimeError(
            "QANT_BLOG_DRAFTS_PROJECT_ID and QANT_BLOG_DRAFTS_WRITER_KEY must "
            "be set to list authors from qant-blog-drafts."
        )
    if not Path(key_path).is_file():
        raise RuntimeError(
            f"QANT_BLOG_DRAFTS_WRITER_KEY points at non-existent file: {key_path}"
        )

    try:
        from google.cloud import firestore  # type: ignore[import-not-found]
        from google.oauth2 import service_account  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            f"google-cloud-firestore not installed ({e}). "
            f"Install with: pip install google-cloud-firestore"
        ) from None

    creds  = service_account.Credentials.from_service_account_file(key_path)
    client = firestore.Client(project=project_id, credentials=creds)
    col = client.collection("brands").document(brand_slug).collection("authors")
    out: list[dict[str, str]] = []
    for snap in col.stream():
        d = snap.to_dict() or {}
        out.append({
            "slug":   snap.id,
            "name":   d.get("name") or snap.id,
            "byline": d.get("byline") or "",
        })
    return sorted(out, key=lambda r: r["slug"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--brand",
        help="Brand slug (directory name under qant/brands/). Returns the full brand context.",
    )
    mode.add_argument(
        "--list-brands",
        action="store_true",
        help="List every brand with a .brand-seo.yml as JSON [{slug, display_name}, ...]. Used by the /blog skill brand picker.",
    )
    parser.add_argument(
        "--list-authors",
        action="store_true",
        help="With --brand: emit [{slug, name, byline}, ...] for that brand's "
             "authors fetched from qant-blog-drafts (instead of the full brand context).",
    )
    parser.add_argument(
        "--brands-root",
        default=None,
        help="Override the brands root directory (for testing).",
    )
    args = parser.parse_args()

    brands_root = Path(args.brands_root) if args.brands_root else None

    if args.list_brands:
        print(json.dumps(list_brands(brands_root), indent=2, sort_keys=True))
        return 0

    if args.list_authors:
        if not args.brand:
            print("Error: --list-authors requires --brand <slug>.", file=sys.stderr)
            return 2
        try:
            authors = list_authors_from_drafts(args.brand)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(authors, indent=2, sort_keys=True))
        return 0

    try:
        ctx = load_brand_context(args.brand, brands_root=brands_root)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    print(json.dumps(ctx, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
