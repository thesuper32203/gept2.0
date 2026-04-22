# Changelog — Structural Changes & Additions

Track every significant structural change, new feature, or architectural decision made to the codebase.

## Format
```
### [YYYY-MM-DD HH:MM EST] — Short title
- **What changed**: Description
- **Why**: Reason for the change
- **Files affected**: list of files
- **PRD updated**: yes/no
- **CLAUDE.md updated**: yes/no
```

---

<!-- Entries added below as changes are made -->

### [2026-04-19 EST] — Removed ML pipeline, shifted to rule-based engine
- **What changed**: Removed all ML code from `packages/engine/features/builder.py` (sklearn, xgboost, lightgbm, joblib imports; model instantiations; `target_features`, `train`, `test` functions). Rewrote PRD.md to remove Phases 2B-2F (ML models, training pipeline, evaluation, inference service) and replace with rule-based scanner docs. Rewrote `docs/phase2/README.md` as a build guide for the rule-based scanner and backtester. Updated README.md title, project structure, and added scanner run instructions.
- **Why**: Simplifying to rule-based approach — transparent (every decision is a readable formula), no training infrastructure needed, faster to iterate
- **Files affected**: packages/engine/features/builder.py, PRD.md, docs/phase2/README.md, README.md
- **PRD updated**: yes
- **CLAUDE.md updated**: no

### [2026-04-12 08:15 PM EST] — Docker deployment fixes for full containerized operation
- **What changed**: Switched collector DB_HOST from `host.docker.internal:6543` to `db:5432` for Docker-internal networking. Added `PYTHONUNBUFFERED=1` to fix silent log buffering. Added `IF NOT EXISTS` to schema index creation. Resolved stale container name conflicts.
- **Why**: Collector was configured to talk to host machine DB instead of the containerized TimescaleDB; Python stdout buffering made Docker logs appear frozen
- **Files affected**: docker-compose.yml, packages/collector/db/schema.sql
- **PRD updated**: no
- **CLAUDE.md updated**: no

### [2026-04-10 10:45 AM EST] — Phase 1 bug fixes across collector pipeline
- **What changed**: Fixed 6 bugs: DB_PORT string→int cast (connection.py), null guard on failed API fetch (items.py), save_prices missing return 0 (base.py), None snapshot_time guard (base.py), create_hypertable idempotency (schema.sql), removed bad linter-injected imports (items.py, backfill.py)
- **Why**: Multiple runtime crash paths discovered during phase 1 review — DB pool creation would TypeError, failed API fetches would crash item collection, duplicate hypertable creation would fail on Docker restart
- **Files affected**: connection.py, items.py, base.py, schema.sql, backfill.py
- **PRD updated**: no
- **CLAUDE.md updated**: no

### [2026-04-10 10:50 AM EST] — Replaced PatchTST with feature-engineered GBDT pipeline in PRD
- **What changed**: Rewrote Phase 2 to use XGBoost/LightGBM/RF/LogReg instead of PatchTST transformer. Added 50+ feature definitions (lags, returns, moving averages, volatility, volume, spread, breakouts, time, item-level). Defined regression and classification targets, training pipeline, evaluation metrics, profit backtesting, and inference service. Updated tech stack, architecture diagram, project structure, and differentiators.
- **Why**: Gradient boosted models are proven best-in-class for tabular financial data — faster training, interpretable, no GPU required, easier to iterate as a solo developer
- **Files affected**: PRD.md
- **PRD updated**: yes
- **CLAUDE.md updated**: no

### [2026-04-10 10:30 AM EST] — Added EST 12-hour logging to collector entry point
- **What changed**: Added ESTFormatter class to packages/collector/main.py (Docker entry point) with 12-hour clock and Eastern timezone. Moved logging setup before package imports with force=True to override module-level handlers.
- **Why**: Logs were displaying UTC 24-hour time, user needs Eastern time for readability
- **Files affected**: packages/collector/main.py, packages/collector/collectors/main.py
- **PRD updated**: no
- **CLAUDE.md updated**: no

### [2026-04-10 10:15 AM EST] — Fixed threading.Thread args tuple bug
- **What changed**: Changed `args="prices_5min"` to `args=("prices_5min",)` in both main.py files for backfill thread creation
- **Why**: Bare string in args iterates characters as separate arguments, causing TypeError in backfill.run()
- **Files affected**: packages/collector/main.py, packages/collector/collectors/main.py
- **PRD updated**: no
- **CLAUDE.md updated**: no

### [2026-04-10 11:15 AM EST] — Created Phase 2 implementation guide
- **What changed**: Added `docs/phase2/README.md` — step-by-step guide covering feature engineering, model training, evaluation, inference, and Docker deployment. Minimal code with imports, focused on learning/understanding rather than copy-paste implementation.
- **Why**: Beginner-oriented documentation so the developer can learn while building
- **Files affected**: docs/phase2/README.md
- **PRD updated**: no
- **CLAUDE.md updated**: no

### [2026-04-10 10:55 AM EST] — Created README.md for deployment
- **What changed**: Added README with setup instructions, Docker deployment steps, database connection guide, project structure, and troubleshooting
- **Why**: Users need documentation to deploy the project
- **Files affected**: README.md
- **PRD updated**: no
- **CLAUDE.md updated**: no
