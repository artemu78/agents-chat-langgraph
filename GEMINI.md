# Project Rules: Nebula Glass

## Python Development
1. **Version Bumping**: Every time any Python file (`.py`) in the `web_app/backend/` directory is modified, the the module-level `API_VERSION = "x.y.z"` constant next to `FastAPI(...), in `main.py`, MUST be incremented (e.g., 2.1.0 -> 2.2.0).
2. **KISS Principle**: Maintain simple, functional code.
3. **Surgical Edits**: Use targeted `replace` calls instead of overwriting entire files when possible.
