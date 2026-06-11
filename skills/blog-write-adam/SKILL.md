---
name: blog-write-adam
description: >
  Thin alias for `/blog write` with `--author adam-burgess` injected.
  Routes to the blog-write sub-skill with Adam Burgess's author record
  loaded from qant-blog-drafts. Use when the user says "write as Adam",
  "/blog-write-adam <topic>", or any equivalent shortcut for
  Adam-authored content.
user-invokable: true
argument-hint: "<topic> [--brand <slug>] [--no-submit]"
license: MIT
---

# /blog-write-adam — Adam-authored article shortcut

This skill is a thin alias. It delegates straight to `blog-write` with
`--author adam-burgess` injected.

## Behavior

When invoked:

1. Forward all user-supplied arguments to `blog-write` verbatim, EXCEPT:
   - Inject `--author adam-burgess` if no `--author` flag was passed.
   - Refuse with a clear error if `--author <other-slug>` was passed —
     this alias is specifically for Adam-authored content; the user
     should use `/blog write` directly to pick a different author.
2. Execute `blog-write`'s full workflow (Phases 0 → 7.5).

## Effect

* Phase 0.6 (author resolution) reads
  `qant-blog-drafts.brands/{brand_slug}/authors/adam-burgess` —
  the on-disk `brands/<slug>/authors/<slug>/` bundles were retired in
  Phase F-post. If the author doc doesn't exist under the brand the
  user picked, the skill stops and asks the operator to create it in
  Axiom (Instance Config → Brands → Authors) first.
* Phase 5a (frontmatter) sets `author:` from the Firestore doc's
  `name` field and `authorByline:` from its `byline` field.
* Phase 7 renders the bio block from the Firestore `bio` field into
  the local article foot. Phase 7.5 writes the draft to
  `qant-blog-drafts.brands/{brand_slug}/drafts/{auto_id}` with
  `author: {slug, name}` only in the per-draft doc — bio + byline +
  voice fields live once on `brands/{brand_slug}/authors/adam-burgess`.

## Pass-through arguments

All other `blog-write` flags work normally:

| Flag | Effect |
|------|--------|
| `<topic>` | Required. The article topic. |
| `--brand <slug>` | Resolves brand context, injects identity, enables submission. When omitted, Phase 0.5 of `blog-write` prompts. |
| `--no-submit` | Skips Phase 7.5 entirely. |

## Why this alias exists

Adam is the standing author across multiple brand sites
(adamburgess.me, Red Bridge Cyber, PrimeProtocols.com, ABC Training).
Typing `/blog-write-adam` is shorter than `/blog write --author
adam-burgess` and easier to remember from inside any brand directory.

## Example

```
/blog-write-adam "Beginner cyber hygiene checklist for SMBs" \\
    --brand redbridgecyber
```

Expands to:

```
/blog write "Beginner cyber hygiene checklist for SMBs" \\
    --author adam-burgess --brand redbridgecyber
```

End-to-end: brand context loaded via the env-precedence pick (`.env` →
`.env.stg` → `.env.dev`), Adam's author record read from
`qant-blog-drafts.brands/redbridgecyber/authors/adam-burgess`,
article drafted in Adam's voice (using the Firestore doc's
`writing_style` + structured-voice fields), FLOW review run, draft
written to `qant-blog-drafts.brands/redbridgecyber/drafts/{auto_id}`
via `submit_draft_firestore.py` (env-based SA auth — no per-brand
bearer key), Firestore paths reported back.
