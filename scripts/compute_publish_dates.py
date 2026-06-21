#!/usr/bin/env python3
"""Assign publish dates to approved articles per a brand's cadence config.

``/blog publish`` calls this between listing the approved queue and writing
articles to the brand site. For each approved article it computes the next
open publish date for that (author, kind), honouring:

* the per-brand cadence config (``brands/<slug>/docs/blog/publish-cadence.json``)
  — weekday(s), interval, and a launch-day batch;
* the dates ALREADY occupied on the brand site — so re-runs never double-book.
  Two content systems are supported: a TS registry
  (``brands/<slug>/lib/content/articles.ts``, e.g. redbridgecyber) or
  frontmatter markdown (``brands/<slug>/content/blog/**.md``, e.g. elliejames).
  The registry is used when it exists; otherwise the markdown corpus is read;
* idempotency — an approved article whose slug is already in the registry is
  reported ``action: "skip"`` (already published, awaiting DB cleanup).

The launch batch fills the first N slots of a kind onto ``launch_date`` (e.g.
the 3 perspective pieces that go live on launch day); subsequent pieces fall on
the weekly/however cadence. A single-weekday weekly cadence needs no interval —
"next occurrence of the weekday after the anchor" is already weekly. Interval
> 1 (monthly pillars) enforces a minimum gap from the latest same-kind date.

Pure functions (``parse_registry_articles``, ``find_rule``, ``compute_schedule``)
take text/dicts so they are unit-testable without the filesystem.

Usage:
    python3 compute_publish_dates.py --brand-slug redbridgecyber \
        --articles '<json array from list_approved_articles.py>'
    # optional overrides: --cadence <path> --articles-ts <path>

Output: JSON array of rows, each the input row plus ``date`` (YYYY-MM-DD) and
``action`` ("schedule" | "skip") + ``reason`` when skipped, sorted by date.

Exit codes: 0 ok · 1 IO/parse failure · 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

QANT_BRANDS_ROOT = Path("/Users/adam/Projects/qant/brands")
DEFAULT_AUTHOR = "red-bridge-cyber-team"
_HORIZON_DAYS = 2000  # loop backstop (~5.5 years) — far past any real schedule


# ── Registry parsing ─────────────────────────────────────────────────────────

def _array_body(text: str, name: str) -> str:
    """Return the substring inside the `[ ... ]` of `export const <name> = [`,
    string-aware so braces/brackets inside string literals don't miscount."""
    idx = text.find(name)
    if idx < 0:
        return ""
    lb = text.find("[", idx)
    if lb < 0:
        return ""
    depth = 0
    quote: str | None = None
    esc = False
    i = lb
    while i < len(text):
        c = text[i]
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[lb + 1:i]
        i += 1
    return ""


def _top_level_objects(body: str) -> list[str]:
    """Split an array body into its top-level `{ ... }` object literals,
    string-aware so nested objects (e.g. citabilityBlock) stay intact."""
    objs: list[str] = []
    depth = 0
    start: int | None = None
    quote: str | None = None
    esc = False
    for i, c in enumerate(body):
        if quote:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                quote = None
            continue
        if c in "'\"`":
            quote = c
            continue
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objs.append(body[start:i + 1])
                start = None
    return objs


def parse_registry_articles(ts_text: str) -> list[dict]:
    """Extract `{slug, kind, author, date}` for every entry in ALL_ARTICLES.

    `author` defaults to the brand team author when the entry omits it (the
    registry convention — person authors are explicit, team is the default).
    """
    out: list[dict] = []
    for obj in _top_level_objects(_array_body(ts_text, "ALL_ARTICLES")):
        slug = re.search(r"\bslug:\s*'([^']+)'", obj)
        kind = re.search(r"\bkind:\s*'([^']+)'", obj)
        edate = re.search(r"\bdate:\s*'([^']+)'", obj)
        author = re.search(r"\bauthor:\s*'([^']+)'", obj)
        if not (slug and kind and edate):
            continue
        out.append({
            "slug":   slug.group(1),
            "kind":   kind.group(1),
            "date":   edate.group(1),
            "author": author.group(1) if author else DEFAULT_AUTHOR,
        })
    return out


def _frontmatter(md_text: str) -> dict[str, str]:
    """Parse the leading `--- ... ---` YAML frontmatter as flat scalars.

    Stdlib only (no PyYAML). Handles `key: value`, surrounding quotes, and
    YAML block scalars (`>-` / `|`) by taking the key's value as empty — we
    only read scalar keys (slug/date/kind/author_slug), never block bodies.
    """
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] in (" ", "\t") or ":" not in raw:  # nested / continuation — ignore
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value and value[0] in (">", "|"):  # block scalar — value is on following lines
            value = ""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def parse_markdown_articles(content_dir: Path, default_author: str) -> list[dict]:
    """Extract `{slug, kind, date, author}` from every frontmatter markdown
    file under ``content_dir`` (recursively).

    For markdown brands the post's `author` frontmatter is a display name, not
    a slug, so occupancy is attributed to ``default_author`` (the brand's
    single author slug) unless the file carries an explicit ``author_slug``.
    ``kind`` defaults to ``spoke`` when absent (the /blog write default).
    Files missing slug or date are skipped (drafts-in-progress, partials).
    """
    out: list[dict] = []
    if not content_dir.is_dir():
        return out
    for md in sorted(content_dir.rglob("*.md")):
        fm = _frontmatter(md.read_text(encoding="utf-8"))
        slug = fm.get("slug") or md.stem
        edate = (fm.get("date") or "")[:10]
        if not slug or not edate:
            continue
        out.append({
            "slug":   slug,
            "kind":   fm.get("kind") or "spoke",
            "date":   edate,
            "author": fm.get("author_slug") or default_author,
        })
    return out


# ── Scheduling ───────────────────────────────────────────────────────────────

def find_rule(cadence: dict, author_slug: str, kind: str) -> dict | None:
    for r in cadence.get("rules", []):
        if r.get("author_slug") == author_slug and r.get("kind") == kind:
            return r
    return None


def _next_slot(rule: dict, occupied: set[date], launch: date) -> date:
    """Next unoccupied weekday slot for a rule, given dates already taken."""
    weekdays = rule.get("weekdays") or []
    interval = int(rule.get("interval_weeks") or 1)
    if occupied:
        anchor = max(occupied)
        min_gap = interval * 7 if interval > 1 else 1
    else:
        anchor = launch - timedelta(days=7)
        min_gap = 1
    candidate = anchor + timedelta(days=1)
    for _ in range(_HORIZON_DAYS):
        if (candidate.weekday() in weekdays
                and candidate not in occupied
                and candidate >= launch  # never schedule before launch_date
                and (candidate - anchor).days >= min_gap):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError(f"no open slot found within {_HORIZON_DAYS} days for {rule}")


_OUT_KEYS = (
    "draft_id", "brand_slug", "slug", "title",
    "author_slug", "category", "kind", "hero_image_url", "word_count",
)


def compute_schedule(cadence: dict, existing: list[dict], approved: list[dict]) -> list[dict]:
    """Assign a date (or skip) to each approved article. ``existing`` is the
    parsed registry; ``approved`` is processed in the given order (the caller
    passes them oldest-first so the launch batch fills in queue order)."""
    launch = date.fromisoformat(cadence["launch_date"])
    launch_batch = cadence.get("launch_batch", {})
    seen_slugs = {e["slug"] for e in existing}

    occupied: dict[tuple[str, str], set[date]] = {}
    launch_used: dict[tuple[str, str], int] = {}
    for e in existing:
        key = (e.get("author") or DEFAULT_AUTHOR, e["kind"])
        try:
            ed = date.fromisoformat(e["date"])
        except (ValueError, KeyError):
            continue
        occupied.setdefault(key, set()).add(ed)
        if ed == launch:
            launch_used[key] = launch_used.get(key, 0) + 1

    results: list[dict] = []
    for art in approved:
        row = {k: art.get(k) for k in _OUT_KEYS}
        slug = art.get("slug") or ""
        kind = art.get("kind") or "spoke"
        author = art.get("author_slug") or ""

        if slug in seen_slugs:
            results.append({**row, "date": None, "action": "skip",
                            "reason": "slug already in site registry (already published)"})
            continue

        rule = find_rule(cadence, author, kind)
        if rule is None:
            results.append({**row, "date": None, "action": "skip",
                            "reason": f"no cadence rule for ({author}, {kind})"})
            continue

        key = (author, kind)
        occ = occupied.setdefault(key, set())
        batch_size = launch_batch.get(kind)
        if isinstance(batch_size, int) and launch_used.get(key, 0) < batch_size:
            assigned = launch
            launch_used[key] = launch_used.get(key, 0) + 1
        else:
            assigned = _next_slot(rule, occ, launch)
        occ.add(assigned)
        seen_slugs.add(slug)
        results.append({**row, "date": assigned.isoformat(), "action": "schedule"})

    results.sort(key=lambda r: (r["date"] is None, r["date"] or ""))
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def _load(brand_slug: str, cadence_path: Path | None, ts_path: Path | None,
          brands_root: Path) -> tuple[dict, list[dict]]:
    """Return (cadence, existing) where ``existing`` is the brand's already-
    occupied articles. Source is the TS registry when present (or forced via
    ``--articles-ts``), else the frontmatter-markdown corpus."""
    brand_dir = brands_root / brand_slug
    cad = cadence_path or brand_dir / "docs" / "blog" / "publish-cadence.json"
    cadence = json.loads(cad.read_text(encoding="utf-8"))
    default_author = cadence.get("default_author") or DEFAULT_AUTHOR

    ts = ts_path or brand_dir / "lib" / "content" / "articles.ts"
    if ts.exists():
        return cadence, parse_registry_articles(ts.read_text(encoding="utf-8"))

    content_dir = brand_dir / "content" / "blog"
    return cadence, parse_markdown_articles(content_dir, default_author)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--brand-slug", required=True)
    ap.add_argument("--articles", required=True,
                    help="JSON array of approved rows (from list_approved_articles.py).")
    ap.add_argument("--cadence", type=Path, default=None,
                    help="Override the cadence config path.")
    ap.add_argument("--articles-ts", type=Path, default=None,
                    help="Override the registry articles.ts path.")
    ap.add_argument("--brands-root", type=Path, default=QANT_BRANDS_ROOT)
    args = ap.parse_args()

    try:
        approved = json.loads(args.articles)
        if not isinstance(approved, list):
            raise ValueError("--articles must be a JSON array")
    except ValueError as e:
        sys.stderr.write(f"error: bad --articles input: {e}\n")
        return 2

    try:
        cadence, existing = _load(args.brand_slug, args.cadence, args.articles_ts, args.brands_root)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    try:
        results = compute_schedule(cadence, existing, approved)
    except RuntimeError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
