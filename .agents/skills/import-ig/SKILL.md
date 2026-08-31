---
name: import-ig
description: Parse an Instagram or TikTok NYC restaurant recommendation post, including videos, reels, and image carousels, then review grounded venue extraction and Neon matches and import the approved source transactionally. Use for posts that recommend restaurants, bars, coffee shops, desserts, fast food, or speakeasies in RestFinder.
---

# Import IG

Use `src/restfinder/social_video.py`; do not write ad hoc SQL or infer Neon IDs
with a model.

If a supplied Instagram or TikTok URL is rejected because the platform changed
its post URL format, treat that as parser maintenance rather than asking the
user to rewrite the URL. Resolve redirects without credentials and, when
needed, inspect the visible post in the in-app Browser. Verify that the final
HTTPS host is still an allowed Instagram or TikTok host and that the URL has a
stable post identifier. Then make the smallest necessary update to
`social_identity`, its path regex or host allowlist, and focused tests in
`tests/test_social_video.py`; document the newly supported shape in this skill.
Run the social-video tests and the skill validator, then retry `status`. Never
accept arbitrary hosts, derive identity from untrusted query parameters, or
extract browser cookies, tokens, or session storage. If the post identity
cannot be verified, stop and request the canonical post link instead of
weakening validation.

1. Read the repository `AGENTS.md`. Work on exactly one post and resolve its
   original URL. Before downloading or analyzing it, check Neon using:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video status "POST_URL"
   ```

   This is a read-only lookup of the canonical URL in
   `restaurant_references.reference`. If it reports `Imported: yes`, show the
   existing rows and ask whether the user wants to reimport this post. Do not
   download, analyze, edit references, or incur model usage unless the user
   explicitly confirms reimport. If they decline, stop. A prior general request
   to import videos is not reimport approval for an already-present URL.

2. For a new source, or after explicit reimport confirmation, identify whether
   it is a video or an image carousel. For a video, analyze the post directly:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video analyze "POST_URL"
   ```

   The downloader intentionally uses no browser cookies. If public access fails,
   ask the user to attach or download the media, then use:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video analyze \
     "path/to/media.mp4" --source-url "POST_URL"
   ```

   For an image carousel, do not analyze only its cover. This applies to
   Instagram `/p/<id>/` carousels and TikTok photo-mode posts, whose canonical
   URL may use `/@user/photo/<id>` or `/@user/video/<id>`. First try the same
   URL command; the downloader can return multiple ordered images. Confirm the
   draft's `media_item_count` against the post's visible slide count. If the
   counts differ, or the downloader cannot access the carousel, use the in-app
   Browser when available to open the canonical post and traverse manually
   from the first slide through the last. On Instagram use the carousel next
   control and visible counter; on TikTok use the photo-post next control and
   dots or counter. Do not assume TikTok autoplay visited every photo. Scroll
   only as needed to keep the media and controls visible. Track the slide
   counter and order, and verify every captured slide is distinct. Do not
   inspect or extract browser cookies, tokens, or session storage.

   Save complete, media-only slide captures in order under the ignored
   `.restfinder/carousels/<platform>-<post-id>/` directory using zero-padded
   names such as `slide-001.png`. Exclude comments, recommendations, and page UI
   from the captures. Save the post's visible caption verbatim as `caption.txt`
   in that directory. If browser capture is unavailable or any slide cannot be
   read, ask the user to provide all slides or a ZIP; do not proceed with a
   partial carousel. Analyze the completed directory while retaining the
   original post URL:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video analyze \
     ".restfinder/carousels/<platform>-<post-id>" \
     --source-url "POST_URL"
   ```

3. Read the generated `.restfinder/video-drafts/<platform>-<post-id>.json` and
   show the `inspect` table. For a carousel, first confirm every slide was
   included and reconcile ranks or list numbering across slides. For every
   venue, review the spoken/overlay/caption evidence, six-way type, address,
   current Neon type, match method, and proposed action. Never treat decoration,
   food photography, or an unlabeled storefront alone as venue identity.
4. Resolve corrections in the draft. A user may exclude a row with
   `"selected": false`, change its type, or select a specific Neon ID from an
   ambiguous result. Do not create a fallback when a plausible canonical match
   is still ambiguous. Every selected row must be `matched` or a reviewed NYC
   `fallback` before approval.
5. Ask for explicit approval of this video's final table. Inspection, analysis,
   corrections, or prior approval of another video never authorize a Neon write.
6. Only after approval, run:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video import \
     ".restfinder/video-drafts/<platform>-<post-id>.json" \
     --manifest "imports/videos/<platform>-<post-id>.json" \
     --import-db
   ```

7. Audit the reported reference/type/fallback counts and read back all rows with
   the exact source URL. Run `make test` and `make build`.

Do not add this one-time workflow to Makefile or CI targets. Do not commit or
push unless the user asks.
