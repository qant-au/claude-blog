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
| `--brand <slug>` | Phase 0.5 resolves brand context (env + `.brand-seo.yml` `content:` block + author list); brand identity is injected into the drafting prompt; Phase 7.5 writes the finished draft to the shared `qant-blog-drafts` Firestore (one project for all brands; auth via two `QANT_BLOG_DRAFTS_*` env vars). |
| `--author <slug>` | Phase 0.6 loads the author bundle from `<brand_dir>/authors/<slug>/` (preferred) or `skills/blog/authors/<slug>/` (fallback); `style.md` participates as a fenced untrusted-data block; `bio.md` is rendered into the article foot; `byline.md` frontmatter populates the article's author byline. |
| `--staging` / `--development` | Selects the env file via `load_brand_context.py`. `--staging` defaults submission to YES; `--development` defaults it to NO. |
| `--no-submit` | Skips Phase 7.5 entirely. |

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

### Phase 0.5: Brand context resolution (only if `--brand` is set)

1. Resolve the brand context once at the start of the run:
   ```bash
   python3 scripts/load_brand_context.py --brand <slug> [--staging|--development]
   ```
   The JSON payload contains:
   - `brand_slug`, `brand_dir`, `env_file` — pointers.
   - `brand_domain` — canonical brand domain from `NEXT_PUBLIC_BRAND_DOMAIN`
     (or derived from `canonical.marketing` in `.brand-seo.yml`). Use for
     absolute OG URLs and the article's `canonical:` frontmatter.
   - `brand_identity` — display_name, canonical, target_keywords,
     optional primary_author, **plus `content:` block** (audience,
     strategy, plan, categories[], url_pattern, default_author) when the
     brand has migrated to the v2 schema.
   - `authors` — list of brand-local author slugs (subdirs under
     `<brand_dir>/authors/`).
   - `brand_key` and `api_url` — emitted for backward compatibility with
     the legacy HTTP submission path. Phase 7.5 no longer uses them; the
     new path is direct Firestore write authed by env-var SA key.
2. Inject `brand_identity` (display_name, canonical, target_keywords,
   content) into the drafting prompt as a small structured block. The
   `content` block is the load-bearing one — `categories[]` constrains
   the article category, `audience` and `strategy` paths point at the
   strategy doc the writer agent should consult.
3. Resolve the author slug:
   - If `--author` passed → use it (validate against
     `brand_context.authors` list).
   - Else if `brand_identity.content.default_author` present → use it.
   - Else if `brand_identity.primary_author` present (v1 schema) → use it.
   - Else prompt the user with the available slugs.

If the brand directory or env file is missing, fail fast and surface the
error from `load_brand_context.py`.

### Phase 0.6: Author bundle load (only if author slug resolved)

1. **Resolve the author directory** — try brand-local FIRST, then fall back
   to skill-local:
   - Brand-local (preferred when `--brand` set): `<brand_dir>/authors/<slug>/`
     where `brand_dir` came from Phase 0.5's loader output.
   - Skill-local fallback: `skills/blog/authors/<slug>/` (legacy single-
     project authors that haven't migrated to per-brand bundles).
   The loader emits the list of brand-local author slugs in
   `brand_context.authors`; you can list it back to the user on misses
   ("available authors for brand <slug>: a, b, c").
2. Load `style.md` via the same fenced-untrusted-data contract used for
   `VOICE.md`:
   ```bash
   HELPER="<resolved load_untrusted_root.py path per blog/SKILL.md>"
   python3 "$HELPER" --allow-any-basename <author_dir>/style.md
   ```
   The `--allow-any-basename` flag is required because `style.md` is not in
   the BRAND.md / VOICE.md / DISCOURSE.md allowlist.
3. Inject the fenced block into the writer agent's prompt. When both
   `style.md` and project-root `VOICE.md` are present, the author's
   `style.md` takes precedence on tone, sentence cadence, and banned-phrase
   list — VOICE.md is the project default; the author bundle is the named
   author's voice.
4. Read `bio.md` and `byline.md` directly (small files, not security-fenced
   — they are rendered into article output, not into the model's system
   prompt as control text). `byline.md`'s YAML frontmatter (`name`,
   `byline`) is the canonical source for the article's author object;
   `bio.md` is the longer descriptor surfaced into the article foot. Hold
   them for Phase 5 frontmatter and Phase 7 author-bio block.

If the slug resolves nowhere (neither brand-local nor skill-local), fail
with a clear error listing the brand-local options
(`brand_context.authors`) and the skill-local options (directory names
under `skills/blog/authors/`).

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

When `--author <slug>` is set: derive the `author:` value from
`<author_dir>/byline.md`'s YAML frontmatter `name:` field (canonical
source). Append the `byline:` field as a secondary frontmatter entry
(`authorByline`) for downstream renderers. If `byline.md` lacks
frontmatter (legacy bundles), fall back to the first H1 in `bio.md`
(strip any `— Author Bio` suffix).

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
   - "[Publisher], [Title], retrieved YYYY-MM-DD, [full URL]"

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

Standard markdown/HTML:
```html
<figure>
  <svg viewBox="0 0 560 380" ...>...</svg>
  <figcaption>Source: [Source Name], [Year]</figcaption>
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

2. **Format completeness**: render the canonical `.md` to `.html` and `.pdf` via `python scripts/blog_render.py --md <slug>.md --out-dir <folder>`. All three artifacts plus `hero.<ext>` must end up in the draft folder.

3. **Content review (blocking)**: dispatch the `blog-reviewer` agent (Task tool) against the rendered `.html`. The agent emits its scorecard to `<folder>/review.md` ending with `BLOCKING: true|false (reason)`. Threshold: overall score 90/100 or higher AND zero P0 issues per `editorial-heuristics.md`.

4. **Visual + asset gates**: run `python scripts/blog_preflight.py --draft <folder> --strict`. This runs Gate 3 (visual verification via patchright at 3 viewport widths), Gate 4 (reads review.md BLOCKING line), and Gate 5 (asset + link integrity). Exit 0 = ship; exit 1 = block.

5. **Iteration**: on any block, capture the failure diagnostic from `<folder>/preflight-report.json`, re-dispatch the blog-writer agent with the diagnostic as input, and re-run from step 1. Maximum 3 iterations. On the 3rd failure, STOP and present the failure diagnostic instead of the draft.

The orchestrator holds the loop counter; this sub-skill never loops itself.

### Phase 7 ordering

After Phase 6.5 passes, the next two phases run in order: Phase 7 (deliver
the article locally — always runs) and Phase 7.5 (submit to qant — only
runs when `--brand` is set, after local delivery).

### Phase 7.5: Draft submission (only if `--brand` is set)

After Phase 6.5 returns all gates passing AND a brand context was resolved
in Phase 0.5, ship the draft to the brand's instance.

1. **Build the payload** from article state into a JSON object matching
   the BlogDraft contract at
   `/Users/adam/Projects/qant/qant-private-api/qant/routers/blog.py:72–251`
   (this is the shape the consumer-app reads after a Move from drafts
   project into the instance):

   ```json
   {
     "brand_slug": "<from Phase 0.5>",
     "title": "<frontmatter title>",
     "slug": "<frontmatter slug or derived from title>",
     "category": "<from frontmatter — MUST be one of brand_identity.content.categories>",
     "target_keyword": "<primary keyword>",
     "author": {
       "slug":   "<resolved author slug>",
       "name":   "<byline.md frontmatter name:>",
       "byline": "<byline.md frontmatter byline:>",
       "bio":    "<bio.md contents, markdown-trimmed>"
     },
     "hero_image_url": "<frontmatter coverImage / ogImage>",
     "og": { "title": "...", "description": "...", "image": "..." },
     "body_markdown": "<the rendered .md, frontmatter stripped>",
     "flow_score": <Phase 6.5 score>,
     "metadata": { /* word count, reading time, tags, source list */ }
   }
   ```

   `submit_draft_firestore.py` adds the producer-side telemetry fields
   (`brand_slug` pin, `contentType`, `submittedBy`, `submittedAt`,
   `keyId`) at write time — do NOT include them in the payload.

   Write the payload JSON to `<draft-folder>/submission.json`.

2. **Decide whether to submit**:
   - `--no-submit` → write `submission.json`, skip the write, tell the user
     where the file lives.
   - `--staging` → submit by default. No prompt.
   - `--development` → DO NOT submit by default. Ask: "Submit to
     qant-blog-drafts? (y/N)".
   - default (no env flag) → ask: "Submit to qant-blog-drafts? (y/n)".

3. **Submit** — writes to the shared `qant-blog-drafts` Firestore project
   via the writer service-account key (separate Firebase project from any
   instance — credential blast radius is "blog drafts only"; see
   `~/.claude/plans/please-review-the-work-harmonic-cosmos.md` § E3 for
   the rationale). Auth is via two env vars set in the contributor's shell:

   - `QANT_BLOG_DRAFTS_PROJECT_ID` — e.g. `qant-blog-drafts`
   - `QANT_BLOG_DRAFTS_WRITER_KEY` — absolute path to writer SA JSON

   ```bash
   python3 scripts/submit_draft_firestore.py \\
       --brand-slug "<brand_slug from Phase 0.5>" \\
       --payload "<draft-folder>/submission.json"
   ```
   The script returns the new Firestore doc path on stdout (JSON:
   `{"id": "...", "path": "brands/<slug>/drafts/<id>"}`). Report the path
   to the user ("visible in the consumer-app Blog module → Drafts once
   the consumer-side wiring lands; meanwhile inspect in the Firebase
   console for project `qant-blog-drafts`").

   The legacy HTTP-based path (`scripts/submit_draft.py` POSTing to
   `${api_url}/private/blog/drafts` with a per-brand bearer key) is kept
   in the repo for backward compatibility with non-QANT consumers, but is
   NOT used by this skill anymore.

4. **On failure**: surface the script's stderr verbatim, write the
   payload to `<draft-folder>/submission.json` (so the user can retry
   manually), and report the failure as a non-fatal warning. The article
   is still complete locally; submission can be retried with:

   ```bash
   python3 scripts/submit_draft_firestore.py \\
       --brand-slug <slug> \\
       --payload <draft-folder>/submission.json
   ```

   Common failure modes: missing env vars (exit 2 — script prints the
   plan-file pointer); SA key file missing (exit 2); IAM denied (exit 1
   with the google-cloud-firestore error); network unreachable (exit 1).

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
