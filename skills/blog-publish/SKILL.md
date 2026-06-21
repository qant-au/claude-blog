---
name: blog-publish
description: >
  Publish approved blog drafts to a QANT brand website. Drains the brand's
  `approved` queue (status managed in Axiom / stored in the instance
  Firestore), renders each article as a real page on the brand site, dates it
  per the author's cadence, mirrors person-authored pieces into the
  adamburgess aggregator, verifies the commit + layout with Playwright, and
  then deletes the article from the DB — the website is the point-of-truth, the
  DB is draft/review storage only. Use when the user says "blog publish",
  "/blog publish", "publish approved articles", "ship the approved blog
  drafts", or "push approved posts live".
user-invokable: true
argument-hint: "[--brand <slug>] [--dry-run] [--all-brands]"
license: MIT
---

# Blog Publisher: Approved drafts → live brand site

`/blog publish` is **Phase 3** of the blog lifecycle, after draft submission
(`/blog write`, Phase 1) and operator approval in Axiom (Phase 2). It owns the
transition from `status: 'approved'` in the DB to a real, dated page on the
brand website — and the subsequent deletion of the DB row.

**Canonical QANT references:**
- Architecture: `/Users/adam/Projects/qant/docs/superpowers/specs/2026-06-09-blog-author-system-final.md`
- Operator guide: `/Users/adam/Projects/qant/qant-common/docs/user/blog/manager.md`
- Ops runbook: `/Users/adam/Projects/qant/qant-common/docs/system/ops/blog.md`

## Core invariants (do not weaken)

1. **Confirm before destruct.** The DB `DELETE` for an article runs **only
   after** its site commit is confirmed (`git log` shows the commit) **and** a
   Playwright layout check passes. A failed commit or failed layout check
   leaves the DB row intact and the article is reported as failed — never
   deleted.
2. **The website is the point-of-truth.** Once published, the article exists
   only on the site (registry entry + markdown + image, committed to git). The
   DB row is removed so it can't be re-published.
3. **Idempotent.** Re-running publish skips any approved article whose slug is
   already in the site registry (it was already published; a previous run may
   have committed but not yet deleted — just delete it).
4. **No SEO-strategy edits.** Cadence comes from the per-brand
   `docs/blog/publish-cadence.json`, never from the strategy prose docs.
5. **ISO dates only.** Every `date` written to a registry is `YYYY-MM-DD`
   (the brand prebuild + IndexNow tooling enforce this shape).
6. **Cross-links resolve and are date-compatible.** Every internal `/improve`
   link must use the right route for the target's kind (perspective →
   `/improve/perspective/<slug>`, article → `/improve/<slug>`, microanswer →
   `/improve/m/<slug>`) and point at content that goes live **no later than**
   the linking piece — a link to a future-dated article 404s while the linker
   is already live. The brand validators enforce both (Phase 3.5); never weaken
   them. External (off-brand) links are opened in a new tab by the brand's
   article renderer — author plain `[text](url)`, do not hand-add `target`.

## Scripts this skill uses

All under `scripts/` in this plugin:

| Script | Purpose |
|--------|---------|
| `list_approved_articles.py --brand <slug>` | Drain the `approved` queue (`GET /brand/blog/approved`). |
| `compute_publish_dates.py --brand-slug <slug> --articles '<json>'` | Assign each article its publish date per cadence + the site registry. |
| `qant_api.py` (`request()` inline) | Fetch full article body + hero image; called directly. |
| `delete_inbox_draft.py --brand-slug <slug> --draft-id <id> --reason "..."` | The single destructive call — delete after both gates pass. |

The site-write step (Phase 3) is **brand-specific** because brands store
content differently. Two systems are wired:

- **redbridgecyber** — a TS registry (`lib/content/articles.ts`) holds the
  metadata + a separate markdown body file. See *Phase 3 — redbridgecyber*.
- **elliejames** — frontmatter markdown only: each post is one self-contained
  `content/blog/<slug>.md` (frontmatter + body), read at build by
  `lib/blog/load.ts`. No TS registry, no adamburgess mirror. See *Phase 3 —
  elliejames*.

The scheduler (`compute_publish_dates.py`) already abstracts the occupied-date
source over both systems (registry vs. markdown corpus), so Phases 0–2 are
brand-agnostic; only the Phase 3 write differs. New brands add their own
Phase 3 subsection.

---

## Phase 0 — Dispatch

Parse arguments:
- `--brand <slug>` — publish one brand. If omitted and exactly one brand has
  approved articles, use it; otherwise list the brands with approved articles
  and ask which.
- `--all-brands` — iterate every brand under `qant/brands/` with a key.
- `--dry-run` — run Phases 0–2 and print the plan; **skip** all file writes,
  commits, Playwright, and deletes.

List the queue:

```bash
python3 scripts/list_approved_articles.py --brand <slug>
```

If empty → print `No approved articles to publish for <slug>.` and exit 0.
Otherwise announce the count and continue. Sort the rows oldest-first by
`created_at` (so the launch batch fills in submission order).

## Phase 1 — Load cadence + registry

Resolve the brand directory (the env/brand resolver in `qant_api.py` uses
`/Users/adam/Projects/qant/brands/<slug>/`). Read:
- `brands/<slug>/docs/blog/publish-cadence.json` — the cadence config.
- The existing occupied dates (for scheduling + idempotency). The scheduler
  reads these itself: `lib/content/articles.ts` for registry brands
  (redbridgecyber), or the `content/blog/**.md` frontmatter for markdown
  brands (elliejames). You do not pass them in — `compute_publish_dates.py`
  picks the right source from the brand directory.

## Phase 2 — Schedule

```bash
python3 scripts/compute_publish_dates.py \
    --brand-slug <slug> \
    --articles '<the JSON array from Phase 0>'
```

Each result row carries `date` + `action`:
- `action: "schedule"` → a date was assigned.
- `action: "skip"` → slug already in the registry (already published — in
  Phase 6 just delete its DB row) **or** no cadence rule for `(author, kind)`
  (report it; the operator must add a rule or fix the author/kind).

**Dry-run stops here** — print a table of `slug · kind · author · date ·
action` and exit.

## Phase 3 — Write the article onto the brand site (redbridgecyber)

For each `action: "schedule"` row, in date order:

**3a. Fetch the full article + hero image** (brand-key API, via `qant_api.request`):
- `GET /brand/blog/articles/{draft_id}` → `body_markdown`, `title`, `category`,
  `og`, `author`, `metadata`.
- `GET /brand/blog/articles/{draft_id}/image` (`none_on_404=True`) → base64
  hero (`mime`, `data`).

**3b. Write the markdown body** to
`brands/redbridgecyber/content/articles/<slug>.md` (create
`content/articles/` if missing). Strip any leading YAML frontmatter — the file
is pure markdown body (the registry holds the metadata).

**3c. Write the hero image** (only if one was returned): decode the base64 to
`brands/redbridgecyber/public/blog-assets/<slug>.<ext>` (`.webp`/`.png` from
the mime). No hero is valid — the page renders without one.

**3d. Append the registry entry** to `ALL_ARTICLES` in
`brands/redbridgecyber/lib/content/articles.ts`, matching the existing object
literal shape. Field mapping:

| Article field | Source |
|---------------|--------|
| `slug` | DB `slug` |
| `kind` | DB `kind` (`perspective` / `spoke` / `pillar`) |
| `author` | DB `author.slug` (omit when it's `red-bridge-cyber-team`, the default) |
| `category` | **perspective → `'security'`** (cross-cohort lens); otherwise DB `category` (one of email/speed/domain/visibility/security) |
| `pillarId` | **perspective → omit**; spoke/pillar → the `pillarId` of the category's pillar in the registry (warn + use the pre-registered `<category>-N` id if none ships yet) |
| `title` | DB `title` |
| `excerpt` | DB `og.description` (else the article's answer-first opening sentence), ≤ ~200 chars |
| `citabilityBlock` | the article's answer-first opening — the Key-Takeaways list (as `{ intro, bullets, outro }`) or the first substantive paragraph (plain string). This is the primary AI-citation surface; lift it from `body_markdown`, don't fabricate |
| `date` | the scheduler's assigned `date` |
| `readTime` | `round(word_count / 200)` |
| `num` | `String(max(existing num)+1).padStart(2,'0')` |

**3e. Perspective only — wire `RESEARCH_COMMENTARY`.** If this is a
`perspective` piece **and** `RESEARCH_COMMENTARY` in
`brands/redbridgecyber/lib/content/research.ts` is currently `null`, set it to
`{ slug: '<slug>', title: '<title>' }`. If it's already set, leave it (it's a
curator choice — the `/research` card links the first one). The consumer
(`app/research/page.tsx`) already links `/improve/perspective/<slug>`.

**3f. Mirror person-authored pieces to adamburgess (full-text republish).**
Only when `author.slug !== 'red-bridge-cyber-team'` (Adam's pieces — the
syndication-eligibility key). adamburgess.me/blog republishes the **full text**
with canonical pointing back to the source (noindex,follow); its loader
(`brands/adamburgess/lib/blog/load.ts`) reads frontmatter markdown under
`content/blog/**`. Write a markdown file — **not** a registry entry:

Path: `brands/adamburgess/content/blog/redbridgecyber-perspectives/<slug>.md`

```md
---
title: "<title>"
slug: <slug>
excerpt: "<excerpt, ≤240 chars>"
date: <assigned date>
status: published
category: cybersecurity
categoryName: "Cybersecurity"
group: "Red Bridge Cyber - Perspectives"
author: "Adam Burgess"
readTime: <readTime>
heroImage: "<"/blog/<slug>/hero.<ext>" if a hero was copied, else "">"
heroAlt: "<alt text, or "">"
source:
  name: "Red Bridge Cyber"
  slug: redbridgecyber
  canonicalUrl: "https://redbridgecyber.com.au/improve/perspective/<slug>"
---

<full body>
```

Body assembly:
- **Opening** = the `citabilityBlock` rendered as markdown (plain string → a
  paragraph; `{intro,bullets,outro}` → intro paragraph, `- ` bullets, outro),
  then a blank line, then `body_markdown`. The RBC body starts *after* the
  citabilityBlock, so prepending it reconstructs the full article.
- **Absolutize internal links**: `](/x)` → `](https://redbridgecyber.com.au/x)`
  and `href="/x"` → the absolute RBC URL (skip already-local `/blog/` paths).
- **Copy in-body images**: any `/blog-assets/...` reference → copy into
  `brands/adamburgess/public/blog/<slug>/<filename>` and rewrite the src to
  `/blog/<slug>/<filename>`.
- **Strip GEO annotations**: remove `<!-- [UNIQUE INSIGHT] -->`,
  `<!-- [PERSONAL EXPERIENCE] -->`, `<!-- [ORIGINAL DATA] -->`, etc.
- **Hero**: if a hero was written to the brand site
  (`public/blog-assets/<slug>.<ext>`), copy it to
  `brands/adamburgess/public/blog/<slug>/hero.<ext>` and set `heroImage`.

This is a repo-only write (the adamburgess loader renders it; no Playwright
there). `brands/adamburgess/scripts/import-redbridgecyber-perspectives.mjs`
performs exactly this transform for a backfill and is the reference
implementation. (For a non-perspective Adam piece, point `canonicalUrl` at
`/improve/<slug>` and group it under that source instead.)

## Phase 3 — Write the article onto the brand site (elliejames)

elliejames has **no TS registry and no adamburgess mirror** — each post is one
self-contained frontmatter markdown file that `lib/blog/load.ts` reads at
build. Per `action: "schedule"` row, in date order:

**3a. Fetch the full article + hero image** — identical to redbridgecyber 3a
(`GET /brand/blog/articles/{draft_id}` + `…/image`, via `qant_api.request`).

**3b. Write one complete markdown file** to
`brands/elliejames/content/blog/<slug>.md`. Unlike redbridgecyber (pure body +
separate registry), the **frontmatter lives in this file** — the loader parses
it. Shape (match an existing post, e.g. `content/blog/what-do-you-actually-want.md`):

```md
---
title: <DB title>
slug: <slug>
excerpt: >-
  <DB og.description, else the answer-first opening sentence; ≤ ~240 chars>
pillar: <one of: sleep | stillness | presence | intention | ritual | inner-life>
date: '<scheduler-assigned YYYY-MM-DD>'
status: published
author: Ellie James
readTime: <round(word_count / 200), min 1>
metaDescription: >-
  <DB og.description or excerpt>
heroImage: /blog/<slug>/cover.png      # omit if no hero was returned
heroAlt: <DB hero alt, if any>
---

<body_markdown>
```

- `pillar` **must** be one of the six pillar ids (`lib/blog/categories.ts`).
  Map the DB `category` to a pillar id; if the draft's category is already a
  pillar id use it directly, else pick the closest pillar (the loader's
  `pillarFromCategoryName` is the fallback the site uses).
- `date` is the scheduler's assigned date, single-quoted (YAML would otherwise
  coerce it to a timestamp). ISO `YYYY-MM-DD` only.
- `author` is the **display name** `Ellie James` (the loader renders this as
  the byline), not the `ellie-james` slug.

**3c. Write the hero image** (only if one was returned): decode the base64 to
`brands/elliejames/public/blog/<slug>/cover.png` (`.png`/`.webp` from the
mime) and set `heroImage: /blog/<slug>/cover.png`. No hero is valid — omit the
`heroImage`/`heroAlt` lines and the page renders without one.

**3d. No registry, no mirror.** The markdown file *is* the publication record;
there is nothing else to edit.

**3.5 Validate (before commit).** elliejames has no RBC-style content
validators; the build is the gate. From the brand dir:

```bash
cd /Users/adam/Projects/qant/brands/elliejames
npm run build      # prebuild (build-lastmod) + next build — fails on a bad date / unparseable frontmatter
```

If the build fails, **STOP** for that article: do not commit, keep the DB row,
report it with the build output.

**4. Commit + confirm.** One commit per article:

```bash
cd /Users/adam/Projects/qant/brands/elliejames
git add content/blog/<slug>.md public/blog/<slug>/
git commit -m "blog: publish <slug> (<pillar>, <date>)"
```

Confirm with `git log --oneline -1` (and exit code). A failed commit → STOP,
keep the DB row, report as failed.

**5. Playwright layout gate.** The container must be running so dev HMR has the
new markdown (`./restart.sh` from the brand dir — `next dev` on port 4321, no
rebuild needed).

```bash
# staging shows future-dated posts, so the URL is reachable pre-go-live
curl -s -o /dev/null -w "%{http_code}" "http://localhost:4321/post/<slug>"   # expect 200
cd /Users/adam/Projects/qant/brands/elliejames && npm run test:e2e
```

A `404` means the container isn't running / hasn't hot-reloaded — prompt the
user to `./restart.sh` and retry; do **not** delete the DB row in that state.
On a failed layout/e2e check, print the output, keep the DB row, report failed.

Then proceed to **Phase 6** (delete from DB) — it is brand-agnostic.

## Phase 3.5 — Content validation gate (before commit) — redbridgecyber

(elliejames does its own validate/commit/gate inline in *Phase 3 —
elliejames* above; the Phases below are the redbridgecyber registry flow.)

The new registry entry + markdown must pass the brand's prebuild content
validators **before anything is committed**. From the brand dir:

```bash
cd /Users/adam/Projects/qant/brands/redbridgecyber
node scripts/build-lastmod.mjs \
  && node scripts/validate-content-schedule.mjs \
  && node scripts/validate-content-links.mjs
```

- `validate-content-schedule.mjs` — pillar↔trail coordination + 2/weekday slots.
- `validate-content-links.mjs` — every internal `/improve` link resolves to the
  right route for the target's kind and is date-compatible. A perspective linked
  at `/improve/<slug>` instead of `/improve/perspective/<slug>`, a dead slug, or
  a link to a not-yet-live (future-dated) article all fail the build.

If any validator exits non-zero, **STOP** for that article: do not commit, keep
the DB row, report it as failed-not-published with the validator output. (Brands
without these scripts yet: run `npm run build` — the same gates run in prebuild.)

## Phase 4 — Commit + confirm — redbridgecyber

Commit the brand-site changes (one commit per article keeps history clean):

```bash
cd /Users/adam/Projects/qant/brands/redbridgecyber
git add lib/content/articles.ts content/articles/<slug>.md \
        public/blog-assets/<slug>.* lib/content/research.ts   # research.ts only if 3e fired
git commit -m "blog: publish <slug> (<kind>, <date>)"
```

If Adam-authored, commit the mirror too:

```bash
cd /Users/adam/Projects/qant/brands/adamburgess
git add content/blog/redbridgecyber-perspectives/<slug>.md public/blog/<slug>/
git commit -m "blog: mirror <slug> from Red Bridge Cyber"
```

**Confirm the commit** with `git log --oneline -1` (and check exit code). If
`git commit` fails (e.g. nothing staged, hook rejects), **STOP** for that
article — do not run Phase 5 or 6. Report it as failed.

## Phase 5 — Playwright layout gate — redbridgecyber

The article is committed but not yet verified. The redbridgecyber container
must be running so dev HMR has the new `articles.ts` (`./restart.sh
--no-tunnel` from the brand dir — `next dev`, no rebuild needed).

1. **Reachability pre-check** — GET the article's own URL and expect `200`:
   ```bash
   # perspective:   http://localhost:4444/improve/perspective/<slug>
   # spoke/pillar:  http://localhost:4444/improve/<slug>
   curl -s -o /dev/null -w "%{http_code}" "http://localhost:4444/improve/perspective/<slug>"
   ```
   A `404` means the container isn't running or hasn't hot-reloaded — prompt
   the user to `./restart.sh --no-tunnel` from the brand dir and retry. Do
   **not** delete the DB row in this state (commit stands, row kept).

2. **Layout assertion:**
   ```bash
   cd /Users/adam/Projects/qant/brands/redbridgecyber
   npm run test:e2e -- tests/e2e/schema.spec.ts
   ```
   - perspective pieces are covered by `perspective page adds Article schema`
     (it reads `PERSPECTIVE_SLUGS[0]` from the registry at runtime);
   - spokes/pillars by `article page adds Article schema`.

   **Never report success without this passing.** On failure, print the
   Playwright output verbatim, keep the DB row, and report the article as
   failed-not-deleted for manual follow-up.

**Dry-run skips Phase 5 entirely.**

## Phase 6 — Delete from the DB (only after Phases 4 + 5 pass)

```bash
python3 scripts/delete_inbox_draft.py \
    --brand-slug redbridgecyber \
    --draft-id <draft_id> \
    --reason "published as <route> on <date>"
```

Idempotent (404-tolerant). This is the only destructive action. For
`action: "skip"` rows that were skipped because the slug was already in the
registry, also delete their DB row here (they're already live).

## Phase 7 — Summary

Print a table:

```
Published (N):
  <slug>  <kind>  <date>  git:confirmed  playwright:pass  db:deleted
Skipped — already live (M):
  <slug>  db:deleted
Failed — NOT deleted, manual action (K):
  <slug>  <reason / playwright output ref>
```

---

## Notes / edge cases

- **`category` for perspectives** is `'security'` (widest lens). If a
  perspective clearly belongs elsewhere, set its `category` explicitly.
- **Container not running** → the Phase 5 pre-check fails safe: commits stand,
  DB rows kept, the run reports what still needs verifying.
- **No cadence rule** for `(author, kind)` → the scheduler returns
  `action: "skip"` with a reason; the article is left untouched (not deleted).
  Add a rule to the brand's `publish-cadence.json` or correct the draft's
  author/kind, then re-run.
- **Multiple perspectives in one run** all schedule correctly (the scheduler
  tracks dates assigned within the run); the launch batch fills the first 3
  onto launch day.
