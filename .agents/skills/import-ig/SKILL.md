---
name: import-ig
description: Parse an Instagram or TikTok NYC restaurant recommendation post, review grounded venue extraction and Neon matches, and import the approved source transactionally. Use for social videos, reels, or posts that recommend restaurants, bars, coffee shops, desserts, fast food, or speakeasies in RestFinder.
---

# Import IG

Use `src/restfinder/social_video.py`; do not write ad hoc SQL or infer Neon IDs
with a model.

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

2. For a new source, or after explicit reimport confirmation, analyze the post:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video analyze "POST_URL"
   ```

   The downloader intentionally uses no browser cookies. If public access fails,
   ask the user to attach or download the media, then use:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.social_video analyze \
     "path/to/media.mp4" --source-url "POST_URL"
   ```

3. Read the generated `.restfinder/video-drafts/<platform>-<post-id>.json` and
   show the `inspect` table. For every venue, review the spoken/overlay evidence,
   six-way type, address, current Neon type, match method, and proposed action.
   Never treat decoration alone as venue identity.
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
