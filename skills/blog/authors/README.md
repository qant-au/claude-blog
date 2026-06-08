# Author Bundles — RETIRED

The `skills/blog/authors/<slug>/` disk-bundle layout was retired in
Phase F-post (June 2026). Authors are now managed via the **Blog Manager
UI** in the QANT consumer app, with the data stored in the
`qant-blog-drafts` Firestore project at
`brands/{brand_slug}/authors/{slug}`.

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
available authors for a brand. `scripts/submit_draft_firestore.py
--author <slug>` looks up the canonical name + byline at submission
time.

The drafting prompt is assembled from the Firestore fields directly —
no fenced untrusted-data wrapper from disk anymore. The structured
fields are injected as a small directive block; `writing_style` is
appended as the freeform overflow.

## Adding a new author

Open the Blog Manager in the consumer app → pick the brand → "+ New
Author" → fill in the form. Save. The author shows up in
`--list-authors` immediately and is selectable by `--author <slug>` on
the next `/blog write` invocation.

## What happened to the `adam/` directory?

It was deleted in Phase F-post once the data was confirmed present in
qant-blog-drafts under the `adam-burgess` slug for every brand Adam
contributes to.
