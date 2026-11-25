# ADR-003: Bundled Static Next.js 15 UI

## Status
Accepted

## Context
Requiring end users to install Node.js or run a separate frontend dev server creates friction for a Python CLI observability tool (`pip install traceagent && traceagent demo`).

## Decision
Build the Next.js 15 + React 19 + Tailwind CSS frontend with `output: "export"`, copy `frontend/out/` into `src/traceagent/static/`, include `artifacts = ["src/traceagent/static/**"]` in `pyproject.toml`, and mount it in FastAPI via `StaticFiles(html=True)` after all `/v1/*` and `/api/*` routes.

## Consequences
- End users need **zero Node.js** at runtime.
- Single-command offline `traceagent demo` serves both the API and the 3-panel Flamegraph & Fork UI on `127.0.0.1`.
