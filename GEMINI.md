# Project Rules: Nebula Glass

## Python Development
1. **Version Bumping**: Every time any Python file (`.py`) in the `web_app/backend/` directory is modified, the the module-level `API_VERSION = "x.y.z"` constant next to `FastAPI(...), in `main.py`, MUST be incremented (e.g., 2.1.0 -> 2.2.0).
2. **KISS Principle**: Maintain simple, functional code.
3. **Surgical Edits**: Use targeted `replace` calls instead of overwriting entire files when possible.

## Frontend Development
1. **Version Bumping**: Every time frontend source or build config under `web_app/frontend/` is modified (e.g. `src/**`, `index.html`, `vite.config.ts`, styles), the `"version": "x.y.z"` field in `web_app/frontend/package.json` MUST be incremented using the same semver spirit as backend `API_VERSION` (patch by default; one bump per task unless moving minor/major). If the task is only to set or bump that version, do not increment again in the same turn.
