---
name: blog-write-adam
description: >
  Thin alias for `/blog write` with `--author adam-burgess` injected.
  Routes to the blog-write sub-skill with Adam Burgess's author record
  loaded via the QANT brand-blog API. Use when the user says "write as Adam",
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

* Phase 0.6 (author resolution) reads the `adam-burgess` author doc
  via the brand-blog API (`GET /brand/blog/authors/adam-burgess` with
  the brand's key) — the on-disk `brands/<slug>/authors/<slug>/`
  bundles were retired in Phase F-post. If the author doc doesn't
  exist under the brand the user picked, the skill stops and asks the
  operator to create it in Axiom (Instances → Brands → Authors) first.
* Phase 5a (frontmatter) sets `author:` from the author doc's
  `name` field and `authorByline:` from its `byline` field.
* Phase 7 renders the bio block from the author doc's `bio` field into
  the local article foot. Phase 7.5 submits the draft via
  `POST /brand/blog/articles` (status `draft`) with only `author_slug`
  in the payload — name is joined server-side, and bio + byline +
  voice fields live once on the per-author doc.

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
`.env.stg` → `.env.dev`), Adam's author record read via the brand-blog
API (`GET /brand/blog/authors/adam-burgess` with redbridgecyber's
`brk_` key), article drafted in Adam's voice (using the author doc's
`writing_style` + structured-voice fields), FLOW review run, draft
submitted to redbridgecyber's instance via `submit_draft.py`
(`POST /brand/blog/articles`, brand-key auth — no service-account
keys), `draft_id` + `draft_path` reported back.
