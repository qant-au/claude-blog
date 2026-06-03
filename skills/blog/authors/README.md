# Author Bundles

Author bundles supply the voice, identity, and bio block that `blog-write` /
`blog-rewrite` inject when invoked with `--author <slug>`.

## Layout

Each author is a directory under `skills/blog/authors/<slug>/` containing
exactly three files:

| File | Purpose |
|------|---------|
| `bio.md` | Multi-paragraph author bio. Rendered into the article's author bio block (foot of post) and into the `author.bio` field of the draft submission payload. |
| `style.md` | Full writing-style guide. Loaded into the drafting prompt as a fenced untrusted-data block (same security contract as `BRAND.md` / `VOICE.md`). Takes precedence over `VOICE.md` when both are present. |
| `byline.md` | One-liner byline string. Used in cards, social previews, and the `author.byline` payload field. |

The author's display name is derived from the `bio.md` first heading
(`# Adam Burgess — Author Bio` → `Adam Burgess`).

## Adding a new author

1. Create `skills/blog/authors/<slug>/`.
2. Write the three files. `style.md` is the largest — model it on
   `skills/blog/authors/adam/style.md`.
3. Optionally add a thin alias skill (e.g. `skills/blog-write-<slug>/SKILL.md`)
   that delegates to `blog-write` with `--author <slug>` preset.

## Currently shipped

| Slug | Name | Notes |
|------|------|-------|
| `adam` | Adam Burgess | Migrated from `qant/brands/adamburgess/WRITING_STYLE.md` (April 2026, v1.0). Covers men's health, decision making, ICT, critical thinking, income after 50. |

## Security note

`style.md` is loaded via `scripts/load_untrusted_root.py` (or an equivalent
fence wrapper) — the same indirect-prompt-injection contract that applies to
`BRAND.md` / `VOICE.md`. Author bundles checked into this repo are trusted by
the maintainer, but the loader still nonces and sanitizes them so the contract
is uniform across all root-style inputs.
