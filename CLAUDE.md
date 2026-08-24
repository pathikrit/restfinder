# RestFinder contributor notes

RestFinder is a Python 3.13.2/uv project with a Neon-compatible PostgreSQL data
pipeline and a static Leaflet frontend.

- Keep Python and JavaScript dependencies pinned to exact versions.
- Never commit `.env`, `.site/`, or generated restaurant JSON.
- Apply schema changes through Alembic migrations.
- Preserve stable IDs in the form `<source>:<external-id>`.
- Fetches must be complete and transactional; never partially advance
  `last_seen`.
- Reference manifests under `imports/` are tracked inputs and must be
  idempotent.
- Run `make test` and `make build` before handing off changes.
