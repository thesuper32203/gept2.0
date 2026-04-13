# Error Log — Bugs Debugged & Resolved

Track every significant error encountered and how it was fixed.

## Format
```
### [YYYY-MM-DD HH:MM EST] — Error summary
- **Error**: Full error message or description
- **Root cause**: What caused it
- **Fix**: What was changed to resolve it
- **Files affected**: list of files
```

---

### [2026-04-12 08:10 PM EST] — Docker collector pointed at wrong database host
- **Error**: `docker-compose.yml` had `DB_HOST: host.docker.internal` and `DB_PORT: "6543"`, pointing the collector at the local machine instead of the containerized TimescaleDB service
- **Root cause**: Previous configuration was set up for local development against a host-side PostgreSQL; never updated for full Docker deployment
- **Fix**: Changed `DB_HOST` to `db` (Docker service name) and `DB_PORT` to `"5432"` (container-internal port)
- **Files affected**: `docker-compose.yml`

### [2026-04-12 08:10 PM EST] — Schema CREATE INDEX not idempotent
- **Error**: `CREATE INDEX` statements in `schema.sql` lacked `IF NOT EXISTS`, would fail on re-initialization
- **Root cause**: Original schema only used `IF NOT EXISTS` on tables and hypertables but not on indexes
- **Fix**: Added `IF NOT EXISTS` to both `CREATE INDEX` statements
- **Files affected**: `packages/collector/db/schema.sql`

### [2026-04-12 08:12 PM EST] — Stale Docker container name conflict
- **Error**: `Error response from daemon: Conflict. The container name "/gept-db" is already in use`
- **Root cause**: `docker compose down -v` removed the compose-managed containers but a stale container with the same name persisted from a previous manual run
- **Fix**: Ran `docker rm -f gept-db gept-collector` to clear orphaned containers before starting
- **Files affected**: N/A (runtime fix)

### [2026-04-12 08:14 PM EST] — Python stdout buffering hid Docker container logs
- **Error**: All collector logs appeared with identical timestamps; no real-time log visibility via `docker logs`
- **Root cause**: Python fully buffers stdout when not connected to a TTY (standard Docker behavior)
- **Fix**: Added `PYTHONUNBUFFERED: "1"` environment variable to the collectors service in `docker-compose.yml`
- **Files affected**: `docker-compose.yml`
