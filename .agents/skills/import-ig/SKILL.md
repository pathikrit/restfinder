---
name: import-ig
description: Parse one or more Instagram or TikTok NYC-metro restaurant recommendation posts, including videos, reels, and image carousels, then consolidate grounded venue extraction and Neon matches for human review and import only the approved sources transactionally. Use for posts that recommend restaurants, bars, coffee shops, desserts, fast food, or speakeasies in RestFinder.
---

# Import IG

Use `src/restfinder/social_video.py`; do not write ad hoc SQL or infer Neon IDs
with a model. Read the repository `AGENTS.md` before starting.

No `import` command or `--import-db` use is allowed while preparing or reviewing
drafts. A human must explicitly approve the final displayed table for either a
single source or an entire clearly enumerated batch before any Neon write.

## Choose the workflow

- For one URL, prepare and review that source directly.
- For multiple URLs, use the delegated batch workflow below. Deduplicate by
  platform and stable post ID before assigning work. A final batch approval may
  authorize all displayed selected drafts; separate per-post approvals are not
  required unless the user requests them.

## Status preflight

Before downloading or analyzing each source, run:

```bash
PYTHONPATH=src uv run python -m restfinder.social_video status "POST_URL"
```

Status is read-only and identifies an Instagram post consistently across
canonical `/<kind>/<post-id>/` and creator-prefixed
`/<username>/<kind>/<post-id>/` paths. If it reports `Imported: yes`, retain the
existing rows for the final summary and skip download, analysis, and model use.
Only analyze an existing source after the user explicitly authorizes reimport;
a general batch-import request is not reimport approval.

If a supplied URL is rejected because a platform changed its post URL format,
treat that as parser maintenance rather than asking the user to rewrite it.
Resolve redirects without credentials and, when needed, inspect the visible
post in the in-app Browser. Verify that the final HTTPS host is still an allowed
Instagram or TikTok host and that the URL has a stable post identifier. Make the
smallest necessary change to `social_identity`, its path regex or host allowlist,
and focused tests in `tests/test_social_video.py`; document the supported shape
here. Run the social-video tests and skill validator, then retry `status`. Never
accept arbitrary hosts, derive identity from untrusted query parameters, or
extract browser cookies, tokens, or session storage. If identity cannot be
verified, stop and request the canonical post link instead of weakening
validation.

## Delegated batch preparation

The primary agent owns authorization and all database writes.

1. Normalize and deduplicate the URLs, then divide only the non-imported sources
   into disjoint, bounded groups. Delegate groups to available subagents when
   doing so reduces latency. Every delegated task must prohibit `import`,
   `--import-db`, manifest edits, commits, pushes, and browser credential access.
2. Each subagent runs status before analysis, prepares drafts only for new or
   explicitly authorized reimport sources, and returns a structured inventory:
   original URL, canonical reference, existing-import rows or draft path,
   inspect table, carousel count verification, and any failure or ambiguity.
3. Draft filenames are stable by platform and post ID, so never assign one post
   to multiple agents. Subagents may write distinct ignored drafts and carousel
   captures in `.restfinder/`; they must not edit shared code unless assigned a
   separate parser-maintenance task.
4. The primary agent reads every returned draft itself, reruns `inspect`, and
   consolidates all rows. Resolve failures and corrections before asking for
   approval. Do not allow an agent's summary to substitute for primary review.

## Analyze a source

For a video, analyze the post directly:

```bash
PYTHONPATH=src uv run python -m restfinder.social_video analyze "POST_URL"
```

The downloader intentionally uses no browser cookies. If public access fails,
ask the user to attach the media, then retain its original URL:

```bash
PYTHONPATH=src uv run python -m restfinder.social_video analyze \
  "path/to/media.mp4" --source-url "POST_URL"
```

For an Instagram `/p/<id>/` carousel or TikTok photo-mode post, do not analyze
only its cover. First try the URL command; the downloader can return multiple
ordered images. Confirm the draft's `media_item_count` against the visible slide
count. If the counts differ or public download fails, use the in-app Browser to
traverse from the first through last slide, tracking the visible counter and
verifying every capture is distinct. Never inspect cookies, tokens, or session
storage.

Save media-only slides in order under the ignored
`.restfinder/carousels/<platform>-<post-id>/` directory as `slide-001.png`, etc.
Exclude comments and page UI, and save the visible caption verbatim as
`caption.txt`. If any slide cannot be captured, request all slides or a ZIP and
do not analyze a partial carousel. Analyze the complete directory with:

```bash
PYTHONPATH=src uv run python -m restfinder.social_video analyze \
  ".restfinder/carousels/<platform>-<post-id>" --source-url "POST_URL"
```

## Review and approval

Read each generated `.restfinder/video-drafts/<platform>-<post-id>.json` and run
`inspect`. For carousels, confirm all slides and reconcile ranks across slides.
For every venue, review the spoken, overlay, and caption evidence; six-way type;
address; current Neon type; match method; and proposed action. Never use
decoration, food photography, or an unlabeled storefront alone as identity.

A user may exclude a row with `"selected": false`, change its type, or select a
specific Neon ID from an ambiguous result. Do not create a fallback while a
plausible canonical match remains ambiguous. Every selected row must be
`matched` or a reviewed NYC-metro `fallback` before approval. The metro boundary
matches enrichment's regional bounds (`-74.50…-73.20`, `40.40…41.20`) and
includes nearby cities such as Jersey City; do not reject those venues merely
because they are outside the five boroughs.

For a batch, display one consolidated final review grouped by source and include
all selected venues, proposed type changes and fallbacks, existing sources that
will be skipped, and failed or blocked sources. State the exact number of drafts
and selected rows the approval will authorize. Ask for explicit approval of
that displayed batch. Analysis, corrections, or approval of a different batch
never authorize a Neon write.

For large batches, generate the review artifact deterministically with
`scripts/render_batch_review.py`; pass the preflighted existing and intentionally
excluded line numbers explicitly. Read the rendered artifact before presenting
it, and supplement its generic no-draft entries with the known failure reasons.

## Import and audit after approval

Only after explicit approval, import each approved draft with its stable
manifest path:

```bash
PYTHONPATH=src uv run python -m restfinder.social_video import \
  ".restfinder/video-drafts/<platform>-<post-id>.json" \
  --manifest "imports/videos/<platform>-<post-id>.json" --import-db
```

Import sources sequentially so a failure has a clear boundary. Stop on failure;
do not claim the remaining sources were imported. Audit every reported
reference, type, and fallback count, then read back all rows using each exact
source identity. After the approved batch finishes, run `make test` and
`make build` once.

Do not add this one-time workflow to Makefile or CI targets. Do not commit or
push unless the user asks.
