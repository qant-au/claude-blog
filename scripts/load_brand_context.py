#!/usr/bin/env python3
"""Resolve a qant brand directory and emit its env + identity as JSON.

Used by `/blog write --brand <slug>` and `/blog rewrite --brand <slug>` to
pick up the per-brand `BRAND_KEY` and `API_URL` needed to POST a finished
draft to the qant private API, and to inject a small brand-identity block
into the drafting prompt alongside `BRAND.md` / `VOICE.md`.

Brand directories live at `/Users/adam/Projects/qant/brands/<slug>/`. Each
contains:

* `.env`, `.env.stg`, `.env.dev` — simple KEY=VALUE env files.
* `.brand-seo.yml` — brand identity (display name, hosts, target keywords).

Env file selection:

* no flag       → `.env`
* `--staging`   → `.env.stg`
* `--development` → `.env.dev`

Env file parsing handles `KEY=VALUE` lines, comments (`#`), blank lines, and
optional surrounding quotes. It does NOT expand shell variables.

Two key names are accepted for compatibility with the existing brand env
files:

* `BRAND_KEY` or `NEXT_PUBLIC_BRAND_KEY` → emitted as `brand_key`
* `API_URL` (if absent, derived from `NEXT_PUBLIC_BRAND_ENV`: `stg` →
  `https://api-stg.qant.au`, `prod` → `https://api.qant.au`, `dev` →
  `http://localhost:8000`).

`.brand-seo.yml` is parsed defensively with a minimal stdlib YAML reader
(top-level scalars + the `canonical:` map + a `target_keywords:` list, plus
a `primary_author:` slug if present, plus the v2 ``content:`` block —
audience / strategy / plan / categories / url_pattern / default_author —
introduced by the QANT blog Phase E E2 change). PyYAML is not a dependency;
the loader extracts only the fields the blog skill needs and ignores
everything else.

Author auto-discovery
─────────────────────
Each brand directory may contain an ``authors/<slug>/`` subdir holding
``bio.md``, ``style.md``, ``byline.md`` for that author. The loader lists
the available slugs in the output as ``authors``. The orchestrator looks
up an author bundle in this brand-local directory FIRST, falling back to
``claude-blog/skills/blog/authors/<slug>/`` only when the slug is not
present under the brand.

The brand_key is treated as a secret: it is never logged to stderr, only
returned on stdout as part of the JSON payload. Callers that do not need it
(e.g. a dry-run) can pass `--redact-key` to receive `"brand_key": null`.

Usage:
    python3 load_brand_context.py --brand redbridgecyber --staging
    python3 load_brand_context.py --brand redbridgecyber --staging --redact-key

Exits non-zero on:
* unknown brand slug (directory missing)
* missing env file
* missing brand key in env file (cannot submit drafts without it)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

QANT_BRANDS_ROOT = Path("/Users/adam/Projects/qant/brands")

DEFAULT_API_URLS = {
    "stg": "https://api-stg.qant.au",
    "staging": "https://api-stg.qant.au",
    "prod": "https://api.qant.au",
    "production": "https://api.qant.au",
    "dev": "http://localhost:8000",
    "development": "http://localhost:8000",
}


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
    * `canonical.marketing` (top-level marketing URL)
    * `target_keywords` (list of strings, top-level)
    * `primary_author` (string, top-level slug)
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


def resolve_env_file(brand_dir: Path, staging: bool, development: bool) -> Path:
    if staging and development:
        raise ValueError("--staging and --development are mutually exclusive")
    if staging:
        return brand_dir / ".env.stg"
    if development:
        return brand_dir / ".env.dev"
    return brand_dir / ".env"


def load_brand_context(
    slug: str,
    staging: bool = False,
    development: bool = False,
    brands_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve the brand and return the context JSON-able dict.

    Raises FileNotFoundError if the brand dir or env file does not exist.
    Raises KeyError if no brand_key can be found in the env file.
    """
    root = brands_root if brands_root is not None else QANT_BRANDS_ROOT
    brand_dir = root / slug
    if not brand_dir.is_dir():
        raise FileNotFoundError(f"brand directory not found: {brand_dir}")

    env_file = resolve_env_file(brand_dir, staging, development)
    if not env_file.is_file():
        raise FileNotFoundError(f"env file not found: {env_file}")
    env = _parse_env_file(env_file)

    brand_key = env.get("BRAND_KEY") or env.get("NEXT_PUBLIC_BRAND_KEY")
    if not brand_key:
        raise KeyError(
            f"no BRAND_KEY or NEXT_PUBLIC_BRAND_KEY in {env_file}"
        )

    api_url = env.get("API_URL") or env.get("NEXT_PUBLIC_API_URL")
    if not api_url:
        env_label = env.get("NEXT_PUBLIC_BRAND_ENV") or env.get("BRAND_ENV")
        if env_label:
            api_url = DEFAULT_API_URLS.get(env_label.lower())
        if not api_url:
            # Sensible default by flag.
            if staging:
                api_url = DEFAULT_API_URLS["stg"]
            elif development:
                api_url = DEFAULT_API_URLS["dev"]
            else:
                api_url = DEFAULT_API_URLS["prod"]

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

    # Brand-local author auto-discovery (Phase E E1). Lists subdirectory
    # names under brands/<slug>/authors/. The orchestrator looks here FIRST
    # when resolving --author, falling back to skills/blog/authors/ only
    # when the slug is not present brand-locally.
    authors: list[str] = []
    authors_dir = brand_dir / "authors"
    if authors_dir.is_dir():
        authors = sorted(
            p.name for p in authors_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    return {
        "brand_slug": slug,
        "brand_dir": str(brand_dir),
        "env_file": str(env_file),
        "brand_key": brand_key,
        "api_url": api_url,
        "brand_domain": brand_domain,
        "brand_identity": identity,
        "authors": authors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--brand", required=True, help="Brand slug (directory name under qant/brands/)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staging", action="store_true", help="Use .env.stg")
    group.add_argument("--development", action="store_true", help="Use .env.dev")
    parser.add_argument(
        "--redact-key",
        action="store_true",
        help="Set brand_key to null in the output (for dry-runs/logs).",
    )
    parser.add_argument(
        "--brands-root",
        default=None,
        help="Override the brands root directory (for testing).",
    )
    args = parser.parse_args()

    brands_root = Path(args.brands_root) if args.brands_root else None

    try:
        ctx = load_brand_context(
            args.brand,
            staging=args.staging,
            development=args.development,
            brands_root=brands_root,
        )
    except (FileNotFoundError, KeyError, ValueError) as e:
        # Never echo the brand_key here; the failure path never has one anyway.
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.redact_key:
        ctx["brand_key"] = None

    # stdout is the only place the brand_key may appear.
    print(json.dumps(ctx, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
