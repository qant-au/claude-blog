"""Behavioral tests for scripts/compute_publish_dates.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = ROOT / "scripts" / "compute_publish_dates.py"


def _import_helper():
    spec = importlib.util.spec_from_file_location("compute_publish_dates", HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


mod = _import_helper()


CADENCE = {
    "brand_slug": "redbridgecyber",
    "launch_date": "2026-06-17",  # Wednesday
    "rules": [
        {"author_slug": "adam-burgess", "kind": "perspective",
         "weekdays": [3], "interval_weeks": 1},                 # Thursdays
        {"author_slug": "red-bridge-cyber-team", "kind": "spoke",
         "weekdays": [0, 2, 4], "interval_weeks": 1},           # Mon/Wed/Fri
        {"author_slug": "red-bridge-cyber-team", "kind": "pillar",
         "weekdays": [3], "interval_weeks": 4},                 # ~monthly Thu
    ],
    "launch_batch": {"perspective": 3},
}


def _approved(slug, kind, author, **extra):
    row = {"draft_id": f"bpost_{slug}", "slug": slug, "title": slug.title(),
           "author_slug": author, "category": "security", "kind": kind,
           "hero_image_url": "", "word_count": 800}
    row.update(extra)
    return row


# ── Registry parsing ──────────────────────────────────────────────────────────

def test_parse_registry_handles_nested_objects():
    ts = """
export const ALL_ARTICLES: ReadonlyArray<Article> = [
  {
    slug: 'a-pillar',
    kind: 'pillar',
    category: 'visibility',
    citabilityBlock: { intro: 'has a } brace and date: trap inside', bullets: ['x'] },
    date: '2026-06-10',
    num: '01',
  },
  {
    slug: 'adam-essay',
    kind: 'perspective',
    author: 'adam-burgess',
    category: 'security',
    citabilityBlock: 'plain string',
    date: '2026-06-17',
    num: '02',
  },
];
export const ALL_MICROANSWERS: ReadonlyArray<Microanswer> = [
  { slug: 'ignore-me', pillarId: 'x', question: 'q', answer: 'a', date: '2026-06-09' },
];
"""
    entries = mod.parse_registry_articles(ts)
    slugs = {e["slug"] for e in entries}
    assert slugs == {"a-pillar", "adam-essay"}          # microanswer excluded
    by_slug = {e["slug"]: e for e in entries}
    assert by_slug["a-pillar"]["author"] == "red-bridge-cyber-team"  # default
    assert by_slug["adam-essay"]["author"] == "adam-burgess"
    assert by_slug["adam-essay"]["date"] == "2026-06-17"


# ── Launch batch ──────────────────────────────────────────────────────────────

def test_launch_batch_first_three_perspectives_go_to_launch_day():
    approved = [_approved(f"p{i}", "perspective", "adam-burgess") for i in range(5)]
    out = mod.compute_schedule(CADENCE, [], approved)
    dates = {r["slug"]: r["date"] for r in out}
    # First 3 → launch day; #4, #5 → following Thursdays.
    assert dates["p0"] == "2026-06-17"
    assert dates["p1"] == "2026-06-17"
    assert dates["p2"] == "2026-06-17"
    assert dates["p3"] == "2026-06-18"   # Thursday after launch
    assert dates["p4"] == "2026-06-25"
    assert all(r["action"] == "schedule" for r in out)


def test_launch_batch_respects_already_published_launch_pieces():
    existing = [{"slug": "live1", "kind": "perspective",
                 "author": "adam-burgess", "date": "2026-06-17"}]
    approved = [_approved(f"p{i}", "perspective", "adam-burgess") for i in range(3)]
    out = mod.compute_schedule(CADENCE, existing, approved)
    dates = [r["date"] for r in sorted(out, key=lambda r: r["slug"])]
    # Only 2 launch slots remain (3 - 1 already live) → 2 more on launch day,
    # the 3rd rolls to the next Thursday.
    assert dates.count("2026-06-17") == 2
    assert "2026-06-18" in dates


# ── Weekly / weekday cadence ──────────────────────────────────────────────────

def test_perspective_weekly_after_existing():
    existing = [{"slug": "x", "kind": "perspective",
                 "author": "adam-burgess", "date": "2026-07-02"}]  # a Thursday
    # batch already satisfied (1 existing, but at a non-launch date) — still,
    # launch_used counts only launch-day entries, so batch would apply. Use a
    # post-batch scenario by marking 3 launch-day pieces:
    existing += [{"slug": f"l{i}", "kind": "perspective",
                  "author": "adam-burgess", "date": "2026-06-17"} for i in range(3)]
    out = mod.compute_schedule(CADENCE, existing, [_approved("p", "perspective", "adam-burgess")])
    # Latest occupied is 2026-07-02 (Thu) → next Thursday.
    assert out[0]["date"] == "2026-07-09"


def test_spoke_mwf_cadence():
    existing = [{"slug": "s0", "kind": "spoke",
                 "author": "red-bridge-cyber-team", "date": "2026-06-19"}]  # Friday
    approved = [_approved(f"s{i}", "spoke", "red-bridge-cyber-team") for i in range(1, 4)]
    out = mod.compute_schedule(CADENCE, existing, approved)
    dates = [r["date"] for r in out]
    # After Fri 06-19 → Mon 06-22, Wed 06-24, Fri 06-26.
    assert dates == ["2026-06-22", "2026-06-24", "2026-06-26"]
    assert all(date_is_mwf(d) for d in dates)


def date_is_mwf(s):
    from datetime import date
    return date.fromisoformat(s).weekday() in (0, 2, 4)


def test_pillar_monthly_interval():
    existing = [{"slug": "pil0", "kind": "pillar",
                 "author": "red-bridge-cyber-team", "date": "2026-06-04"}]  # Thursday
    out = mod.compute_schedule(CADENCE, existing,
                               [_approved("pil1", "pillar", "red-bridge-cyber-team")])
    # >= 4 weeks (28 days) after 06-04 → 07-02 (next Thursday meeting the gap).
    assert out[0]["date"] == "2026-07-02"


# ── Idempotency + unknown rule ────────────────────────────────────────────────

def test_existing_slug_is_skipped():
    existing = [{"slug": "dup", "kind": "perspective",
                 "author": "adam-burgess", "date": "2026-06-17"}]
    out = mod.compute_schedule(CADENCE, existing, [_approved("dup", "perspective", "adam-burgess")])
    assert out[0]["action"] == "skip"
    assert "already" in out[0]["reason"]
    assert out[0]["date"] is None


def test_unknown_author_kind_is_skipped():
    out = mod.compute_schedule(CADENCE, [], [_approved("z", "spoke", "nobody")])
    assert out[0]["action"] == "skip"
    assert "no cadence rule" in out[0]["reason"]


def test_no_double_booking_within_one_run():
    approved = [_approved(f"s{i}", "spoke", "red-bridge-cyber-team") for i in range(6)]
    out = mod.compute_schedule(CADENCE, [], approved)
    dates = [r["date"] for r in out if r["action"] == "schedule"]
    assert len(dates) == len(set(dates)), "no two articles share a slot in one run"
