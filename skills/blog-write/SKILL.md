---
name: blog-write
description: >
  Write new blog articles from scratch optimized for Google rankings and AI
  citations. Generates full articles with template selection, answer-first
  formatting, Key Takeaways summary box, information gain markers, citation capsules, sourced
  statistics, Pixabay/Unsplash images, built-in SVG chart generation, FAQ schema,
  internal linking zones, and proper heading hierarchy. Supports MDX, markdown,
  and HTML output.
  Use when user says "write blog", "new blog post", "create article",
  "write about", "draft blog", "generate blog post".
user-invokable: true
argument-hint: "<topic>"
license: MIT
---

# Blog Writer: New Article Generation

Writes complete blog articles from a topic, brief, or outline. Every article
follows the 6 pillars of dual optimization (Google rankings + AI citations).

**Key references** (paths relative to repo root; references live in the
main `blog` skill's references directory, not in `blog-write/`):

- `skills/blog/references/synthesis-contract.md`: 6 LAWs for synthesis output (v1.8.0; applies whenever the article embeds research-synthesis prose)
- `skills/blog/references/content-templates.md`: Template selection guide and usage
- `skills/blog/references/quality-scoring.md`: 5-category scoring (Content 30, SEO 25, E-E-A-T 15, Technical 15, AI Citation 15)
- `skills/blog/references/eeat-signals.md`: Experience, expertise, authority, trust markers
- `skills/blog/references/internal-linking.md`: Linking strategy and anchor text rules
- `skills/blog/references/visual-media.md`: Image sourcing and chart styling

## Flags

`blog-write` accepts the orchestrator-forwarded flags described in the
parent `blog/SKILL.md` "Per-brand and per-author flags" section:

| Flag | Effect on workflow |
|------|--------------------|
| `--brand <slug>` (optional) | Phase 0.5 resolves brand context (env + `.brand-seo.yml` `content:` block + author list); brand identity is injected into the drafting prompt; Phase 7.5 submits the draft to the brand's instance via the QANT brand-blog API (`POST /brand/blog/articles`, auth via the brand's own `brk_` key from the brand dir's env file). **If omitted, Phase 0.5 prompts the user with a brand picker.** |
| `--author <slug>` (optional) | Phase 0.6 reads the author via the brand-blog API (`GET /brand/blog/authors/{slug}`, managed in Axiom: Instances → Brands → Authors); Phase 0.6 fetches the full doc with `--get-author`. The author doc carries `name`, `byline`, `bio`, `writing_style`, plus structured-voice fields (`locale`, `pronoun_stance`, `register`, `banned_phrases`, `signature_moves`, `target_audience`). The on-disk `brands/<slug>/authors/<slug>/` bundles were retired in Phase F-post. **If omitted, Phase 0.6 prompts the user with the author list from `--list-authors --brand <slug>`, highlighting `content.default_author`.** |
| `--no-submit` | Skips Phase 7.5 entirely (article ends up local-only). |

Note: there is no `--staging` / `--development` flag. The `/blog` skill is **production-only** — drafts and authors always go to the production AU brand-blog API (`https://api-au.qant.au`, backed by `qant-core-au`). The loader reads `.env.prod`, then `.env` (first existing file wins; staging env files are never read) to pick up `NEXT_PUBLIC_BRAND_DOMAIN` and `NEXT_PUBLIC_BRAND_KEY` (the production `brk_` key). `QANT_BLOG_API_URL` overrides the base for local API development only — resolution lives in `scripts/qant_api.py`.

## Workflow

### Phase 0: Surface Targeting (do this BEFORE research)

Decide which of the FLOW 5 surfaces this post is meant to win. The choice
shapes structure, length, citation density, and call-to-action. The 5 surfaces
in 2026:

1. Owned site (organic Google ranking)
2. SERP including AI Overviews
3. AI assistant citations (ChatGPT, Perplexity, Claude, Gemini, Copilot, You.com)
4. Local pack (out of scope for blog content; use claude-seo for local)
5. Communities and video (Reddit, YouTube, LinkedIn, Quora, niche forums)

Most posts target surfaces 1, 2, and 3 by default. If the same query also
surfaces in a community (Reddit thread, YouTube comment), apply dual-surface
thinking: optimize the post for extraction AND plan a community echo (covered
in `/blog repurpose`).

For a deeper surface-by-surface workflow, see
`skills/blog/references/flow-alignment.md` and `/blog flow find`.

### Phase 0.5: Brand resolution (interactive picker when `--brand` omitted)

If `--brand <slug>` was passed: skip directly to step 2 below.

**1. Brand picker (when `--brand` omitted).**

```bash
python3 scripts/load_brand_context.py --list-brands
```

Returns a JSON array `[{slug, display_name}, ...]` of every brand under
`/Users/adam/Projects/qant/brands/` that has a `.brand-seo.yml`.

- If the list is exactly one brand → auto-pick + announce
  ("Using brand: Red Bridge Cyber (redbridgecyber).").
- Otherwise print a numbered list to stdout, read one line of stdin, and
  resolve the user's input. Accept either the number ("1") or the slug
  ("redbridgecyber") — be lenient on case.
- If the user types something that doesn't match, re-print the list with
  an error line and read again. Max 3 attempts before aborting.

The selected slug becomes `<slug>` for the next step.

**2. Load brand context.**

```bash
python3 scripts/load_brand_context.py --brand <slug>
```

The JSON payload contains:
- `brand_slug`, `brand_dir`, `env_file` — pointers.
- `brand_domain` — canonical brand domain from `NEXT_PUBLIC_BRAND_DOMAIN`
  (or derived from `canonical.marketing` in `.brand-seo.yml` for older
  brands). Use for absolute OG URLs and the article's `canonical:`
  frontmatter.
- `brand_identity` — display_name, canonical, target_keywords, optional
  primary_author, **plus `content:` block** (audience, strategy, plan,
  categories[], url_pattern, default_author).
  (Authors are NOT included in this payload — fetch them separately via
  `python3 scripts/load_brand_context.py --list-authors --brand <slug>`
  in Phase 0.6.)

Inject `brand_identity` (display_name, canonical, content block) into
the drafting prompt as a small structured block. The `content` block is
the load-bearing one — `categories[]` constrains the article category,
`audience` and `strategy` paths point at the strategy doc the writer
agent should consult.

If the brand directory is missing, fail fast and surface the loader's
error.

### Phase 0.6: Author resolution (interactive picker when `--author` omitted)

The on-disk `brands/<slug>/authors/` bundles were retired in Phase F-post.
Authors live in the brand's instance Firestore
(`instances/{id}/brands/{slug}/authors`), reached only via the brand-blog
API and managed in Axiom (Instances → Brands → Authors). Every author has
a full Phase F shape: `name`, `byline`, `bio`, `writing_style`,
`target_audience`, plus structured-voice fields (`locale`,
`pronoun_stance`, `register`, `banned_phrases`, `signature_moves`).

**1. List the authors for this brand.**

```bash
python3 scripts/load_brand_context.py --list-authors --brand <slug>
```

Returns `[{slug, name, byline}, ...]` via `GET /brand/blog/authors`.
Auth is the brand's `NEXT_PUBLIC_BRAND_KEY` read from the brand dir's
env file (the same key the draft-submitter uses) — no env vars to set.

**2. Resolve the author slug.**

- If `--author <slug>` was passed → confirm the slug is in the
  `--list-authors` output. If it isn't, stop and tell the operator:
  "Author `<slug>` doesn't exist for brand `<brand_slug>`. Create it
  in Axiom (Instances → Brands → <brand> → Authors → New Author)
  before re-running."

- If `--author` was omitted → prompt the user. Build the list as:

  ```
  Authors for <display_name>:
    1. red-bridge-cyber-team   (default)
    2. adam-burgess
    Enter number or slug [default: red-bridge-cyber-team]:
  ```

  The default is `brand_context.brand_identity.content.default_author`
  (or, for legacy v1 schemas, `brand_identity.primary_author`). Empty
  stdin = take the default. Accept either the number or the slug.

  If the brand has zero authors, stop with the Axiom instruction
  above.

**3. Load the author doc fields.**

Fetch the full author doc from the API with:

```bash
python3 scripts/load_brand_context.py --get-author <author_slug> --brand <slug>
```

The JSON on stdout is the ONLY author surface for this run. **Never
read `author-profile-*.json`, exported author JSON, or any other
on-disk author file**: exports are point-in-time snapshots that go
stale the moment the profile is edited in Axiom (Instances → Brands →
Authors); the API-served author doc is the live record. The fields:

- `name` → article frontmatter `author:` + per-draft `author.name`.
- `byline` → `authorByline` frontmatter.
- `bio` → rendered into the article foot at render time (NOT in the
  per-draft payload; it stays on the per-author doc).
- `writing_style` → the freeform voice-block addendum. Concatenate
  after the structured-voice block in the writer agent's prompt.
- `locale` → article locale + spelling enforcement (en-AU →
  Australian English, etc.).
- `pronoun_stance` → injected as a hard directive in the writer-agent
  prompt ("Write in [first-person singular | first-person plural |
  third-person singular | third-person plural]").
- `register` → tonal anchor ("[technical | professional |
  conversational | sharp]").
- `banned_phrases` → fail FLOW review (Phase 6) if any phrase appears.
- `signature_moves` → soft bias in the writer-agent prompt.
- `target_audience` → injected as a "you are writing for: ..." line.

When project-root `VOICE.md` is also present, the author's structured
fields + writing_style take precedence on tone, sentence cadence, and
banned-phrase list — VOICE.md is the project default; the author doc
is the named author's voice.

Phase 7.5 only passes `--author <slug>` to `submit_draft.py` — the
server joins the canonical name/byline from the author doc so the
join key + UI label always match the live record.

### Phase 1: Topic Understanding

1. **Clarify the topic** - If the user provides just a topic, ask:
   - Target audience (who is this for?)
   - Primary keyword / search intent
   - Desired word count (default: 2,000-2,500 words)
   - Platform/format (MDX, markdown, HTML - auto-detect if in a project)
2. **If a brief exists** - Load it and skip to Phase 1.5

### Phase 1.5: Template Selection

Select the appropriate content template from the 12 templates in
`skills/blog/templates/` (the main `blog` skill owns the templates directory).

1. **Auto-detect content type** from the topic and search intent:
   | Signal | Template |
   |--------|----------|
   | "How to...", process, steps | `how-to-guide` |
   | "Best X", "Top N", list format | `listicle` |
   | Client result, before/after, metrics | `case-study` |
   | "X vs Y", comparison, alternatives | `comparison` |
   | Broad topic, comprehensive guide | `pillar-page` |
   | "Is X worth it", product evaluation | `product-review` |
   | Opinion, prediction, industry take | `thought-leadership` |
   | Expert quotes, multi-source collection | `roundup` |
   | Code walkthrough, tool demo, technical | `tutorial` |
   | Breaking news, algorithm update, event | `news-analysis` |
   | Survey results, experiment, original data | `data-research` |
   | Q&A, knowledge base, "What is X" | `faq-knowledge` |

2. **Load the matching template**: Read from `skills/blog/templates/<type>.md`
3. **Adapt the outline** - Use the template's section structure, heading patterns,
   and word count guidance to shape Phase 3's outline
4. **Fallback** - If no template clearly fits, use the generic outline structure
   in Phase 3 below. Inform the user which template was selected (or that none matched).

See `skills/blog/references/content-templates.md` for detailed selection criteria and intent mapping.

The selected template also determines the article's **`kind`** (`perspective` /
`pillar` / `spoke`) — stamped into the submission payload in Phase 7.5 and read
by `/blog publish` to route + schedule the article. See the Phase 7.5 map.

### Phase 2: Research

Spawn a `blog-researcher` agent (or do inline research with WebSearch):

1. **Find 8-12 current statistics** (2025-2026 data preferred)
   - Search: `[topic] study 2025 2026 data statistics`
   - Prioritize tier 1-3 sources (see `skills/blog/references/quality-scoring.md`)
   - Record: statistic, source name, URL, date, methodology
2. **Find a cover image** (wide, high-quality, topic-relevant):
   - Search: `site:pixabay.com [topic] wide banner` (preferred)
   - Alternative: `site:unsplash.com [topic] wide`
   - Fallback: `site:pexels.com [topic] wide banner`
   - Target dimensions: 1200x630 (OG-compatible) or 1920x1080
   - Or generate a custom SVG cover via `blog-chart` (text-on-gradient with key stat)
   - Or generate a custom AI image via `blog-image` sub-skill (if nanobanana-mcp configured)
   - See `skills/blog/references/visual-media.md` for cover image sizing details
3. **Find 3-5 inline images** from open-source platforms:
   - **Pixabay** (preferred): Search `site:pixabay.com [topic keywords]`
     - Extract image URL from page
     - Direct URLs: `https://cdn.pixabay.com/photo/YYYY/MM/DD/HH/MM/filename.jpg`
     - Verify with `curl -sI "<url>" | head -1` returns HTTP 200
   - **Unsplash** (alternative): Search `site:unsplash.com [topic keywords]`
     - Build URL: `https://images.unsplash.com/photo-<id>?w=1200&h=630&fit=crop&q=80`
   - **Pexels** (fallback): Search `site:pexels.com [topic keywords]`
4. **Plan 2-4 data visualizations** from researched statistics
   - Select diverse chart types (see `skills/blog/references/visual-media.md`)
   - Map data points to chart formats
5. **AI image generation** (optional, if nanobanana-mcp configured):
   - If stock photo results are insufficient (< 3 good matches) or topic is too niche
   - Generate custom hero image and/or inline illustrations via `blog-image` sub-skill
   - Stock photos remain default - AI generation supplements, never replaces
6. **NotebookLM research** (optional, if user has relevant notebooks):
   - If the user mentions a NotebookLM notebook or the topic aligns with a configured notebook
   - Query via `blog-notebooklm` for source-grounded data from user-uploaded documents
   - Treat NotebookLM responses as Tier 1 sources (user's own primary documents)
   - Falls back silently if not configured or not authenticated
7. **Find relevant YouTube videos** (2-3 per post):
   - Use `blog-google` youtube command or WebSearch `site:youtube.com [topic] [year]`
   - Apply quality criteria from `skills/blog/references/video-embeds.md` (min score 50/100)
   - Select 2-3 best videos. Falls back silently if none found.

### Phase 3: Outline Generation

Create a structured outline before writing. If a template was loaded in Phase 1.5,
adapt this skeleton to match the template's section structure:

```
# [Title as Question - Include Primary Keyword]

## Introduction (100-150 words)
- Hook with surprising statistic
- Problem/opportunity statement
- What the reader will learn

> **Key Takeaways**
> - [Core finding with statistic and source]
> - [Second key insight or recommendation]
> - [Third actionable takeaway]
> (3-5 bullets, 40-60 words combined)

## H2: [Question Format] (300-400 words)
- Answer-first paragraph (40-60 words with stat + source)
- Supporting evidence
- [Image placement]
- Practical advice
- [CITATION CAPSULE placeholder]
- [INTERNAL-LINK: anchor text → target description]

## H2: [Question Format] (300-400 words)
- Answer-first paragraph
- [Chart: type + data description]
- Analysis and implications
- [CITATION CAPSULE placeholder]
- [INTERNAL-LINK: anchor text → target description]

## H2: [Statement for Variety] (300-400 words)
- Answer-first paragraph
- Real-world example or case study
- [Image placement]
- [CITATION CAPSULE placeholder]

## H2: [Question Format] (300-400 words)
- Answer-first paragraph
- [Chart: type + data description]
- Step-by-step guidance
- [CITATION CAPSULE placeholder]
- [INTERNAL-LINK: anchor text → target description]

## H2: [Question Format] (200-300 words)
- Answer-first paragraph
- Forward-looking analysis

## [CTA Section or Inline Placement]
- See `skills/blog/references/cta-placement.md` for placement rules by content type
- Place CTA after value delivery, not at arbitrary positions
- Single focused CTA per post (266% more conversions)
- [CTA: contextual call-to-action matching article topic]

## FAQ Section (3-5 questions, 40-60 words each answer)
- [INTERNAL-LINK: anchor text → detailed content]

## Conclusion (100-150 words)
- Key takeaways (bulleted)
- Call to action
- [INTERNAL-LINK: anchor text → next logical content]
```

Present the outline to the user for approval before writing.

**Visual element pacing**: Insert `[IMAGE]`, `[CHART]`, `[VIDEO]`, or `[CALLOUT]` markers
every 300-500 words. Alternate types (no consecutive same-type). See
`skills/blog/references/content-rules.md` Visual Rhythm section and
`skills/blog/references/cta-placement.md` for CTA positioning.

### Phase 4: Chart Generation (Built-In)

When the researcher identifies chart-worthy data (3+ comparable metrics, trend data,
before/after comparisons):

1. Select chart type using the diversity rule (no repeated types per post)
2. Invoke `blog-chart` sub-skill with: chart type, title, data values, source, platform format
3. Embed the returned SVG directly in the post within a `<figure>` wrapper
4. Target 2-4 charts per 2,000-word post
5. Distribute charts evenly - never cluster them

See `skills/blog/references/visual-media.md` for chart type selection and styling rules.

### Phase 5: Content Writing

Write the full article following these rules:

#### 5a. Frontmatter
```yaml
---
title: "[Question-format title with primary keyword]"
description: "[Fact-dense, 150-160 chars, includes 1 statistic]"
coverImage: "[URL from Pixabay/Unsplash/Pexels or generated SVG path]"
coverImageAlt: "[Descriptive sentence about the cover image]"
ogImage: "[Same as coverImage, or custom OG image URL]"
date: "YYYY-MM-DD"
lastUpdated: "YYYY-MM-DD"
author: "[Author name]"
tags: ["keyword1", "keyword2", "keyword3"]
---
```

If the platform uses a different field name (e.g., `image`, `hero`, `thumbnail`),
adapt to match the project's existing frontmatter convention.

When an author is resolved (Phase 0.6): derive the `author:` value from
the author doc's `name` field (canonical source — fetched via
`GET /brand/blog/authors/{slug}`). Append the
`byline` field as a secondary frontmatter entry (`authorByline`) for
downstream renderers.

The article frontmatter is the only place the FULL author bio appears
in the local-delivery output. The submission payload (Phase 7.5)
carries no author fields at all — the script sends `author_slug` and
the server joins name/byline/bio from the per-author doc.

#### 5b. Summary Box (Key Takeaways)

Immediately after the introduction (before the first H2 body section), add a summary box:

```markdown
> **Key Takeaways**
> - [Core finding with statistic] ([Source], year)
> - [Second key insight or recommendation]
> - [Third actionable takeaway]
```

Requirements:
- 3-5 bullet points, 40-60 words combined
- Must be self-contained - understandable without reading the article
- Include 1 specific statistic with source name
- State the key finding, recommendation, or answer
- Default label: "Key Takeaways". If a persona is active, use the persona's summary_label
- Backward compatible: accept existing TL;DR boxes during rewrites

#### 5c. Answer-First Formatting (Critical)
Every H2 section MUST open with a 40-60 word paragraph containing:
- At least one specific statistic with source attribution
- A direct answer to the heading's implicit question

Pattern:
```markdown
## How Does X Impact Y in 2026?

[Stat from source] ([Source Name](url), year). [Direct answer to the heading
question in 1-2 more sentences, explaining the implication and what this means
for the reader.]
```

**FLOW evidence triple (drafting requirement, not just audit):**

Every public statistic must carry three components AT DRAFTING TIME:

1. **Year anchor in prose.** Write "In 2026," or "As of Q1 2026," BEFORE
   the statistic, in the sentence body. Year buried inside parentheses
   does not count. Example:
   - GOOD: "In 2026, Ahrefs found a 58% lower CTR for position one when
     an AI Overview was present."
   - WEAK: "Position-one CTR dropped 58% (Ahrefs, 2026)."

2. **Inline citation with publisher and title.** Name both the publisher
   and the document title (or report name), not just a brand. Example:
   - GOOD: "Ahrefs, AI Overviews CTR update, December 2025"
   - WEAK: "Ahrefs reported..."

3. **URL plus retrieval date in the source block at the bottom of the post.**
   Provenance discipline lets future readers and AI crawlers verify the
   source still says what was claimed. Format:
   - "[Publisher], [Title] *— retrieved D Month YYYY*, [full URL]"
   - The `— retrieved D Month YYYY` portion must be in markdown italics
     and use the human date form (e.g. `9 June 2026` not `2026-06-09`).
     The em-dash separates the title from the retrieval qualifier.
   - EXTERNAL sources only. First-party / own-research citations (the
     brand's own published datasets, e.g. a Posture Baseline edition)
     carry their edition vintage only ("June 2026") — never a retrieved
     date and never `(n=…)` sample-size notation, in citations, chart
     source lines, or captions.

**FLOW quality bar (drop or replace):**
Public claims must use verified sources OR stay qualitative. If a statistic
cannot be verified, drop it. If it is contradicted by a more recent source,
replace it with the verified alternative. Do not soften vague language to
keep an unsourceable number.

For evidence-led optimization prompts (CTR audit, AI detector test, schema,
PAA rewording, ChatGPT visibility), see `/blog flow optimize`.

#### 5d. Information Gain Markers

Distribute at least 2-3 information gain markers throughout the article. These
signal to search engines and AI systems that the content contains original value
not available elsewhere.

Tag each with a comment or visible marker:

- `[ORIGINAL DATA]` - Proprietary surveys, experiments, A/B test results, case
  study metrics the author collected first-hand
- `[PERSONAL EXPERIENCE]` - First-hand observations, lessons learned from direct
  involvement, "when we tried X, Y happened" narratives
- `[UNIQUE INSIGHT]` - Analysis others haven't made, contrarian perspectives
  backed by data, novel connections between existing research

Placement:
- Weave into the body text naturally
- Use as inline comments: `<!-- [ORIGINAL DATA] -->` before the relevant paragraph
- Or as visible callouts if the format supports it:
  ```markdown
  > **Our finding:** [original observation backed by specific data]
  ```
- Minimum 2 per post, target 3 for comprehensive articles

These markers map directly to the "Originality/unique value markers" criterion
in the Content Quality scoring category (see `skills/blog/references/quality-scoring.md`).

#### 5e. Citation Capsules

For each major H2 section, generate a citation capsule - a 40-60 word self-contained
passage designed so AI systems can extract and quote it directly.

Requirements per capsule:
- 40-60 words, self-contained (makes sense in isolation)
- Contains: one specific claim + one data point + source attribution
- Written in a declarative, quotable style
- Placed within the H2 section body (not as a separate block)

Example:
```markdown
According to a 2026 Gartner study, 58% of enterprise buyers now consult AI
assistants before contacting a vendor ([Gartner](https://www.gartner.com), 2026).
This shift means B2B content must answer specific questions concisely enough
for AI systems to extract and cite in their responses.
```

Capsules map to the "AI Citation Readiness" scoring category (15 points) in
`skills/blog/references/quality-scoring.md`.

#### 5f. Internal Linking Zones

Mark internal linking opportunities throughout the article using placeholder
notation. The user (or a follow-up pass) will resolve these to actual URLs.

Zone placement:
- **Introduction** - Link to related pillar content or topic hub
- **Each H2 section** - Link to supporting articles, deeper dives, related tools
- **FAQ section** - Link answers to detailed content that expands on the answer
- **Conclusion** - Link to the next logical piece of content the reader should consume

Format:
```markdown
[INTERNAL-LINK: anchor text → target description]
```

Example:
```markdown
For a deeper dive into keyword clustering, see our
[INTERNAL-LINK: complete guide to keyword clustering → pillar page on keyword research methodology].
```

Target 5-10 internal link zones per 2,000-word post. Use descriptive anchor text
(never "click here" or "read more"). See `skills/blog/references/internal-linking.md` for
anchor text rules and linking strategy.

#### 5g. Paragraph Rules
- Every paragraph: 40-80 words (never exceed 150)
- Every sentence: max 15-20 words
- Start each paragraph with the most important information
- Target Flesch Reading Ease: 60-70

#### 5h. Heading Rules
- One H1 (title only)
- H2s for main sections (60-70% as questions)
- H3s for subsections only - never skip levels
- Include primary keyword naturally in 2-3 headings

#### 5i. Image Embedding

Standard markdown:
```markdown
![Descriptive alt text - topic keywords naturally](https://cdn.pixabay.com/photo/...)
```

MDX with Next.js Image (if detected):
```mdx
![Descriptive alt text - topic keywords naturally](https://cdn.pixabay.com/photo/...)
```

- Place images after H2 headings, before body text
- Space evenly throughout the post (not clustered)
- Alt text should be a full descriptive sentence

#### 5j. Chart Embedding

Standard markdown/HTML — `blog-chart` returns a complete `<figure>` with the
source already baked inside the SVG; embed it as-is. Do **not** add a
`<figcaption>` source (it would duplicate the in-SVG source line):
```html
<figure>
  <svg viewBox="0 0 560 380" ...>...</svg>
</figure>
```

MDX format:
```mdx
<figure className="chart-container" style={{margin: '2.5rem 0', textAlign: 'center', padding: '1.5rem', borderRadius: '12px'}}>
  <svg viewBox="0 0 560 380" ...>...</svg>
</figure>
```

#### 5k. Video Embedding
Embed YouTube videos using srcdoc lazy-loading pattern from `skills/blog/references/video-embeds.md`.
Include aria-label, noscript fallback for AI crawlers. Place after relevant H2, 500+ words apart.

#### 5l. Citation Format
Inline attribution (always):
```markdown
Organic CTR declined 61% with AI Overviews ([Seer Interactive](https://www.seerinteractive.com/), 2025).
```

#### 5m. FAQ Section
Add 3-5 FAQ items with 40-60 word answers. Each answer must contain a statistic.

For MDX with FAQSchema component:
```mdx
<FAQSchema faqs={[
  { question: "Question?", answer: "40-60 word answer with statistic and source." },
]} />
```

For standard markdown:
```markdown
## Frequently Asked Questions

### Question text here?

Answer with statistic and source attribution (40-60 words).
```

#### 5n. Internal Linking
- 5-10 internal links per 2,000-word post
- Link to relevant existing content naturally
- Use descriptive anchor text (not "click here")

### Phase 6: Quality Check

Before delivering, verify:

#### Structure and Content
1. Every H2 opens with a statistic + source
2. No paragraph exceeds 150 words
3. All statistics have named tier 1-3 sources
4. 2-4 charts with type diversity
5. 3-5 inline images with descriptive alt text
6. Cover image present in frontmatter (coverImage + ogImage)
7. FAQ section present with 3-5 items
8. Heading hierarchy is clean (H1 -> H2 -> H3)
9. Meta description is 150-160 chars with a stat

#### New Element Verification
10. TL;DR box present after introduction (40-60 words, contains statistic + source)
11. At least 2-3 information gain markers (`[ORIGINAL DATA]`, `[PERSONAL EXPERIENCE]`, or `[UNIQUE INSIGHT]`)
12. Citation capsules present in major H2 sections (40-60 words, self-contained, quotable)
13. Internal linking zones marked in introduction, H2 sections, FAQ, and conclusion
14. No AI-detectable phrases from banned list (see `agents/blog-writer.md`)

#### Burstiness and Naturalness Check
15. **Sentence length variance** - Verify a mix of short (8-word) and long (25-word) sentences. Uniform sentence length signals AI authorship.
16. **Banned AI phrase scan** - Check for and remove:
    - "in today's digital landscape", "it's important to note", "dive into"
    - "game-changer", "navigate the landscape", "revolutionize", "seamlessly"
    - "cutting-edge", "harness the power of", "leverage" (as verb)
    - "delve", "crucial", "elevate", "foster", "landscape" (overused)
    - "multifaceted", "robust", "tapestry", "embark"
    - Full list in `agents/blog-writer.md`
17. **Contractions** - Verify natural use of contractions ("it's", "we've", "don't", "isn't"). Formal AI prose avoids contractions; natural writing uses them.
18. **Rhetorical questions** - Verify at least one rhetorical question every 200-300 words to break up declarative patterns.
19. **YouTube videos** - 2-3 embeds with lazy loading, aria-labels, and noscript fallback (see `skills/blog/references/video-embeds.md`)

### Phase 6.5: Delivery Contract Enforcement (v1.9.0)

Before Phase 7, run the 5-gate delivery contract per `skills/blog/references/blog-delivery-contract.md`. The user is never the first reviewer; the gates are.

Steps:

1. **Capability discovery + hero**: run `python scripts/blog_preflight.py --draft <folder> --gate 1` to enumerate available paths. If `nanobanana-mcp` is loaded, generate the hero via the MCP tool. Otherwise run `python scripts/generate_hero.py --topic "<title>" --tags "<tags>" --out <folder>` (uses the Gemini, Unsplash, Pexels, Pixabay, Openverse ladder).

   **1a. Convert for blog use**: normalise the hero to 1200x630 WebP:

   ```bash
   magick <folder>/hero.<ext> -resize 1200x630^ -gravity center -extent 1200x630 -quality 80 <folder>/hero.webp
   ```

   (No ImageMagick? `sips -z 630 1200 hero.<ext> --out hero.png` then convert; install `imagemagick` for WebP output.)

   **1b. Agent visual review (mandatory when `--brand` is set)**: Read `<folder>/hero.webp` with the Read tool (it renders the image) and judge it against this checklist — ALL must pass:

   - Depicts the article's actual subject, not a generic abstraction.
   - No text artifacts or garbled lettering anywhere in the frame.
   - No AI-slop tells: extra limbs/fingers, melted or fused objects, uncanny faces, impossible geometry.
   - Palette and tone fit the brand identity resolved in Phase 0.5.
   - Reads clearly at thumbnail size (the Axiom review sidebar shows it ~270px wide).

   On failure: regenerate with a corrected prompt that names the specific defect ("no text overlays", "hands out of frame", …). **Maximum 2 regeneration retries.** After 2 failures, fall back to the stock-photo ladder and review that result against the same checklist. If stock also fails, proceed WITHOUT a hero and note it in the Phase 7 summary — never block the article on the image.

2. **Format completeness**: render the canonical `.md` to `.html` and `.pdf` via `python scripts/blog_render.py --md <slug>.md --out-dir <folder>`. All three artifacts plus `hero.<ext>` must end up in the draft folder.

3. **Content review (blocking)**: dispatch the `blog-reviewer` agent (Task tool) against the rendered `.html`. The agent emits its scorecard to `<folder>/review.md` ending with `BLOCKING: true|false (reason)`. Threshold: overall score 90/100 or higher AND zero P0 issues per `editorial-heuristics.md`.

4. **Visual + asset gates**: run `python scripts/blog_preflight.py --draft <folder> --strict`. This runs Gate 3 (visual verification via patchright at 3 viewport widths), Gate 4 (reads review.md BLOCKING line), and Gate 5 (asset + link integrity). Exit 0 = ship; exit 1 = block.

5. **Iteration**: on any block, capture the failure diagnostic from `<folder>/preflight-report.json`, re-dispatch the blog-writer agent with the diagnostic as input, and re-run from step 1. Maximum 3 iterations. On the 3rd failure, STOP and present the failure diagnostic instead of the draft.

The orchestrator holds the loop counter; this sub-skill never loops itself.

### Phase 7 ordering

After Phase 6.5 passes, the next phases run in order: Phase 7 (deliver
the article locally — always runs), Phase 7.5 (submit to qant — only
runs when `--brand` is set, after local delivery), and Phase 7.6 (attach
the reviewed hero image to the submitted draft — only after a successful
Phase 7.5).

### Phase 7.5: Draft submission (only if `--brand` is set)

After Phase 6.5 returns all gates passing AND a brand context was resolved
in Phase 0.5, ship the draft to the brand's instance.

1. **Build the payload** from article state. Shape (the payload must
   NOT include `author`, `brand_slug`, or `contentType` — the server
   joins the author's canonical name from the author doc and the brand
   comes from the key):

   ```json
   {
     "title": "<frontmatter title>",
     "slug": "<frontmatter slug or derived from title>",
     "category": "<from frontmatter — MUST be one of brand_identity.content.categories>",
     "kind": "<site content kind — derived from the Phase 1.5 template, see map below>",
     "target_keyword": "<primary keyword>",
     "hero_image_url": "<frontmatter coverImage / ogImage>",
     "og": { "title": "...", "description": "...", "image": "..." },
     "body_markdown": "<the rendered .md, frontmatter stripped>",
     "flow_score": <Phase 6.5 score>,
     "metadata": { /* word count, reading time, tags, source list, canonical */ }
   }
   ```

   **`kind`** classifies the article for `/blog publish` (which route it
   lands on and which cadence slot it takes). Derive it from the template
   selected in Phase 1.5 — the template already encodes the intent, so no
   extra flag is needed:

   | Phase 1.5 template | `kind` |
   |--------------------|--------|
   | `thought-leadership` | `perspective` |
   | `pillar-page` | `pillar` |
   | any other template (or no template matched) | `spoke` |

   `kind` flows through `submit_draft.py` unchanged (it is not in the
   strip-list) and is stored on the draft. Legacy drafts written before
   this field default to `spoke` at publish time.

   `submit_draft.py` will:
   - Strip any leaked `author` / `brand_slug` / `contentType` keys from
     the payload and send `author_slug` instead.
   - Fail fast with a clear "create the author in Axiom first" message
     when the server rejects an unknown author slug.
   - The server stamps submission telemetry and creates the article
     with `status='draft'` in the brand's instance Firestore
     (`instances/{id}/brands/{slug}/blog_posts`).

   Write the payload JSON to `<draft-folder>/submission.json`.

2. **Decide whether to submit**:
   - `--no-submit` → write `submission.json`, skip the write, tell the
     user where the file lives.
   - Otherwise → submit. The contributor invoked the skill, they want
     the draft saved. No env-flag-dependent prompt.

3. **Submit** — POSTs to the QANT brand-blog API
   (`POST /brand/blog/articles`, `X-Brand-Key` header). Auth is the
   brand's own key: `NEXT_PUBLIC_BRAND_KEY` (the production `brk_` key)
   read from `/Users/adam/Projects/qant/brands/<slug>/.env.prod` → `.env`
   (first existing file wins; staging env files are never read). The API
   base is the production AU host `https://api-au.qant.au` (backed by
   `qant-core-au`); the `QANT_BLOG_API_URL` env var overrides it for local
   API development only. Resolution lives in `scripts/qant_api.py` — no
   service-account keys, no env-var setup in the contributor's shell.

   ```bash
   python3 scripts/submit_draft.py \\
       --brand-slug "<brand_slug from Phase 0.5>" \\
       --author "<author_slug from Phase 0.6>" \\
       --payload "<draft-folder>/submission.json"
   ```

   The script returns JSON on stdout:

   ```json
   {
     "author_slug": "<author_slug>",
     "draft_id":    "<auto-id>",
     "draft_path":  "<server-reported article path>"
   }
   ```

   Report `draft_path` to the user ("draft written with
   `status='draft'`. Visible in Axiom: Instances → (instance) →
   Brands → (brand) → Articles").

   The legacy direct-Firestore `scripts/submit_draft_firestore.py`
   path was retired in the brand-key API migration — all QANT drafts
   now go through `submit_draft.py`.

4. **On failure**: surface the script's stderr verbatim, write the
   payload to `<draft-folder>/submission.json` (so the user can retry
   manually), and report the failure as a non-fatal warning. The
   article is still complete locally; submission can be retried with:

   ```bash
   python3 scripts/submit_draft.py \\
       --brand-slug <slug> \\
       --author <author_slug> \\
       --payload <draft-folder>/submission.json
   ```

   Common failure modes: no brand env file or no `NEXT_PUBLIC_BRAND_KEY`
   in it (exit 2); author slug not found (exit 2 — the error tells the
   operator to create the author in Axiom: Instances → Brands →
   Authors first); API auth rejected / other API failure (exit 1 with
   the API's error detail); network unreachable (exit 1).

### Phase 7.6: Hero image attach (only after a successful Phase 7.5)

Ship the Phase 6.5 reviewed hero alongside the draft so Axiom shows it
in the article review sidebar. Uses the `draft_id` returned by
`submit_draft.py` (the script POSTs to
`/brand/blog/articles/{id}/image` with the brand key):

```bash
python3 scripts/attach_draft_image.py \\
    --brand-slug "<brand_slug>" \\
    --draft-id   "<draft_id from Phase 7.5>" \\
    --image      "<folder>/hero.webp" \\
    --mime image/webp --width 1200 --height 630 \\
    --source banana   # or gemini-direct / stock, matching how the hero was produced
```

- **Exit 3 (payload too large)**: re-encode at lower quality and retry —
  `magick <folder>/hero.webp -quality 65 <folder>/hero.webp`, then
  `-quality 50` on a second exit 3. A 1200x630 WebP at q50 is far below
  the gate; a third failure means something is wrong with the source
  image — fall through to the failure handling below.
- **No hero exists** (Phase 6.5 proceeded imageless): skip this phase
  silently; Axiom shows "No image attached".
- **On any other failure**: warn and continue — the draft is already
  submitted and stands on its own. The operator can flag an image-only
  rewrite from Axiom to attach one later. NEVER fail the
  submission over the image.

On success, include `images/hero` in the Phase 7 summary's draft_path
line (e.g. `<draft_path> (+ images/hero)`).

### Phase 7: Delivery

Present the completed article ONLY after Phase 6.5 returns all gates passing. Include the screenshots from `<folder>/preview/*.png` in the summary so the user can see what they are getting before reading the prose.

Summary template:

```
## Blog Post Complete: [Title]

### Template Used
- [Template name] (or "generic outline - no template matched")

### Statistics
- [N] sourced statistics from tier 1-3 sources
- [N] unique sources cited

### Visual Elements
- Cover image: [source - Pixabay/Unsplash/Pexels or generated SVG]
- [N] inline images (Pixabay/Unsplash/Pexels)
- [N] SVG charts (types: bar, lollipop, donut, line)
- [N] YouTube video embeds (titles: ...)

### Dual-Optimization Elements
- TL;DR box: present (N words)
- Information gain markers: [N] ([types used])
- Citation capsules: [N] across H2 sections
- Internal linking zones: [N] marked

### Structure
- [N] H2 sections with answer-first formatting
- [N] FAQ items with schema
- Word count: ~[N] words
- Estimated reading time: [N] min

### Naturalness
- Sentence length variance: [pass/fail]
- AI phrase scan: [pass/fail]
- Contractions used: [yes/no]
- Rhetorical questions: [N] (target: 1 per 200-300 words)

### Next Steps
- Review and customize for your brand voice
- Resolve [INTERNAL-LINK] placeholders with actual URLs
- Add internal links to your existing content
- Run `/blog analyze <file>` to verify quality score
- Generate VideoObject schema: `/blog schema <file>` (includes video markup)
- Generate audio narration: `/blog audio generate <file>` (optional)
```
