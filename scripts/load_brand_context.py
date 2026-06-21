#!/usr/bin/env python3
"""Resolve a qant brand directory and emit its identity + env as JSON.

Used by ``/blog write`` / ``/blog rewrite`` to inject brand identity into
the drafting prompt and to surface the brand-local author list for the
author picker. Since the 2026-06 brand-key migration every data call
(authors, drafts, images, rewrite queue) goes over the QANT brand-blog
API authenticated with the brand's own key — see scripts/qant_api.py for
how the key + API base are resolved from the brand env file.

Brand directories live at ``/Users/adam/Projects/qant/brands/<slug>/``.
Each contains:

* one of ``.env.prod``, ``.env`` — simple KEY=VALUE env file.
* ``.brand-seo.yml`` — brand identity (display name, hosts, content scope).

Env file selection (production-only)
────────────────────────────────────────
Tries ``.env.prod`` → ``.env`` in order and uses the first existing file
(staging env files are never read — the /blog skill is production-only;
see scripts/qant_api.py). The only field the loader cares about from env now
is ``NEXT_PUBLIC_BRAND_DOMAIN`` (the canonical brand hostname). Brands run
on a single canonical domain regardless of environment.

``.brand-seo.yml`` is parsed defensively with a minimal stdlib YAML reader
(top-level scalars + ``canonical:`` map + ``target_keywords:`` list +
``primary_author:`` scalar + v2 ``content:`` block — audience / strategy /
plan / categories / url_pattern / default_author). PyYAML is not a
dependency.

Authors
───────
Authors live in the instance Firestore attached to the brand and are
managed in Axiom (Instances → Brands → Authors). The skill reads them
over the brand-key API (``GET /brand/blog/authors``); the on-disk
``brands/<slug>/authors/`` bundles were retired in Phase F-post.

The ``--list-authors --brand <slug>`` mode emits
``[{slug, name, byline}, ...]`` for the skill's author picker;
``--get-author <slug> --brand <slug>`` emits the full voice payload.
Auth comes from ``NEXT_PUBLIC_BRAND_KEY`` in the brand env file — no
service-account env vars are needed any more.

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
* no env file present (loader expected ``.env.prod`` / ``.env``)
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
# Production-only: staging env files (.env.stg / .env.dev) are never read.
ENV_FILE_PRECEDENCE: tuple[str, ...] = (".env.prod", ".env")


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
                            # Strip an inline `# comment` on unquoted values.
                            if kw and kw[0] not in {'"', "'"} and " #" in kw:
                                kw = kw.split(" #", 1)[0].rstrip()
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
                                # Strip an inline `# comment` on unquoted values.
                                if v and v[0] not in {'"', "'"} and " #" in v:
                                    v = v.split(" #", 1)[0].rstrip()
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


def _api():
    """Lazy import of the brand-key API client (scripts/qant_api.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "qant_api", Path(__file__).resolve().parent / "qant_api.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def list_authors_from_drafts(brand_slug: str, _request=None, *, brands_root: Path | None = None) -> list[dict[str, str]]:
    """Fetch the brand's authors over the brand-key API.

    Returns ``[{slug, name, byline}, ...]`` sorted by slug. Used by the
    skill's author picker when ``--author`` is omitted on ``/blog write``.

    ``_request`` is a test seam; production callers omit it.
    """
    request_fn = _request if _request is not None else _api().request
    kw = {"brands_root": brands_root} if (_request is None and brands_root is not None) else {}
    resp = request_fn(brand_slug, "GET", "/brand/blog/authors", None, **kw)
    out = [
        {
            "slug":   a.get("slug") or "",
            "name":   a.get("name") or a.get("slug") or "",
            "byline": a.get("byline") or "",
        }
        for a in (resp or {}).get("items", [])
    ]
    return sorted(out, key=lambda r: r["slug"])


def get_author_from_drafts(
    brand_slug: str,
    author_slug: str,
    _request=None,
    *,
    brands_root: Path | None = None,
) -> dict:
    """Fetch ONE full author doc over the brand-key API.

    This is the /blog skill's single author surface: the returned dict
    carries the complete Axiom-managed voice payload (name, byline, bio,
    target_audience, locale, pronoun_stance, register, banned_phrases,
    signature_moves, writing_style) plus ``slug``. Skills must use this,
    never on-disk author-profile-*.json exports, which go stale the moment
    the profile is edited in Axiom.

    ``_request`` is a test seam; production callers omit it.
    """
    request_fn = _request if _request is not None else _api().request
    kw = {"brands_root": brands_root} if (_request is None and brands_root is not None) else {}
    try:
        doc = request_fn(brand_slug, "GET", f"/brand/blog/authors/{author_slug}", None, **kw)
    except RuntimeError as e:
        # qant_api.ApiError subclasses RuntimeError; match on .status so the
        # check survives separate module loads (the test harness imports
        # scripts by path, which creates distinct class objects).
        if getattr(e, "status", None) == 404:
            raise LookupError(
                f"author '{author_slug}' not found for brand '{brand_slug}'. "
                f"Create or edit authors in Axiom (Instances → Brands → Authors)."
            ) from None
        raise
    doc = dict(doc or {})
    doc.setdefault("slug", author_slug)
    return doc


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
             "authors fetched over the brand-key API (instead of the full brand context).",
    )
    parser.add_argument(
        "--get-author",
        metavar="AUTHOR_SLUG",
        help="With --brand: emit the FULL author doc (every Axiom-managed voice "
             "field) over the brand-key API as JSON. This is the skill's only "
             "author surface; never read author-profile-*.json exports.",
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
            authors = list_authors_from_drafts(args.brand, brands_root=brands_root)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(authors, indent=2, sort_keys=True))
        return 0

    if args.get_author:
        if not args.brand:
            print("Error: --get-author requires --brand <slug>.", file=sys.stderr)
            return 2
        try:
            author = get_author_from_drafts(args.brand, args.get_author, brands_root=brands_root)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        except LookupError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        # default=str: Firestore timestamps (created_at / updated_at /
        # mirrored_at) aren't JSON-native; render them as ISO-ish strings.
        print(json.dumps(author, indent=2, sort_keys=True, default=str))
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
