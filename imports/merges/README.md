# Reviewed duplicate decisions

Run `make duplicates`, review the ignored `.restfinder/duplicate-review.json`,
and copy completed decisions into a dated JSON manifest in this directory.
Apply a reviewed manifest explicitly with:

```bash
PYTHONPATH=src uv run python -m restfinder.duplicates apply imports/merges/<file>.json
```

Never change a decision from `defer` to `merge` without reviewing both venues.
