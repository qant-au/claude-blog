---
name: blog-write-adam
description: >
  Thin alias for `/blog write` with `--author adam` preset. Routes to the
  blog-write sub-skill with Adam Burgess's author bundle loaded
  (skills/blog/authors/adam/{bio,style,byline}.md). Use when the user says
  "write as Adam", "/blog-write-adam <topic>", or any equivalent shortcut
  for Adam-authored content.
user-invokable: true
argument-hint: "<topic> [--brand <slug>] [--staging|--development] [--no-submit]"
license: MIT
---

# /blog-write-adam — Adam-authored article shortcut

This skill is a thin alias. It delegates straight to `blog-write` with
`--author adam` injected.

## Behavior

When invoked:

1. Forward all user-supplied arguments to `blog-write` verbatim, EXCEPT:
   - Inject `--author <slug>` if no `--author` flag was passed. The slug
     defaults to `adam-burgess` when a `--brand` flag is also present
     (brand-local convention introduced by QANT blog Phase E E1) and
     falls back to `adam` (skill-local legacy slug) when no brand is set.
   - Refuse with a clear error if `--author <other-slug>` was passed —
     this alias is specifically for Adam-authored content; the user
     should use `/blog write` directly to pick a different author.
2. Execute `blog-write`'s full workflow (Phases 0 → 7.5).

## Effect

* Phase 0.6 (author bundle load) tries `<brand_dir>/authors/<slug>/`
  first (Phase E E1 brand-local layout), then falls back to
  `skills/blog/authors/<slug>/`. `style.md` is loaded as a fenced
  untrusted-data block and treats as the voice authority for the
  drafting prompt.
* Phase 5a (frontmatter) sets `author:` from `byline.md` frontmatter
  `name:` field (canonical) and `authorByline:` from the `byline:`
  field.
* Phase 7 / 7.5 renders the bio block from `bio.md` and includes the
  author object in the draft submission payload, which is written to the
  shared `qant-blog-drafts` Firestore project.

## Pass-through arguments

All other `blog-write` flags work normally:

| Flag | Effect |
|------|--------|
| `<topic>` | Required. The article topic. |
| `--brand <slug>` | Resolves brand context, injects identity, enables submission. |
| `--staging` | Reads `.env.stg`, defaults submission to YES. |
| `--development` | Reads `.env.dev`, defaults submission to NO. |
| `--no-submit` | Skips Phase 7.5 entirely. |

## Why this alias exists

Adam is the only standing author in this repo today, and most posts will
be written in his voice across multiple brand sites (adamburgess.me,
PrimeProtocols.com, ABC Training, Red Bridge Cyber guest content). Typing
`/blog-write-adam` is shorter than `/blog write --author adam` and easier
to remember from inside any brand directory.

If a future author bundle ships (see `skills/blog/authors/README.md`), a
parallel `blog-write-<slug>` alias can be added with the same shape.

## Example

```
/blog-write-adam "Beginner cyber hygiene checklist for SMBs" \\
    --brand redbridgecyber --staging
```

Expands to:

```
/blog write "Beginner cyber hygiene checklist for SMBs" \\
    --author adam-burgess --brand redbridgecyber --staging
```

End-to-end: brand context loaded from
`/Users/adam/Projects/qant/brands/redbridgecyber/.env.stg`, brand-local
`adam-burgess` author bundle loaded (from
`brands/redbridgecyber/authors/adam-burgess/`), article drafted in Adam's
voice, FLOW review run, payload written to the shared `qant-blog-drafts`
Firestore at `brands/redbridgecyber/drafts/{auto_id}` via
`submit_draft_firestore.py` (env-based SA auth — no per-brand bearer
key), Firestore doc path reported back.
