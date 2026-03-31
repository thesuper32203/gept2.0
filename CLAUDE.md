# gept2.0 — Claude Instructions

## Python Standards
- Follow PEP8: 4-space indent, snake_case variables/functions, PascalCase classes, UPPER_SNAKE constants
- Add type hints to all function signatures: `def fetch_prices(item_id: int) -> dict:`
- Keep functions focused — if a function does more than one thing, split it
- Prefer explicit over clever — readable code beats compact code

## Before Writing Code
- For any multi-step feature (more than 1 file), use `/claude-mem:make-plan` first
- Use `/claude-mem:smart-explore` to understand existing code structure before editing — do not read full files just to explore

## Code Quality
- After every file edit, review the change: does it duplicate existing logic? Could it be a shared utility?
- Modules should have a single clear responsibility — if a file is doing too many things, flag it
- No magic numbers — use named constants
- No unused imports

## Project Architecture Rules
- `packages/collector/` — only data collection logic, no business logic
- `packages/engine/` — only ML and recommendation logic, no HTTP concerns
- `packages/api/` — only HTTP routing and request/response handling, delegates to engine
- `packages/web/` — only frontend, talks to api only
- Cross-package imports are not allowed — packages communicate only through the API layer

## Memory Efficiency
- Use `ctx_execute_file` (context-mode) when analyzing large files or logs — do not load raw output into context
- Use `ctx_search` for follow-up questions about already-indexed content

## PRD & CLAUDE.md Sync Rules
- If a new feature, module, or structural decision is added that is NOT in `PRD.md`, update `PRD.md` immediately
- If a new coding rule, architectural constraint, or pattern is established, add it to `CLAUDE.md`
- Never let the codebase drift silently from the plan — every intentional deviation must be documented

## Change Logging (logs/)
- After any significant structural change (new file, new module, refactored architecture), add an entry to `logs/changes.md`
- After resolving any non-trivial bug or error, log it in `logs/errors.md`
- Log format: date, what changed, why, files affected, whether PRD/CLAUDE.md were updated
