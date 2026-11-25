# TraceAgent — Bundled Next.js 15 Static UI Spec (`04_FRONTEND_STATIC_UI_SPEC.md`)

The frontend is a fast, local-first Next.js 15 static export bundled directly inside the Python wheel (`src/traceagent/static/`), so `pipx install traceagent && traceagent demo` requires **zero Node.js** on the end user's machine.

---

## 1. Critical Next.js 15 Static Export Invariants (Do Not Break)

1. **`frontend/next.config.ts` MUST enforce:**
   ```ts
   import type { NextConfig } from "next";
   const nextConfig: NextConfig = {
     output: "export",
     trailingSlash: true,
     images: { unoptimized: true },
   };
   export default nextConfig;
   ```
2. **NO Dynamic `[trace_id]` App Router Folders:** Static export fails on arbitrary runtime trace IDs if you use `/traces/[id]/page.tsx`. Instead, use a single root page `/` with client-side query parameter state (`/?trace=<trace_id>`) so browser refresh NEVER returns HTTP 404.
3. **API Base URL:**
   ```ts
   export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
   ```
   - In production (served by FastAPI on `:4318`), `API_BASE` is `""` (same-origin `/api/traces`).
   - In local frontend dev (`npm run dev`), set `NEXT_PUBLIC_API_BASE=http://127.0.0.1:4318`.
4. **Build & Bundle Copy Command:**
   ```bash
   cd frontend && npm run build && rm -rf ../src/traceagent/static && cp -r out ../src/traceagent/static
   ```

---

## 2. Three-Panel Workspace Layout (Clean, High-Contrast DevTool Aesthetic)

Use a crisp dark engineering console theme (`#0B0F17` canvas, `#111827` panels, `#1F2937` borders, `#F9FAFB` text, `#38BDF8` accent, `#22C55E` pass, `#EF4444` error) — zero decorative animations or marketing fluff.

### Panel 1 — Left Sidebar (260px): Trace Explorer
- Lists all traces from `GET /api/traces` with:
  - Status dot (`green` ok / `red` error)
  - Trace name + short ID + `FORK` badge if `parent_trace_id !== null`
  - Step count + total tokens (`in / out`)
- Clicking a trace updates `?trace=<id>` and fetches `GET /api/traces/{id}`.

### Panel 2 — Center Canvas (Flexible): Waterfall Flamegraph & Audit Header
- **Top Audit Bar:**
  - Trace Name & ID
  - **SHA-256 Chain Badge:** `SHA-256 CHAIN: VALID` (green) or `TAMPERED AT SEQ N` (red) directly from `chain_verification`.
  - Total Steps, Total Duration (ms), Total Tokens.
- **Step Waterfall List:**
  - Horizontal bar per step proportional to `duration_ms` (color-coded by `op_type`: `invoke_agent`, `chat`, `execute_tool`, `mcp_call`, red outline on `status === "error"`).
  - Shows `seq`, `op_type`, `name`, `duration_ms`, and `in/out tokens`.

### Panel 3 — Right Drawer (420px): Step Inspector & Time-Travel Forker
- Displays selected step's `input`, `output`, `error`, `prev_hash`, and `step_hash`.
- **Edit & Fork Action Block:**
  - Editable JSON textarea pre-populated with selected step's `output` (validates JSON syntax live before enabling submit).
  - Mode selector strictly labeled:
    - `Deterministic Stub Replay ($0.00 — tests code/parsers)`
    - `Live Fork from Step N (saves prefix tokens)`
  - Submit triggers `POST /api/traces/{id}/fork`, displays the **Base vs. Fork Diff Summary** (`error_count_delta`, `tokens_burned`, `prefix_tokens_saved`, `replay_duration_ms`), and adds a 1-click button to open the newly created fork trace.

---

## 3. Frontend Quality Gate
- Strict TypeScript (`strict: true`), zero `any` types on API contracts (`frontend/src/lib/types.ts` must mirror `02_PROTOCOL_CONTRACTS.md`).
- Must pass `npm run typecheck && npm run lint && npm run build` with 0 errors before committing `src/traceagent/static/`.
