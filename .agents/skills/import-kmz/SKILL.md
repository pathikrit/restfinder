---
name: import-kmz
description: Import a Google My Maps KMZ as a named curated restaurant list, with explicit folder-to-type mapping, canonical DOHMH matching, fallback deduplication, and a reviewed Neon write. Use for new friend maps or other one-time KMZ sources in RestFinder.
---

# Import KMZ

Use `src/restfinder/kmz.py`; do not create a source-specific importer.

1. Read the repository `AGENTS.md`. Copy the source KMZ into `data/` under a
   durable list-oriented filename, leaving the original file untouched unless
   the user explicitly requests a move.
2. Inspect every folder before selecting candidates:

   ```bash
   PYTHONPATH=src uv run python -m restfinder.kmz "data/List.kmz" \
     --source "Person's List" --all --limit 0
   ```

3. Translate only user-approved folders with repeated
   `--category "FOLDER=TYPE"` arguments. Unmapped folders are skipped. Supported
   types are `Restaurant`, `Bars`, `Coffee Shops`, `Dessert`, `Fast Food`, and
   `Hidden / Speakeasy`. A folder mapped to `Coffee Shops` automatically uses
   dessert keywords to classify obvious bakeries, ice cream, and sweets as
   `Dessert`.
4. Run the same command without `--all` and without `--import-db` to review the
   candidate count, folder counts, type counts, and parsed names. Never write to
   Neon merely because a file was inspected.
5. When the user has authorized the import, rerun the reviewed command with
   `--import-db`. The importer coalesces same-name source pins within 100 meters,
   keeps only places within a nominal two-hour OSRM drive of Times Square, and
   matches in this order:
   - current or historical canonical DOHMH rows;
   - existing external fallback rows from other lists;
   - a new fallback row namespaced to this list.

   Matching requires nearby coordinates plus an exact normalized name or a
   high-confidence name similarity. Ambiguous candidates remain new fallbacks;
   do not force arbitrary permit matches.
6. Audit the reported direct/fuzzy match, ambiguity, fallback, and reference
   counts in Neon. Confirm every imported target has the exact list name as its
   reference and no orphan references exist. Run `make test` and `make build`.

One-time snapshots and importer invocations must not be added to recurring CI or
Makefile targets. Do not commit or push unless the user asks.
