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
   - Inject `--author adam` if no `--author` flag was passed.
   - Refuse with a clear error if `--author <other-slug>` was passed —
     this alias is specifically for Adam-authored content; the user
     should use `/blog write` directly to pick a different author.
2. Execute `blog-write`'s full workflow (Phases 0 → 7.5).

## Effect

* Phase 0.6 (author bundle load) reads `skills/blog/authors/adam/style.md`
  as a fenced untrusted-data block and treats it as the voice authority
  for the drafting prompt.
* Phase 5a (frontmatter) sets `author: Adam Burgess` and `authorByline`
  from `byline.md`.
* Phase 7 / 7.5 renders the bio block from `bio.md` and includes the
  author object in the draft submission payload.

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
    --author adam --brand redbridgecyber --staging
```

End-to-end: brand context loaded from
`/Users/adam/Projects/qant/brands/redbridgecyber/.env.stg`, Adam author
bundle loaded, article drafted in Adam's voice, FLOW review run, payload
POSTed to `https://api-stg.qant.au/private/blog/drafts` with the brand's
bearer token, draft id reported back.
