# Author Bundles — RETIRED

> **Canonical reference** for the current author architecture:
> `/Users/adam/Projects/qant/docs/superpowers/specs/2026-06-09-blog-author-system-final.md`.
> See also the operator guide
> (`qant-common/docs/user/blog/manager.md`) and ops runbook
> (`qant-common/docs/system/ops/blog.md`).

The `skills/blog/authors/<slug>/` disk-bundle layout was retired in
Phase F-post (June 2026). Authors are now managed in **Axiom**
(Instances → (instance) → Brands → (brand) → Authors), with the data
stored in the brand's instance Firestore at
`instances/{id}/brands/{slug}/authors` and reached only via the QANT
brand-blog API (`GET /brand/blog/authors[/{slug}]`, authenticated with
the brand's `brk_` key).

Every author carries the full Phase F shape:

| Field | Purpose |
|-------|---------|
| `name` | Display name. |
| `byline` | One-line role descriptor surfaced in cards + social previews. |
| `bio` | Multi-paragraph markdown bio. Rendered into the article foot. |
| `target_audience` | Free-text "who this author writes for". |
| `locale` | `en-AU` / `en-US` / `en-GB` / `en-NZ` / `en` — drives spelling. |
| `pronoun_stance` | `first_person_singular` / `_plural` / `third_person_singular` / `_plural`. |
| `register` | `technical` / `professional` / `conversational` / `sharp`. |
| `banned_phrases` | Strings the writer agent must never emit. |
| `signature_moves` | Phrases / patterns the author favours (soft bias). |
| `writing_style` | Markdown overflow / nuance not captured by the structured fields above. |

## How `blog-write` / `blog-rewrite` use it

`scripts/load_brand_context.py --list-authors --brand <slug>` lists the
available authors for a brand (via the API). `scripts/submit_draft.py
--author <slug>` sends the slug; the server joins the canonical name +
byline from the author doc at submission time.

The drafting prompt is assembled from the API-served fields directly —
no fenced untrusted-data wrapper from disk anymore. The structured
fields are injected as a small directive block; `writing_style` is
appended as the freeform overflow.

## Adding a new author

Open Axiom → Instances → (instance) → Brands → (brand) → Authors →
"+ New Author" → fill in the form. Save. The author shows up in
`--list-authors` immediately and is selectable by `--author <slug>` on
the next `/blog write` invocation.

## What happened to the `adam/` directory?

It was deleted in Phase F-post once the data was confirmed present
under the `adam-burgess` author slug for every brand Adam
contributes to.
