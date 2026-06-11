---
name: blog-rewrite
description: >
  Rewrite and optimize existing blog posts for Google rankings (December 2025
  Core Update, E-E-A-T) and AI citations (GEO/AEO). Full rewrite for both
  Google rankings AND AI citations. For AI-citation-only audit (no Google
  work), use blog-geo instead. Replaces fabricated statistics with sourced
  data, applies answer-first formatting, adds Pixabay/Unsplash images,
  generates built-in SVG charts, injects FAQ schema, performs AI content
  detection, adds citation capsules and information gain markers, and
  updates freshness signals. Works with any blog format (MDX, markdown,
  HTML). Use when user says "rewrite blog", "optimize blog", "update blog",
  "improve blog", "fix blog", "refresh blog post", "blog optimization".
user-invokable: true
argument-hint: "[<file-path>]"
license: MIT
---

# Blog Rewriter: Optimize Existing Posts

Rewrites and optimizes existing blog posts for dual ranking: Google search
and AI citation platforms. Preserves the author's voice while applying the
6 pillars of optimization.

**Key references:**
- `references/quality-scoring.md` - 5-category scoring (Content 30, SEO 25, E-E-A-T 15, Technical 15, AI Citation 15)
- `references/eeat-signals.md` - Experience, expertise, authority, trust markers
- `references/internal-linking.md` - Linking strategy and anchor text rules
- `references/visual-media.md` - Image sourcing and chart styling
- `skills/blog/references/synthesis-contract.md` - 6 LAWs for re-citation hygiene during rewrite (v1.8.0; cross-skill ref lives in the orchestrator's references dir)
- `skills/blog/references/research-quality.md` - cross-source clustering for replacement-statistic research (v1.8.0)

## Cross-reference

For 21 evidence-led optimization prompts (AI-detector test, CTR audit, schema, PAA rewording, technical audit, ChatGPT visibility) directly applicable to rewrite work, see `/blog flow optimize`.

## Flags

`blog-rewrite` accepts the orchestrator-forwarded flags described in the
parent `blog/SKILL.md` "Per-brand and per-author flags" section. Same shape
as `blog-write`:

| Flag | Effect on workflow |
|------|--------------------|
| `--brand <slug>` | Phase 0.5 resolves brand context; identity injected into the rewrite prompt; Phase 5.6 submits the rewritten draft to the brand's instance via the QANT brand-blog API (brand-key auth). |
| `--author <slug>` | Phase 0.6 fetches the FULL author doc via `python3 scripts/load_brand_context.py --get-author <slug> --brand <brand_slug>` (brand-blog API `GET /brand/blog/authors/{slug}`, managed in Axiom: Instances → Brands → Authors); `writing_style` + structured-voice fields shape the rewrite prompt; `bio` is rendered into the article foot; `byline` populates frontmatter byline. **Never read `author-profile-*.json` or any other on-disk author file**: the API-served doc is the live record. |
| `--from-queue` | **Queue mode** (v1.9.2). Skip the positional `<file-path>` argument; instead pull every article flagged for rewrite (`review_state == "needs_rewrite"`, read via `GET /brand/blog/rewrites` with the brand's key) and rewrite each one in sequence. When combined with `--brand <slug>`, the drain is scoped to that one brand. With `--all-brands` (or no `--brand`), the drain enumerates every brand dir under `/Users/adam/Projects/qant/brands/` that has a brand key in its env file and merges the queues. See *Queue mode (Phase 0.3)* below. |
| `--all-brands` | Multi-brand queue mode (v1.10). Implies `--from-queue`. Enumerates the brand dirs with keys and rewrites every flagged draft across every brand in one pass. **This is the default when `/blog rewrite` is invoked with NO arguments** — see *Phase 0: argument dispatch* for the auto-mode contract. |
| `--no-submit` | Skips the submission phase entirely. |

See `skills/blog-write/SKILL.md` Phase 0.5 and 0.6 for the exact resolution
and loading steps — the rewrite path applies the same procedure verbatim.

## Workflow

### Phase 0: Argument dispatch (zero-prompt default)

The operator never wants the skill to ask questions about which draft to
rewrite or which brand to scope to. The dispatch is fully derivable from
the arguments and the rewrite-queue state. Resolve in this order; do
NOT prompt the operator at any branch.

| Argument shape | Mode |
|---|---|
| positional `<file-path>` | File-path mode. Run the existing file-path rewrite path. |
| `--from-queue --brand <slug>` (any order) | Per-brand queue drain. Call `list_pending_rewrites.py --brand <slug>` and iterate Phase 0.3 over that brand only. |
| `--from-queue --all-brands` OR `--from-queue` alone OR **no arguments at all** | Multi-brand queue drain. Call `list_pending_rewrites.py --all-brands`, iterate Phase 0.3 over the merged queue. **This is the default behaviour** for an arg-less `/blog rewrite`. |
| `--brand <slug>` alone, no positional, no `--from-queue` | Equivalent to `--from-queue --brand <slug>` — same per-brand drain. |

After dispatch:

- If the resolved queue is empty, print one line — `"No drafts flagged for
  rewrite across any brand."` (or `"… for brand <slug>."` in per-brand
  mode) — and exit 0. Do NOT prompt for a file path, do NOT offer to
  enumerate options.
- Otherwise announce `"Found N drafts across M brand(s). Draining the
  queue."` and proceed to Phase 0.3 over the resolved row list.

The 4-option "Specific file path / Queue mode / Pick a recent draft /
Chat about this" chooser the user previously saw was the Claude Code
harness reacting to the now-removed `argument-hint: "<file-path>"`
required-arg signal. The new `argument-hint: "[<file-path>]"` (optional)
combined with the dispatch above suppresses it.

### Phase 0.3: Queue mode (when `--from-queue` is set)

The operator-facing trigger here is "I don't want to go hunting for
articles that need a rewrite — read every flagged draft, rewrite it, clear
the flag." Articles get flagged in Axiom (Instances → (instance) →
Brands → (brand) → Articles → Rewrite), which sets the top-level field
`review_state: "needs_rewrite"`. The skill never sets that
field itself — it only consumes the flag and clears it on success.

**1. Fetch the queue.** No env vars needed — each brand is queried via
`GET /brand/blog/rewrites` with its own `NEXT_PUBLIC_BRAND_KEY`
(resolved from the brand dir's env file by `scripts/qant_api.py`).

```bash
# Multi-brand drain (default for arg-less `/blog rewrite`):
python3 scripts/list_pending_rewrites.py --all-brands

# Per-brand drain (legacy / debugging):
python3 scripts/list_pending_rewrites.py --brand <brand-slug>
```

The script returns a JSON array of `{brand_slug, draft_id, draft_path,
slug, title, author_slug, category, review_state, review_targets,
word_count}` per flagged draft — `brand_slug` is populated per row so
the iterator can re-resolve brand context per draft in multi-brand mode.
`review_targets` is `{content: bool, image: bool}` (defaulted to
`{content: true, image: false}` for drafts flagged before targets
existed) and selects the branch in step b.2. If the array is
empty, the queue is empty — announce it and exit cleanly (Phase 0
already prints the "no flagged drafts" line; reaching Phase 0.3 with an
empty queue is a bug).

In multi-brand mode, the Phase 0.5 brand-context resolution
(`load_brand_context.py --brand <slug>`) runs PER ROW with the row's
`brand_slug`. If a brand's `.brand-seo.yml` is missing or its
`brand_key` is absent, log "fail: brand context unavailable for
&lt;slug&gt;" and continue to the next row — never abort the run.

**2. Iterate per draft.** For each entry:

a. Read the full article doc via the API (the list script returns
   identifiers + summary, not the body — fetch the body fresh so the
   rewrite acts on the current content):
   ```python
   import qant_api  # scripts/qant_api.py
   doc = qant_api.request(brand_slug, "GET",
                          f"/brand/blog/articles/{draft_id}")
   ```

b. Use the doc's `author_slug` as the resolved author for Phase 0.6 (no
   prompt; the flagged draft carries its own author), then fetch that
   author's FULL doc:
   ```bash
   python3 scripts/load_brand_context.py --get-author <author_slug> --brand <brand_slug>
   ```
   The JSON on stdout supplies the author-voice block for the rewrite
   prompt (`writing_style` + the structured-voice fields), the
   `banned_phrases` list for FLOW review, and `bio`/`byline` at render.
   **Never read `author-profile-*.json` or any other on-disk author
   file**: exports go stale against the Axiom-managed doc. Use
   `body_markdown` as the input to the rewrite phases (skip Phase 1's
   "detect format" step — the body is markdown).

b.1. **Read `review_instructions` from the doc** (top-level field, sibling
   to `review_state`). Axiom's Rewrite modal lets the
   operator type free-form guidance — for example, "remove the SCIF
   reference, replace with: at a conference with a senior federal
   government representative presenting", or "drop the third subhead;
   it duplicates the second". The field may be empty (unguided rewrite)
   or absent on older flagged drafts. Treat empty / whitespace-only as
   absent.

   When `review_instructions` is non-empty, inject it into the
   writer-agent prompt for Phase 4 (Content Rewrite) as a top-of-prompt
   instruction block, headed with "**Operator's rewrite guidance** —
   apply faithfully:" and followed by the instructions verbatim. Place
   it before the brand identity / author voice blocks so the rewrite
   agent treats it as a hard constraint, not a stylistic preference.
   Surface a one-line "instructions: <first 80 chars>…" entry in the
   per-draft progress log so the operator sees the guidance was loaded.

b.2. **Read `review_targets` from the doc** (top-level field, sibling to
   `review_state`; default `{content: true, image: false}` when absent).
   Log `targets: content=<bool> image=<bool>` in the per-draft progress
   line, then dispatch:

   | `content` | `image` | Branch |
   |---|---|---|
   | true | false | **Content-only** (legacy default) — steps c, d, d.1 (copy image), e, f |
   | true | true  | **Content + image** — steps c, d, d.2 (fresh image), e, f |
   | false | true | **Image-only** — step d.3 ONLY (skip c/d/e: no body rewrite, no resubmit, no delete) |

   (`{content: false, image: false}` never occurs — the API rejects it.)

c. Run Phase 1 (Audit), Phase 2 (Research), Phase 3 (Chart Generation),
   Phase 4 (Content Rewrite — see step b.1 for `review_instructions`
   injection), Phase 5 (Verification), and Phase 5.5 (Delivery Contract)
   exactly as the file-path path does. The brand context loaded in
   Phase 0.5 applies.

d. Phase 5.6 (Draft submission) submits the rewritten draft via
   `submit_draft.py` with the same `--brand-slug` and
   `--author <author_slug>`. The submit path creates a NEW article with
   a fresh auto-id; step e then deletes the original so the operator
   never sees a duplicate in the Axiom Articles list.

d.1. **Content-only branch — carry the hero across.** After Phase 5.6
   returns the new `draft_id`, copy the original's hero image to the
   new doc (no regeneration — no wasted image-gen credits; the
   operator's approval state survives):
   ```bash
   python3 scripts/copy_draft_image.py \\
       --brand-slug    <brand-slug> \\
       --from-draft-id <original-draft-id> \\
       --to-draft-id   <new-draft-id>
   ```
   `no_image_to_copy` on stdout is a clean no-op (legacy draft without
   a hero). On failure, warn and continue — the rewritten draft stands;
   the operator can flag an image-only rewrite later.

d.2. **Content + image branch — regenerate.** Instead of copying,
   produce a fresh hero exactly per blog-write Phase 6.5 step 1
   (banana MCP or ladder → `magick` convert to 1200x630 WebP q80 →
   agent visual review, max 2 retries) and attach it to the NEW draft
   id per blog-write Phase 7.6 (`attach_draft_image.py`, q65/q50
   re-encode ladder on exit 3). `review_instructions` guidance applies
   to the image prompt as well as the body rewrite.

d.3. **Image-only branch — in-place update, nothing else moves.** The
   body is NOT rewritten and NO new doc is submitted; the draft id,
   `submittedAt`, and any operator body edits all survive, and there is
   no submit-failure window. Steps:

   1. Build the image prompt from the doc's `title`, `category`,
      `target_keyword` — and `review_instructions`, which here guides
      the IMAGE ("less abstract, show an actual server room", …).
   2. Generate + convert + visually review per blog-write Phase 6.5
      step 1 (same checklist, same 2-retry cap, stock fallback).
   3. Attach over the existing hero on the SAME draft:
      ```bash
      python3 scripts/attach_draft_image.py \\
          --brand-slug <brand-slug> --draft-id <original-draft-id> \\
          --image <folder>/hero.webp --mime image/webp \\
          --width 1200 --height 630 --source banana
      ```
      The doc's `state` resets to `generated` so the operator re-reviews
      it in the Axiom image modal.
   4. Clear the flag trio so the queue does not re-surface the draft:
      ```bash
      python3 scripts/clear_review_state.py \\
          --brand-slug <brand-slug> --draft-id <original-draft-id> \\
          --reason "image regenerated via /blog rewrite --from-queue"
      ```
   5. Do NOT call `delete_inbox_draft.py`. Log `ok (image-only)` in the
      end-of-run summary.

e. **After Phase 5.6 returns success AND step d.1/d.2 has run** — the
   rewritten article is committed to the brand's instance Firestore
   (`instances/{id}/brands/{slug}/blog_posts/{new_id}`) and its hero
   is in place — DELETE the original flagged article outright via
   `DELETE /brand/blog/articles/{id}` (the server cascades the
   original's images subcollection, so the copy in d.1
   must complete first):
   ```bash
   python3 scripts/delete_inbox_draft.py \\
       --brand-slug <brand-slug> \\
       --draft-id   <original-draft-id> \\
       --reason     "superseded by rewrite via /blog rewrite --from-queue"
   ```
   If the delete fails (rare — network / permissions), log the failure
   and continue. The rewritten draft is still committed; the duplicate
   is cosmetic and can be resolved with a manual delete or the next
   queue pass.

   **Order matters.** Do NOT delete the original before submit
   succeeds. A submit failure with the original already deleted is
   data loss. If Phase 5.6 fails, SKIP step e entirely so the original
   stays in the brand's instance with its `review_state: "needs_rewrite"`
   flag intact and the next queue pass retries.

   The older `clear_review_state.py` helper still exists for the manual
   path (operator wants to lift a flag without actually rewriting). It
   is no longer part of the queue-drain flow.

f. Log a one-line "ok / fail" summary per draft. Continue to the next
   queue entry on failure rather than aborting the run — the operator
   wants the queue to drain and any failures surfaced at the end.

**3. End-of-run summary.** Print the count of drafts attempted, the
count that succeeded through Phase 5.6, and the count that failed (with
the failure reason per draft). Treat the run as successful (exit 0) if
at least one draft processed cleanly; treat it as failure (exit 1) only
if EVERY draft failed.

**4. Testing pattern.** To exercise the queue mode, flag an article in
Axiom: Instances → (instance) → Brands → redbridgecyber → Articles →
Rewrite (optionally adding instructions and targets).

Then run `/blog rewrite --from-queue --brand redbridgecyber` and watch
the round-trip.

**5. Future-state note (obsolete).** ~~When the slug-based upsert
ships in the draft submitter (qnt-046), Phase 0.3 step e
becomes redundant — the upsert overwrites the same doc, the new
payload doesn't carry `review_state`, and the flag is cleared as a
side effect of the overwrite.~~ Superseded: step e now deletes the
original outright after a confirmed submit, so the duplicate-doc
problem the upsert was meant to solve does not arise. qnt-046 is no
longer load-bearing.

### Phase 1: Audit (Read-Only)

1. **Read the blog post** - Detect format (MDX, markdown, HTML)
2. **Run the quality checklist** against `references/quality-scoring.md`:
   - Count fabricated vs sourced statistics
   - Check answer-first formatting (H2 -> stat in first sentence?)
   - Count images and charts (type diversity?)
   - Measure paragraph lengths (any > 150 words?)
   - Check heading hierarchy (H1 -> H2 -> H3, no skips?)
   - Look for FAQ schema
   - Check freshness signals (lastUpdated, dateModified)
   - Assess self-promotion level
   - Evaluate citation tier quality
3. **AI content detection scan**:
   - **Burstiness score** - Measure sentence length variance across the post. Low
     variance (most sentences within 3-5 words of each other) is a strong AI signal.
     Calculate: standard deviation of sentence word counts. Target SD > 6.
   - **Known AI phrase scan** - Check for these high-frequency AI phrases:
     - "in today's digital landscape", "it's important to note", "dive into"
     - "game-changer", "navigate the landscape", "revolutionize", "seamlessly"
     - "cutting-edge", "harness the power of", "leverage" (as verb)
     - "delve", "crucial", "elevate", "foster", "landscape" (overused)
     - "multifaceted", "robust", "tapestry", "embark"
     - Full list in `agents/blog-writer.md`
   - **Vocabulary diversity** - Calculate Type-Token Ratio (TTR): unique words /
     total words. Low TTR (< 0.40) suggests AI-generated repetitive phrasing.
     Target TTR > 0.50 for natural prose.
   - **AI content percentage estimate** - Based on burstiness, phrase density, and
     TTR, estimate what percentage of the content reads as AI-generated (0-100%).
     Report as: "AI content estimate: ~X%"
   - **Second-order structural reflex scan** (v1.8.0) - The first-order checks above
     are vocabulary-level. The second-order pass catches what survives them: structural
     and rhythmic tics LLMs default to after the obvious words are replaced. Run against
     `skills/blog/references/ai-slop-detection.md`. Flag at minimum:
     - Question-cadence H2s above 70% of headings
     - Three or more "Here..." paragraph openers
     - Three-clause sentence rhythm above 50% in any 200-word window
     - More than 2 hedge words ("may," "often," "typically," "generally") in any 20-word span
     - Symmetric-list bloat (list-item word-count SD below 5)
     - More than 2 wrap-up rhetorical questions ("What does this mean for...?")
     - More than half of H2 openers starting with a transition word
     - "The key insight is..." or "What's important here is..." as sentence openers
     - Listicle pre-list intro above 250 words
     - Opening-word repetition: top three first-words above 25% share
     - Paragraph-shape SD below 25 (visual monotony)
     A draft is only "AI-detection clean" when both passes are clean. The two-namespace
     terminology (first-order/second-order for slop-detection vs Tier 1/2/3 for source
     authority) is intentional: see `skills/blog/references/ai-slop-detection.md` for
     why the labels diverged in v1.8.1.
4. **Video embed check**:
   - Count existing YouTube embeds in the post
   - If 0 embeds, flag: "No video embeds. YouTube has the strongest AI visibility correlation (0.737)"
   - If present, check: lazy loading? aria-labels? noscript fallback? VideoObject schema?
5. **Cannibalization check**:
   - Identify the post's primary keyword from title, H1, and first paragraph
   - Search the blog directory for other posts targeting the same keyword:
     - Grep headings and meta descriptions across all blog posts
     - Flag any posts with significant keyword overlap
   - If cannibalization found, report:
     - Which posts compete for the same keyword
     - Recommend: **merge** (combine into one stronger post) or **differentiate**
       (shift one post to a related but distinct keyword)
6. **Calculate current score** across 5 categories:
   - Score across 5 categories (Content Quality 30, SEO Optimization 25, E-E-A-T Signals 15, Technical Elements 15, AI Citation Readiness 15)
   - Total: 0-100
7. **Present audit summary** with specific findings, AI detection results, video status, cannibalization status, and score
8. **Enter plan mode** - Present section-by-section optimization plan

Wait for user approval before proceeding.

### Phase 2: Research

1. **Identify the blog's core topic** from existing content
2. **Find replacement statistics** for any fabricated/unsourced data:
   - Search: `[topic] study 2025 2026 data statistics`
   - Target tier 1-3 sources only
3. **Find images** if post has fewer than 3:
   - Pixabay: `site:pixabay.com [topic keywords]`
   - Unsplash: `site:unsplash.com [topic keywords]`
   - Verify each URL returns HTTP 200
   - If nanobanana-mcp is configured, offer AI generation for missing/insufficient images via `blog-image`
4. **Plan charts** if post has fewer than 2:
   - Identify data suitable for visualization
   - Select diverse chart types

### Phase 3: Chart Generation (Built-In)

When the post needs more visual elements, invoke the `blog-chart` sub-skill:

1. Select chart type using the diversity rule (no repeated types per post)
2. Pass: chart type, title, data values, source, platform format
3. Embed the returned SVG directly within a `<figure>` wrapper
4. Target 2-4 charts per 2,000-word post

See `references/visual-media.md` for chart type selection and styling rules.

### Phase 4: Content Rewrite

Apply changes in this order:

#### 4a. Preserve What Works
- Keep the author's voice and unique perspective
- Preserve original insights and first-hand experience
- Keep existing quality images and charts
- Maintain internal links

#### 4b. Fix Frontmatter
- Add `lastUpdated: "YYYY-MM-DD"` (today's date)
- Keep original `date` unchanged
- Fix meta description: fact-dense, 150-160 chars, includes 1 statistic
- Add `coverImage` + `coverImageAlt` + `ogImage` if missing
  - Search Pixabay/Unsplash/Pexels for wide hero image (1200x630)
  - Or generate custom SVG cover via `blog-chart` (text-on-gradient with key stat)
  - Or generate custom AI image via `blog-image` sub-skill (if nanobanana-mcp configured)
- Verify tags/categories are appropriate

#### 4c. Apply Answer-First Formatting
Every H2 section MUST open with a 40-60 word paragraph containing:
- At least one specific statistic with source attribution
- A direct answer to the heading's implicit question

#### 4d. Replace Fabricated Statistics
- Search for patterns: "X% of...", "X out of Y...", unsourced claims
- Replace with real data from tier 1-3 sources
- Always include inline attribution: `([Source Name](url), year)`

#### 4e. Improve Headings
- Convert statement headings to questions where natural (60-70% target)
- Keep 2-3 statement headings for variety
- Ensure keyword appears in 2-3 headings naturally

#### 4f. Fix Paragraph Length
- Split any paragraph > 150 words
- Target 40-80 words per paragraph
- Ensure each paragraph starts with its most important sentence

#### 4g. Add Visual Elements
- Embed new images after H2 headings, spaced evenly
- Embed charts within relevant sections
- If nanobanana-mcp configured: generate custom images for sections lacking good stock matches (invoke `blog-image` sub-skill via Task)
- Adapt embed format to detected platform (MDX vs markdown vs HTML)

#### 4h. Add Video Embeds
If the post lacks YouTube video embeds:
- Search 2-3 relevant videos using quality criteria from `references/video-embeds.md`
- Embed using platform-appropriate format (srcdoc lazy loading)
- Place: 1 after introduction, 1-2 in mid-article sections
- Include noscript fallback for AI crawlers

#### 4i. Add/Improve FAQ
- If no FAQ exists, add one (3-5 questions)
- If FAQ exists, ensure answers are 40-60 words with statistics
- Add FAQ schema markup appropriate to platform

#### 4j. Reduce Self-Promotion
- Max 1 brand mention (author bio context only)
- Remove "At [Company], we..." patterns
- Convert promotional sections to educational content

#### 4k. Citation Capsule Injection
For each H2 section, generate (or improve existing) a citation capsule:
- 40-60 word self-contained passage per H2
- Contains: one specific claim + one data point + source attribution
- Written in a declarative style so an AI system could extract and quote it directly
- Placed naturally within the section body, not as a separate callout

Example:
```markdown
According to a 2026 Gartner study, 58% of enterprise buyers now consult AI
assistants before contacting a vendor ([Gartner](https://www.gartner.com), 2026).
This shift means B2B content must answer specific questions concisely enough
for AI systems to extract and cite in their responses.
```

Capsules map to the "AI Citation Readiness" category (15 points) in
`references/quality-scoring.md`.

#### 4l. Anti-AI-Detection Patterns
Apply these transformations to reduce AI-detectable writing patterns:
- **Eliminate em dashes** - Replace every em dash (-) with a comma, hyphen (-),
  colon, or period. Split sentences if needed. Em dashes are an AI writing tell.
- **Replace flagged phrases** - Swap every detected AI phrase (from the scan in
  Phase 1 step 3) with a natural alternative. Examples:
  - "it's important to note" -> "worth noting" or "keep in mind"
  - "in today's digital landscape" -> "right now" or "in [specific year]"
  - "leverage" -> "use", "apply", "take advantage of"
  - "delve" -> "look at", "explore", "dig into"
  - "robust" -> "strong", "solid", "reliable"
  - "crucial" -> "key", "essential", "critical" (or restructure the sentence)
- **Vary sentence length deliberately** - After rewriting, scan each paragraph.
  Inject short punchy sentences (5-10 words) between longer ones (18-25 words).
  Target: no more than 3 consecutive sentences within 5 words of each other's length.
- **Inject rhetorical questions** - Add at least one rhetorical question every
  200-300 words to break up declarative monotony.
- **Use contractions naturally** - Replace formal constructions with contractions
  where they sound natural: "it is" -> "it's", "we have" -> "we've",
  "do not" -> "don't", "is not" -> "isn't".
- **Include hedging language** - Sprinkle first-person hedges that signal real
  experience: "in our experience", "we've found that", "from what we've seen",
  "this tends to", "it depends on".

#### 4m. Summary Box (Key Takeaways)
If the post lacks a summary box, add one immediately after the introduction:
```markdown
> **Key Takeaways**
> - [Core finding with statistic and source]
> - [Second key insight or recommendation]
> - [Third actionable takeaway]
> (3-5 bullets, 40-60 words combined. Self-contained - reader gets
> the core value without reading the full article.)
```
Default label is "Key Takeaways", but this is configurable per persona or
brand voice (e.g., "The Bottom Line", "Quick Summary", "What You Need to Know").

If an existing TL;DR box is present, convert it to the bullet-point Key
Takeaways format. Verify it meets the 40-60 word requirement and contains
at least one statistic with source attribution.

#### 4n. Information Gain Marker Injection
Review the post for original value and tag it:
- `[ORIGINAL DATA]` - Any proprietary data, survey results, experiments, or
  case study metrics the author collected first-hand
- `[PERSONAL EXPERIENCE]` - First-hand observations, lessons learned
- `[UNIQUE INSIGHT]` - Novel analysis, contrarian perspectives backed by data

If the post lacks original value markers:
- Ask the author for first-hand data or experience to include
- At minimum, add analytical insights that connect existing research in new ways
- Target: at least 2-3 markers per post

Use HTML comments (`<!-- [ORIGINAL DATA] -->`) or visible callouts depending
on the post's style.

### Phase 5: Verification

After rewriting, verify all quality gates pass:

#### Core Quality Gates
1. Every H2 opens with a statistic + source
2. No paragraph exceeds 150 words
3. Zero fabricated statistics
4. Heading hierarchy is clean
5. FAQ section present with schema
6. Images have descriptive alt text
7. Cover image present in frontmatter (coverImage + ogImage)
8. If MDX: build the project to verify no compilation errors

#### New Element Verification
9. TL;DR box present after introduction (40-60 words, contains statistic)
10. At least 2-3 information gain markers present
11. Citation capsules in major H2 sections (40-60 words, self-contained)
12. Internal linking zones marked or actual links present (5-10 per 2,000 words)
13. No AI-detectable phrases remain from banned list

#### Burstiness and Naturalness Check
14. Sentence length variance: SD > 6 (mix of short and long sentences)
15. Contractions used naturally throughout
16. Rhetorical questions present (1 per 200-300 words)
17. AI content estimate reduced from audit baseline
18. Score improved across all 5 categories vs Phase 1 audit
19. YouTube video embeds present with lazy loading, aria-labels, and noscript fallback

### Phase 6: Summary

```
## Blog Optimization Complete: [Title]

### Score Change
- Before: [X]/100 ([Rating])
  - Content Quality: [X]/30
  - SEO Optimization: [X]/25
  - E-E-A-T Signals: [X]/15
  - Technical Elements: [X]/15
  - AI Citation Readiness: [X]/15
- After: [Y]/100 ([Rating])
  - Content Quality: [Y]/30
  - SEO Optimization: [Y]/25
  - E-E-A-T Signals: [Y]/15
  - Technical Elements: [Y]/15
  - AI Citation Readiness: [Y]/15

### AI Detection
- Before: ~[X]% AI-detected content
- After: ~[Y]% AI-detected content
- Phrases replaced: [N]
- Burstiness improved: [before SD] -> [after SD]

### Cannibalization
- [Status: none found / flagged N posts / resolved]

### Changes Made
- [X] statistics replaced with sourced data
- [X] SVG charts added (types: ...)
- [X] images added from Pixabay/Unsplash
- Answer-first formatting applied to [N] H2 sections
- FAQ schema injected with [N] questions
- TL;DR box: [added/updated]
- Information gain markers: [N] ([types])
- Citation capsules: [N] across H2 sections
- AI phrases replaced: [N]
- lastUpdated set to [date]
- Self-promotion reduced to [N] mentions

### Visual Elements
- Charts: [count] ([types])
- Images: [count]
- YouTube videos: [count] ([titles])

### Ready for
- `/blog analyze <file>` to verify final score
- Publishing / deploying
```

## Phase 5.5: Delivery Contract Enforcement (v1.9.0)

Before presenting the rewritten draft, run the 5-gate delivery contract per `skills/blog/references/blog-delivery-contract.md`. The contract applies to rewrites the same way it applies to new posts: the user is never the first reviewer.

Steps:

1. **Hero check**: if the existing post already has a hero image referenced and still on disk, keep it. If the rewrite changed the topic substantially OR the hero is missing, regenerate via `python scripts/generate_hero.py --topic "<new title>" --tags "<tags>" --out <folder>`.
2. **Re-render**: run `python scripts/blog_render.py --md <slug>.md --out-dir <folder>` to refresh the `.html` and `.pdf` from the updated `.md`.
3. **Reviewer dispatch**: dispatch the `blog-reviewer` agent against the rendered `.html`. Threshold: score 90/100 or higher AND zero P0 issues.
4. **Preflight**: run `python scripts/blog_preflight.py --draft <folder> --strict`. Exit 0 = ship; exit 1 = block.
5. **Iterate on failure**: maximum 3 iterations. After the 3rd failure, STOP and present the diagnostic from `<folder>/preflight-report.json`.

Rewrites have a higher implicit threshold because the existing draft was presumably already published. Re-presenting something worse than the original is not acceptable. If the rewritten score is lower than the original score, that itself is a P0 condition.

## Phase 5.6: Draft submission (only if `--brand` is set)

After Phase 5.5 returns all gates passing AND a brand context was resolved
in Phase 0.5 (see `skills/blog-write/SKILL.md` Phase 0.5 and 0.6 for the
exact resolution and loading steps — `blog-rewrite` reuses them verbatim),
ship the rewritten draft to the brand's instance using the same procedure
as `blog-write` Phase 7.5:

1. **Build the payload** to `<draft-folder>/submission.json` matching the
   shape in `skills/blog-write/SKILL.md` Phase 7.5 step 1. For rewrites,
   include the original post's slug if known so the receiving API can link
   the new draft to the published predecessor (via `metadata.replaces_slug`).

2. **Decide whether to submit**:
   - `--no-submit` → write `submission.json`, skip the write.
   - Otherwise → submit. The contributor invoked the skill; they want
     the draft saved. No env-flag-dependent prompt.

3. **Submit** — POSTs to the QANT brand-blog API
   (`POST /brand/blog/articles`, `X-Brand-Key` header). Auth is the
   brand's own `brk_` key, resolved from the brand dir's env file by
   `scripts/qant_api.py` — no env vars to set:

   ```bash
   python3 scripts/submit_draft.py \\
       --brand-slug "<brand_slug from Phase 0.5>" \\
       --author "<author_slug from Phase 0.6>" \\
       --payload "<draft-folder>/submission.json"
   ```

   The server validates the author and joins the canonical name from
   the author doc; the script fails fast with a "create the author in
   Axiom first" message when the slug is unknown. Report the returned
   `draft_path` to the user.

4. **On failure**: surface the script's stderr verbatim, write the
   payload to `<draft-folder>/submission.json` (so the user can retry
   manually), and report the failure as a non-fatal warning. The
   rewrite is still complete locally.

## Update Mode

When invoked as `/blog update <file>`, focus on freshness:
1. Update statistics to latest available data (2025-2026)
2. Add new developments since last update
3. Refresh images if older than 1 year
4. Update `lastUpdated` in frontmatter
5. Preserve the existing structure - minimize rewrites
6. Target: at least 30% content change to register as "fresh" for AI crawlers
