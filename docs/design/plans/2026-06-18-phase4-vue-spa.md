# Phase 4 — Vue 3 SPA (web UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **View tasks (6–9) must additionally use the `frontend-design` skill** to produce polished, distinctive UI while keeping the specified script logic and passing the listed tests.

**Goal:** Build the browser app the prior three phases were leading to — a Vite + Vue 3 + TypeScript SPA that manages vehicles, documents, and jobs and hosts the streaming agentic chat (with live OBD/web tool activity and source citations), served by the existing FastAPI backend.

**Architecture:** A new `frontend/` Vite project (Vue 3 + TS + Tailwind v4 + Pinia + vue-router + Vitest). A typed REST client mirrors the FastAPI schemas; a fetch-based SSE reader consumes the `POST /api/jobs/{id}/messages` token stream. Pinia stores hold vehicles, scanner status, and config. Views: Vehicles, Vehicle detail (documents + jobs), Chat, Settings. **Dev:** Vite dev server (`:5173`) proxies `/api` → FastAPI (`:8000`). **Prod:** `npm run build` emits `frontend/dist`, which the backend already serves via `StaticFiles(html=True)` — a single command on a single port.

**Tech Stack:** Vite, Vue 3 (`<script setup lang="ts">`), TypeScript, Tailwind CSS v4 (`@tailwindcss/vite`, CSS-first `@theme`), Pinia, vue-router, Vitest + @vue/test-utils + jsdom. One small Python addition (`GET /api/config`) on the FastAPI side.

This is Plan 4 of the phased v1 work (Plans 1–3 — backend foundation, agentic chat, OBD tools + web search — are complete; Plan 4 branches from the Phase 3 tip). It is the last v1 plan and produces the shippable web app.

## Key decisions baked into this plan

- **TypeScript + Tailwind v4 with a small custom design system** (user choice). No component library — a hand-built "garage console" look (dark industrial-clean surfaces, an amber accent, monospace for codes/specs) keeps it distinctive and portfolio-worthy. Design tokens live in `@theme` (Task 2); view tasks use the `frontend-design` skill to elevate the markup.
- **fetch-based SSE reader, not `EventSource`.** The chat endpoint is a `POST` returning `text/event-stream`; `EventSource` cannot POST, so the reader uses `fetch` + `response.body.getReader()` and parses `data: {json}\n\n` frames (Task 4).
- **No backend serving/CORS change.** `main.py` already mounts `frontend/dist` with `html=True` (SPA fallback) and allows the Vite dev origin. The only backend change is the new read-only `GET /api/config` (Task 1) the Settings view needs.
- **Versions resolved at scaffold time.** The scaffold uses `npm create vite@latest ... --template vue-ts` and `npm install` (latest), committing the generated `package.json`/lockfile, rather than pinning version numbers in this plan.

## Global Constraints

- Node ≥ 20.19 (or ≥ 22.12). All frontend work happens inside `frontend/`; run npm/vitest from there. The repo root stays a Python project.
- Frontend tests use **Vitest** (`environment: "jsdom"`, `globals: true`), `@vue/test-utils` `mount()`, and `createMemoryHistory` for any router-dependent test. Run with `npm test` (`vitest run`) from `frontend/`. Tests never hit the network: `fetch` is stubbed (`vi.stubGlobal`) or the API client is mocked (`vi.mock`).
- Tailwind v4: configure via `@import "tailwindcss";` + `@theme {}` in the CSS entry and the `@tailwindcss/vite` plugin. **Do not create `tailwind.config.js`** and do not use `@tailwind base/components/utilities` directives or a PostCSS config.
- The `@/` path alias maps to `frontend/src/` in both `vite.config.ts` (`resolve.alias`) and `tsconfig.app.json` (`paths`). `vitest.config.ts` inherits the alias via `mergeConfig(viteConfig, …)`.
- The API client targets relative `/api/...` paths (same-origin in prod; proxied in dev). Never hardcode `http://localhost:8000` in app code.
- TypeScript is strict (the `@vue/tsconfig` base enables `strict: true`). `npm run build` (which runs `vue-tsc` then `vite build`) must pass with no type errors.
- The Python side: any change keeps the full `uv run pytest tests/ -v` suite green; OpenAI/MCP stay mocked; no secrets are exposed by `GET /api/config` (booleans and non-secret strings only).
- `frontend/node_modules` and `frontend/dist` are git-ignored. Commit messages plain, conventional-commit style; no AI/Claude attribution in tracked content.

### Backend API surface the SPA consumes (reference — exact shapes)

```
GET    /api/health                              -> { "status": "ok" }
GET    /api/config                              -> ConfigOut (Task 1)
GET    /api/vehicles                            -> VehicleOut[]
POST   /api/vehicles                  (201)     <- VehicleCreate  -> VehicleOut
GET    /api/vehicles/{id}             (404)     -> VehicleOut
GET    /api/vehicles/{id}/jobs                  -> JobOut[]
POST   /api/vehicles/{id}/jobs        (201,404) <- JobCreate      -> JobOut
GET    /api/jobs/{id}                 (404)     -> JobOut
GET    /api/vehicles/{id}/documents             -> DocumentOut[]
GET    /api/documents/{id}            (404)     -> DocumentOut
POST   /api/vehicles/{id}/documents   (202,404,413,415)  multipart file=<pdf>  -> DocumentOut (pending)
GET    /api/jobs/{id}/messages                  -> ChatMessageOut[]
POST   /api/jobs/{id}/messages        (SSE)     <- { content }    -> text/event-stream
GET    /api/scanner/status                      -> { available, scanner_reachable, detail }

VehicleOut    { id, year, make, model, engine, vin: string|null, notes: string|null, created_utc }
JobOut        { id, vehicle_id, title, description: string|null, status, created_utc }
DocumentOut   { id, vehicle_id, file_name, document_type, processing_status, uploaded_utc }
                processing_status ∈ "pending" | "ready" | "failed"
ChatMessageOut{ id, job_id, role, content, sources_json: Array<object>|null, created_utc }
                NOTE: sources_json arrives PARSED as an array (or null), not a JSON string.

SSE events (one JSON object per `data:` frame):
  { "type": "token",       "text": string }
  { "type": "tool_call",   "name": string, "arguments": object }
  { "type": "tool_result", "name": string }
  { "type": "sources",     "sources": Array<object> }
  { "type": "done" }
  { "type": "error",       "detail": string }
```

---

### Task 1: Backend — read-only `GET /api/config` endpoint

**Files:**
- Modify: `app/api/schemas.py` (add `ConfigOut`)
- Create: `app/api/routers/config.py`
- Modify: `app/api/main.py` (include the router)
- Test: `tests/test_api/test_config_endpoint.py` (create)

**Interfaces:**
- Produces: `GET /api/config` → `ConfigOut { openai_key_present: bool, obd_mcp_enabled: bool, obd_port: str, web_search_enabled: bool, web_search_key_present: bool, chat_model: str, embed_model: str }`. Reads `app.config.settings`; exposes only booleans and non-secret strings (never the keys themselves).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_config_endpoint.py`:
```python
def test_config_reports_non_secret_status(api_client):
    r = api_client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "openai_key_present",
        "obd_mcp_enabled",
        "obd_port",
        "web_search_enabled",
        "web_search_key_present",
        "chat_model",
        "embed_model",
    }
    assert isinstance(body["openai_key_present"], bool)
    assert body["obd_port"]  # non-empty default
    # Never leak the actual secret values.
    assert "sk-" not in str(body)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_config_endpoint.py -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add the schema**

Append to `app/api/schemas.py`:
```python
class ConfigOut(BaseModel):
    openai_key_present: bool
    obd_mcp_enabled: bool
    obd_port: str
    web_search_enabled: bool
    web_search_key_present: bool
    chat_model: str
    embed_model: str
```

- [ ] **Step 4: Create the router**

Create `app/api/routers/config.py`:
```python
from fastapi import APIRouter

from app.api.schemas import ConfigOut
from app.config import settings

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=ConfigOut)
def get_config() -> ConfigOut:
    return ConfigOut(
        openai_key_present=bool(settings.openai_api_key),
        obd_mcp_enabled=settings.obd_mcp_enabled,
        obd_port=settings.obd_port,
        web_search_enabled=settings.web_search_enabled,
        web_search_key_present=bool(settings.tavily_api_key),
        chat_model=settings.openai_chat_model,
        embed_model=settings.openai_embed_model,
    )
```

- [ ] **Step 5: Include the router**

In `app/api/main.py`, add `config` to the routers import line and include it:
```python
from app.api.routers import vehicles, jobs, documents, chat, scanner, config
```
```python
    app.include_router(scanner.router)
    app.include_router(config.router)
```

- [ ] **Step 6: Run the test + full suite**

Run: `uv run pytest tests/test_api/test_config_endpoint.py -v`
Expected: PASS.
Run: `uv run pytest tests/ -v`
Expected: PASS (all prior + new).

- [ ] **Step 7: Commit**

```bash
git add app/api/schemas.py app/api/routers/config.py app/api/main.py tests/test_api/test_config_endpoint.py
git commit -m "feat(api): add read-only config status endpoint for the web UI"
```

---

### Task 2: Frontend scaffold (Vite + Vue 3 + TS + Tailwind v4 + Pinia + router + Vitest)

**Files:**
- Create: the `frontend/` Vite project (generated), then customized:
  - `frontend/vite.config.ts`, `frontend/vitest.config.ts`, `frontend/tsconfig.app.json` (alias)
  - `frontend/src/style.css` (Tailwind import + `@theme` design tokens)
  - `frontend/src/main.ts`, `frontend/src/App.vue`, `frontend/src/router/index.ts`
  - `frontend/src/views/VehiclesView.vue` (placeholder home), `frontend/src/components/__tests__/smoke.test.ts`
- Modify: `.gitignore` (ignore `frontend/node_modules`, `frontend/dist`)

**Interfaces:**
- Produces: a runnable SPA shell. `npm run dev` serves on `:5173` proxying `/api` → `:8000`; `npm run build` emits `frontend/dist`; `npm test` runs Vitest. The `@/` alias resolves in app, build, and tests. Design tokens (`bg-bg`, `bg-surface`, `text-muted`, `bg-accent`, `font-mono`, `rounded-card`, …) are available app-wide.

- [ ] **Step 1: Scaffold the project**

From the repo root:
```bash
npm create vite@latest frontend -- --template vue-ts
cd frontend
npm install
npm install tailwindcss @tailwindcss/vite pinia vue-router
npm install -D vitest @vue/test-utils jsdom
```
Expected: `frontend/` created with the vue-ts template; deps installed; `frontend/package.json` and lockfile present.

- [ ] **Step 2: Ignore build artifacts**

Append to the repo-root `.gitignore`:
```gitignore
# Frontend
frontend/node_modules/
frontend/dist/
frontend/*.tsbuildinfo
```

- [ ] **Step 3: Configure Vite (plugin, alias, proxy)**

Replace `frontend/vite.config.ts` with:
```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
```

- [ ] **Step 4: Configure Vitest**

Create `frontend/vitest.config.ts`:
```ts
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: { environment: 'jsdom', globals: true },
  }),
)
```

In `frontend/package.json`, ensure the `scripts` block contains:
```json
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 5: Add the `@/` path alias to tsconfig**

In `frontend/tsconfig.app.json`, add inside `compilerOptions`:
```json
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
```

- [ ] **Step 6: Design tokens + Tailwind entry**

Replace `frontend/src/style.css` with:
```css
@import "tailwindcss";

@theme {
  /* "Garage console" — dark industrial-clean with an amber accent */
  --color-bg: #0f1419;
  --color-surface: #171d26;
  --color-surface-2: #1e2630;
  --color-border: #2b3441;
  --color-text: #e7edf3;
  --color-muted: #8b97a6;
  --color-accent: #f5a623;        /* amber — shop signage / warning lamp */
  --color-accent-strong: #ff8c1a;
  --color-success: #3ecf8e;
  --color-warning: #f5a623;
  --color-danger: #ef4444;

  --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;

  --radius-card: 0.75rem;
}

html, body, #app { height: 100%; }
body { background: var(--color-bg); color: var(--color-text); }
```

- [ ] **Step 7: Router, store, app shell**

Replace `frontend/src/router/index.ts`:
```ts
import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'vehicles', component: () => import('@/views/VehiclesView.vue') },
  ],
})
```

Replace `frontend/src/main.ts`:
```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { router } from '@/router'
import App from './App.vue'
import './style.css'

createApp(App).use(createPinia()).use(router).mount('#app')
```

Replace `frontend/src/App.vue`:
```vue
<script setup lang="ts"></script>

<template>
  <div class="min-h-full">
    <router-view />
  </div>
</template>
```

Create `frontend/src/views/VehiclesView.vue` (placeholder, replaced in Task 6):
```vue
<script setup lang="ts"></script>

<template>
  <main class="p-8">
    <h1 class="text-2xl font-semibold text-accent">Mechanic Sidekick</h1>
    <p class="text-muted">Web UI scaffold is running.</p>
  </main>
</template>
```

- [ ] **Step 8: Smoke test**

Create `frontend/src/components/__tests__/smoke.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import VehiclesView from '@/views/VehiclesView.vue'

describe('scaffold', () => {
  it('renders the app heading', () => {
    const wrapper = mount(VehiclesView)
    expect(wrapper.text()).toContain('Mechanic Sidekick')
  })
})
```

- [ ] **Step 9: Verify dev/build/test, then commit**

Run (from `frontend/`): `npm test`
Expected: 1 passing test.
Run: `npm run build`
Expected: type-check + build succeed; `frontend/dist/index.html` exists.

```bash
cd ..
git add frontend .gitignore
git commit -m "feat(web): scaffold Vue 3 + TS + Tailwind v4 SPA with router, Pinia, Vitest"
```
(The committed `frontend/` excludes `node_modules`/`dist` per `.gitignore`.)

---

### Task 3: API types + typed REST client

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Test: `frontend/src/api/__tests__/client.test.ts`

**Interfaces:**
- Produces:
  - `types.ts` — `Vehicle`, `VehicleCreate`, `Job`, `JobCreate`, `Document`, `ChatMessage`, `ScannerStatus`, `AppConfig` interfaces matching the backend shapes (reference table in Global Constraints).
  - `client.ts` — `api` object: `listVehicles()`, `getVehicle(id)`, `createVehicle(body)`, `listJobs(vehicleId)`, `getJob(id)`, `createJob(vehicleId, body)`, `listDocuments(vehicleId)`, `uploadDocument(vehicleId, file)`, `listMessages(jobId)`, `getScannerStatus()`, `getConfig()`. Each returns a typed Promise and throws `ApiError` on non-2xx. (The chat SSE POST is NOT here — it lives in Task 4.)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/__tests__/client.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, ApiError } from '@/api/client'

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response
}

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('lists vehicles via GET /api/vehicles', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([{ id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' }]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const vehicles = await api.listVehicles()

    expect(fetchMock).toHaveBeenCalledWith('/api/vehicles', expect.objectContaining({ method: 'GET' }))
    expect(vehicles[0].make).toBe('Audi')
  })

  it('creates a vehicle via POST with a JSON body', async () => {
    const created = { id: 2, year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L', vin: null, notes: null, created_utc: 'x' }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(created, 201))
    vi.stubGlobal('fetch', fetchMock)

    const vehicle = await api.createVehicle({ year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/vehicles')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toMatchObject({ make: 'Subaru' })
    expect(vehicle.id).toBe(2)
  })

  it('uploads a document as multipart to the 202 endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ id: 5, vehicle_id: 1, file_name: 'm.pdf', document_type: 'service_manual', processing_status: 'pending', uploaded_utc: 'x' }, 202),
    )
    vi.stubGlobal('fetch', fetchMock)

    const file = new File(['%PDF'], 'm.pdf', { type: 'application/pdf' })
    const doc = await api.uploadDocument(1, file)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/vehicles/1/documents')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect(doc.processing_status).toBe('pending')
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'Vehicle 999 not found' }, 404)))
    await expect(api.getVehicle(999)).rejects.toBeInstanceOf(ApiError)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- client`
Expected: FAIL — cannot resolve `@/api/client`.

- [ ] **Step 3: Write the types**

Create `frontend/src/api/types.ts`:
```ts
export interface Vehicle {
  id: number
  year: number
  make: string
  model: string
  engine: string
  vin: string | null
  notes: string | null
  created_utc: string
}

export interface VehicleCreate {
  year: number
  make: string
  model: string
  engine: string
  vin?: string | null
  notes?: string | null
}

export interface Job {
  id: number
  vehicle_id: number
  title: string
  description: string | null
  status: string
  created_utc: string
}

export interface JobCreate {
  title: string
  description?: string | null
}

export type ProcessingStatus = 'pending' | 'ready' | 'failed'

export interface Document {
  id: number
  vehicle_id: number
  file_name: string
  document_type: string
  processing_status: ProcessingStatus
  uploaded_utc: string
}

export interface ChatMessage {
  id: number
  job_id: number
  role: string
  content: string
  sources_json: Array<Record<string, unknown>> | null
  created_utc: string
}

export interface ScannerStatus {
  available: boolean
  scanner_reachable: boolean
  detail: string
}

export interface AppConfig {
  openai_key_present: boolean
  obd_mcp_enabled: boolean
  obd_port: string
  web_search_enabled: boolean
  web_search_key_present: boolean
  chat_model: string
  embed_model: string
}
```

- [ ] **Step 4: Write the client**

Create `frontend/src/api/client.ts`:
```ts
import type {
  AppConfig, ChatMessage, Document, Job, JobCreate, ScannerStatus, Vehicle, VehicleCreate,
} from '@/api/types'

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`API ${status}: ${detail}`)
    this.name = 'ApiError'
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { method: 'GET', ...init })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  listVehicles: () => request<Vehicle[]>('/api/vehicles'),
  getVehicle: (id: number) => request<Vehicle>(`/api/vehicles/${id}`),
  createVehicle: (body: VehicleCreate) => request<Vehicle>('/api/vehicles', jsonInit('POST', body)),

  listJobs: (vehicleId: number) => request<Job[]>(`/api/vehicles/${vehicleId}/jobs`),
  getJob: (id: number) => request<Job>(`/api/jobs/${id}`),
  createJob: (vehicleId: number, body: JobCreate) =>
    request<Job>(`/api/vehicles/${vehicleId}/jobs`, jsonInit('POST', body)),

  listDocuments: (vehicleId: number) => request<Document[]>(`/api/vehicles/${vehicleId}/documents`),
  getDocument: (id: number) => request<Document>(`/api/documents/${id}`),
  uploadDocument: (vehicleId: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Document>(`/api/vehicles/${vehicleId}/documents`, { method: 'POST', body: form })
  },

  listMessages: (jobId: number) => request<ChatMessage[]>(`/api/jobs/${jobId}/messages`),
  getScannerStatus: () => request<ScannerStatus>('/api/scanner/status'),
  getConfig: () => request<AppConfig>('/api/config'),
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- client`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
cd .. && git add frontend/src/api && git commit -m "feat(web): typed REST API client and backend types"
```

---

### Task 4: SSE chat stream reader

**Files:**
- Create: `frontend/src/api/chatStream.ts`
- Test: `frontend/src/api/__tests__/chatStream.test.ts`

**Interfaces:**
- Produces:
  - `ChatStreamEvent` — a discriminated union over the six SSE event types.
  - `streamChatMessage(jobId: number, content: string, onEvent: (e: ChatStreamEvent) => void, signal?: AbortSignal) => Promise<void>` — POSTs `{ content }` to `/api/jobs/{jobId}/messages`, reads the `text/event-stream` body, parses each `data: {json}\n\n` frame, and calls `onEvent` per event. Resolves when the stream ends; rejects/`ApiError` on a non-OK response.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/__tests__/chatStream.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamChatMessage, type ChatStreamEvent } from '@/api/chatStream'

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
}

afterEach(() => vi.restoreAllMocks())

describe('streamChatMessage', () => {
  it('parses token, tool, sources, and done frames in order', async () => {
    const frames = [
      'data: {"type":"tool_call","name":"search_manuals","arguments":{"query":"oil"}}\n\n',
      'data: {"type":"tool_result","name":"search_manuals"}\n\n',
      'data: {"type":"token","text":"Use "}\n\n',
      'data: {"type":"token","text":"5W-30."}\n\n',
      'data: {"type":"sources","sources":[{"filename":"m.pdf","page":3}]}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream(frames),
    } as unknown as Response))

    const events: ChatStreamEvent[] = []
    await streamChatMessage(1, 'what oil?', (e) => events.push(e))

    expect(events.map((e) => e.type)).toEqual([
      'tool_call', 'tool_result', 'token', 'token', 'sources', 'done',
    ])
    const tokens = events.filter((e) => e.type === 'token').map((e) => (e as { text: string }).text)
    expect(tokens.join('')).toBe('Use 5W-30.')
  })

  it('handles a frame split across two stream chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream(['data: {"type":"to', 'ken","text":"hi"}\n\n', 'data: {"type":"done"}\n\n']),
    } as unknown as Response))

    const events: ChatStreamEvent[] = []
    await streamChatMessage(1, 'x', (e) => events.push(e))

    expect(events[0]).toEqual({ type: 'token', text: 'hi' })
    expect(events[1]).toEqual({ type: 'done' })
  })

  it('throws on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as Response))
    await expect(streamChatMessage(1, 'x', () => {})).rejects.toBeTruthy()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- chatStream`
Expected: FAIL — cannot resolve `@/api/chatStream`.

- [ ] **Step 3: Write the reader**

Create `frontend/src/api/chatStream.ts`:
```ts
export type ChatStreamEvent =
  | { type: 'token'; text: string }
  | { type: 'tool_call'; name: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; name: string }
  | { type: 'sources'; sources: Array<Record<string, unknown>> }
  | { type: 'done' }
  | { type: 'error'; detail: string }

export async function streamChatMessage(
  jobId: number,
  content: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/jobs/${jobId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const flush = () => {
    let index: number
    while ((index = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      const payload = line.slice('data:'.length).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload) as ChatStreamEvent)
      } catch {
        /* ignore an unparseable frame */
      }
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    flush()
  }
  buffer += decoder.decode()
  flush()
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- chatStream`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd .. && git add frontend/src/api/chatStream.ts frontend/src/api/__tests__/chatStream.test.ts
git commit -m "feat(web): fetch-based SSE reader for the chat token stream"
```

---

### Task 5: Pinia stores (vehicles, scanner, config)

**Files:**
- Create: `frontend/src/stores/vehicles.ts`, `frontend/src/stores/scanner.ts`, `frontend/src/stores/config.ts`
- Test: `frontend/src/stores/__tests__/stores.test.ts`

**Interfaces:**
- Consumes: `api` (Task 3).
- Produces (setup stores):
  - `useVehiclesStore` — state `vehicles: Vehicle[]`, `selectedId: number | null`, `loading`, `error`; getter `selected`; actions `load()`, `create(body)`, `select(id)`.
  - `useScannerStore` — state `status: ScannerStatus | null`, `loading`; action `refresh()`.
  - `useConfigStore` — state `config: AppConfig | null`; action `load()`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/stores/__tests__/stores.test.ts`:
```ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    listVehicles: vi.fn(),
    createVehicle: vi.fn(),
    getScannerStatus: vi.fn(),
    getConfig: vi.fn(),
  },
}))

import { api } from '@/api/client'
import { useVehiclesStore } from '@/stores/vehicles'
import { useScannerStore } from '@/stores/scanner'

beforeEach(() => setActivePinia(createPinia()))

describe('vehicles store', () => {
  it('loads vehicles and exposes the selected one', async () => {
    ;(api.listVehicles as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' },
    ])
    const store = useVehiclesStore()
    await store.load()
    expect(store.vehicles).toHaveLength(1)
    store.select(1)
    expect(store.selected?.make).toBe('Audi')
  })

  it('prepends a created vehicle', async () => {
    ;(api.createVehicle as ReturnType<typeof vi.fn>).mockResolvedValue(
      { id: 2, year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L', vin: null, notes: null, created_utc: 'x' },
    )
    const store = useVehiclesStore()
    const v = await store.create({ year: 2018, make: 'Subaru', model: 'Outback', engine: '2.5L' })
    expect(v.id).toBe(2)
    expect(store.vehicles[0].make).toBe('Subaru')
  })
})

describe('scanner store', () => {
  it('refreshes status', async () => {
    ;(api.getScannerStatus as ReturnType<typeof vi.fn>).mockResolvedValue(
      { available: true, scanner_reachable: false, detail: 'OBD server up; scanner not reachable.' },
    )
    const store = useScannerStore()
    await store.refresh()
    expect(store.status?.available).toBe(true)
    expect(store.status?.scanner_reachable).toBe(false)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- stores`
Expected: FAIL — cannot resolve the store modules.

- [ ] **Step 3: Write the stores**

Create `frontend/src/stores/vehicles.ts`:
```ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { Vehicle, VehicleCreate } from '@/api/types'

export const useVehiclesStore = defineStore('vehicles', () => {
  const vehicles = ref<Vehicle[]>([])
  const selectedId = ref<number | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const selected = computed(() => vehicles.value.find((v) => v.id === selectedId.value) ?? null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      vehicles.value = await api.listVehicles()
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function create(body: VehicleCreate): Promise<Vehicle> {
    const vehicle = await api.createVehicle(body)
    vehicles.value = [vehicle, ...vehicles.value]
    return vehicle
  }

  function select(id: number) {
    selectedId.value = id
  }

  return { vehicles, selectedId, loading, error, selected, load, create, select }
})
```

Create `frontend/src/stores/scanner.ts`:
```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { ScannerStatus } from '@/api/types'

export const useScannerStore = defineStore('scanner', () => {
  const status = ref<ScannerStatus | null>(null)
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      status.value = await api.getScannerStatus()
    } catch {
      status.value = { available: false, scanner_reachable: false, detail: 'Status unavailable.' }
    } finally {
      loading.value = false
    }
  }

  return { status, loading, refresh }
})
```

Create `frontend/src/stores/config.ts`:
```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { AppConfig } from '@/api/types'

export const useConfigStore = defineStore('config', () => {
  const config = ref<AppConfig | null>(null)

  async function load() {
    config.value = await api.getConfig()
  }

  return { config, load }
})
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- stores`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd .. && git add frontend/src/stores && git commit -m "feat(web): Pinia stores for vehicles, scanner, and config"
```

---

### Task 6: App layout + Vehicles view + global scanner badge

> **Use the `frontend-design` skill** for this and the remaining view tasks. The `<script setup>` logic and the Vitest assertions below are the contract; the template markup is a working baseline to elevate visually (honor the `@theme` tokens — `bg-surface`, `text-muted`, `bg-accent`, `rounded-card`, `font-mono`). Do not change behavior or break the tests.

**Files:**
- Create: `frontend/src/components/AppLayout.vue`, `frontend/src/components/ScannerBadge.vue`
- Replace: `frontend/src/views/VehiclesView.vue`, `frontend/src/App.vue`
- Test: `frontend/src/components/__tests__/scannerBadge.test.ts`, `frontend/src/views/__tests__/vehiclesView.test.ts`

**Interfaces:**
- Consumes: `useVehiclesStore`, `useScannerStore` (Task 5), the router.
- Produces: `AppLayout` (header with app name + `<ScannerBadge>` + `<router-view>`); `ScannerBadge` (reads scanner store, shows a colored dot + label); `VehiclesView` (lists vehicles, add-vehicle form, selecting a vehicle routes to its detail). Adds the `vehicle` detail route placeholder.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/__tests__/scannerBadge.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/client', () => ({ api: { getScannerStatus: vi.fn().mockResolvedValue({ available: true, scanner_reachable: true, detail: 'Scanner connected.' }) } }))

import ScannerBadge from '@/components/ScannerBadge.vue'
import { useScannerStore } from '@/stores/scanner'

beforeEach(() => setActivePinia(createPinia()))

describe('ScannerBadge', () => {
  it('shows the scanner detail once refreshed', async () => {
    const store = useScannerStore()
    await store.refresh()
    const wrapper = mount(ScannerBadge)
    expect(wrapper.text()).toContain('Scanner connected.')
  })

  it('shows a disconnected state when unavailable', () => {
    const wrapper = mount(ScannerBadge)
    expect(wrapper.text().toLowerCase()).toContain('not')
  })
})
```

Create `frontend/src/views/__tests__/vehiclesView.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/api/client', () => ({
  api: {
    listVehicles: vi.fn().mockResolvedValue([
      { id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' },
    ]),
    createVehicle: vi.fn(),
    getScannerStatus: vi.fn().mockResolvedValue({ available: false, scanner_reachable: false, detail: 'x' }),
  },
}))

import VehiclesView from '@/views/VehiclesView.vue'

function routerStub() {
  return createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: VehiclesView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
}

beforeEach(() => setActivePinia(createPinia()))

describe('VehiclesView', () => {
  it('renders the vehicles from the store', async () => {
    const router = routerStub()
    const wrapper = mount(VehiclesView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Audi')
    expect(wrapper.text()).toContain('A8')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- scannerBadge vehiclesView`
Expected: FAIL — components not yet implemented.

- [ ] **Step 3: Implement `ScannerBadge.vue`**

Create `frontend/src/components/ScannerBadge.vue`:
```vue
<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useScannerStore } from '@/stores/scanner'

const scanner = useScannerStore()
onMounted(() => scanner.refresh())

const tone = computed(() => {
  const s = scanner.status
  if (s?.scanner_reachable) return 'bg-success'
  if (s?.available) return 'bg-warning'
  return 'bg-danger'
})
const label = computed(() => scanner.status?.detail ?? 'Scanner not connected.')
</script>

<template>
  <div class="flex items-center gap-2 text-sm text-muted">
    <span class="inline-block h-2.5 w-2.5 rounded-full" :class="tone" />
    <span>{{ label }}</span>
  </div>
</template>
```

- [ ] **Step 4: Implement `AppLayout.vue`**

Create `frontend/src/components/AppLayout.vue`:
```vue
<script setup lang="ts">
import ScannerBadge from '@/components/ScannerBadge.vue'
</script>

<template>
  <div class="min-h-full">
    <header class="flex items-center justify-between border-b border-border bg-surface px-6 py-3">
      <RouterLink to="/" class="text-lg font-semibold text-accent">Mechanic Sidekick</RouterLink>
      <div class="flex items-center gap-4">
        <ScannerBadge />
        <RouterLink to="/settings" class="text-sm text-muted hover:text-text">Settings</RouterLink>
      </div>
    </header>
    <router-view />
  </div>
</template>
```

Replace `frontend/src/App.vue`:
```vue
<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
</script>

<template>
  <AppLayout />
</template>
```

- [ ] **Step 5: Implement `VehiclesView.vue`**

Replace `frontend/src/views/VehiclesView.vue`:
```vue
<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useVehiclesStore } from '@/stores/vehicles'

const store = useVehiclesStore()
const router = useRouter()
const form = reactive({ year: new Date().getFullYear(), make: '', model: '', engine: '' })

onMounted(() => store.load())

async function add() {
  if (!form.make || !form.model) return
  const vehicle = await store.create({ ...form })
  form.make = ''; form.model = ''; form.engine = ''
  router.push({ name: 'vehicle', params: { id: vehicle.id } })
}

function open(id: number) {
  store.select(id)
  router.push({ name: 'vehicle', params: { id } })
}
</script>

<template>
  <main class="mx-auto max-w-4xl p-6">
    <h1 class="mb-4 text-xl font-semibold">Vehicles</h1>

    <form class="mb-6 grid grid-cols-2 gap-3 rounded-card bg-surface p-4 sm:grid-cols-5" @submit.prevent="add">
      <input v-model.number="form.year" type="number" placeholder="Year" class="rounded bg-surface-2 px-3 py-2" />
      <input v-model="form.make" placeholder="Make" class="rounded bg-surface-2 px-3 py-2" />
      <input v-model="form.model" placeholder="Model" class="rounded bg-surface-2 px-3 py-2" />
      <input v-model="form.engine" placeholder="Engine" class="rounded bg-surface-2 px-3 py-2" />
      <button class="rounded bg-accent px-3 py-2 font-medium text-bg">Add</button>
    </form>

    <p v-if="store.loading" class="text-muted">Loading…</p>
    <ul class="space-y-2">
      <li v-for="v in store.vehicles" :key="v.id">
        <button class="w-full rounded-card bg-surface px-4 py-3 text-left hover:bg-surface-2" @click="open(v.id)">
          <span class="font-medium">{{ v.year }} {{ v.make }} {{ v.model }}</span>
          <span class="ml-2 font-mono text-sm text-muted">{{ v.engine }}</span>
        </button>
      </li>
    </ul>
  </main>
</template>
```

- [ ] **Step 6: Add the detail route**

In `frontend/src/router/index.ts`, add a route (the view is built in Task 7; a lazy import is fine even before the file exists for the router definition, but create the route entry now):
```ts
    { path: '/vehicles/:id', name: 'vehicle', component: () => import('@/views/VehicleDetailView.vue') },
```
(Create a minimal placeholder `frontend/src/views/VehicleDetailView.vue` with `<template><div /></template>` so the build resolves; Task 7 replaces it.)

- [ ] **Step 7: Run the tests + build**

Run (from `frontend/`): `npm test`
Expected: PASS (all prior + scannerBadge + vehiclesView).
Run: `npm run build`
Expected: type-check + build succeed.

- [ ] **Step 8: Commit**

```bash
cd .. && git add frontend/src && git commit -m "feat(web): app layout, scanner badge, and vehicles view"
```

---

### Task 7: Vehicle detail view (documents upload + status polling, jobs)

> **Use the `frontend-design` skill.** Logic + tests are the contract; elevate the markup.

**Files:**
- Replace: `frontend/src/views/VehicleDetailView.vue`
- Create: `frontend/src/components/DocumentList.vue`, `frontend/src/components/JobList.vue`
- Test: `frontend/src/views/__tests__/vehicleDetailView.test.ts`

**Interfaces:**
- Consumes: `api` (Task 3), the router (`vehicle` route param `id`, navigation to the `chat` route).
- Produces: `VehicleDetailView` loads the vehicle, its documents, and its jobs. `DocumentList` shows each document with its `processing_status`, supports drag-drop / picker upload (`api.uploadDocument`), and polls `api.getDocument(id)` for any `pending` document until it becomes `ready`/`failed`. `JobList` lists jobs and creates one (then routes to `/jobs/{id}/chat`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/views/__tests__/vehicleDetailView.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/api/client', () => ({
  api: {
    getVehicle: vi.fn().mockResolvedValue({ id: 1, year: 2004, make: 'Audi', model: 'A8', engine: '4.2L', vin: null, notes: null, created_utc: 'x' }),
    listDocuments: vi.fn().mockResolvedValue([
      { id: 7, vehicle_id: 1, file_name: 'manual.pdf', document_type: 'service_manual', processing_status: 'ready', uploaded_utc: 'x' },
    ]),
    listJobs: vi.fn().mockResolvedValue([
      { id: 3, vehicle_id: 1, title: 'Oil leak', description: null, status: 'open', created_utc: 'x' },
    ]),
    createJob: vi.fn(),
    getDocument: vi.fn(),
    uploadDocument: vi.fn(),
  },
}))

import VehicleDetailView from '@/views/VehicleDetailView.vue'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id', name: 'vehicle', component: VehicleDetailView },
    { path: '/jobs/:id/chat', name: 'chat', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}`)
  return router.isReady().then(() => mount(VehicleDetailView, { global: { plugins: [router] } }))
}

beforeEach(() => setActivePinia(createPinia()))

describe('VehicleDetailView', () => {
  it('shows the vehicle, its documents (with status), and its jobs', async () => {
    const wrapper = await mountAt('1')
    await flushPromises()
    expect(wrapper.text()).toContain('Audi')
    expect(wrapper.text()).toContain('manual.pdf')
    expect(wrapper.text().toLowerCase()).toContain('ready')
    expect(wrapper.text()).toContain('Oil leak')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- vehicleDetailView`
Expected: FAIL — view/components not implemented.

- [ ] **Step 3: Implement `DocumentList.vue`**

Create `frontend/src/components/DocumentList.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/api/client'
import type { Document } from '@/api/types'

const props = defineProps<{ vehicleId: number }>()
const documents = ref<Document[]>([])
const uploading = ref(false)
const timers = new Map<number, ReturnType<typeof setInterval>>()

async function load() {
  documents.value = await api.listDocuments(props.vehicleId)
  documents.value.filter((d) => d.processing_status === 'pending').forEach(poll)
}

function poll(doc: Document) {
  if (timers.has(doc.id)) return
  const timer = setInterval(async () => {
    const fresh = await api.getDocument(doc.id)
    const i = documents.value.findIndex((d) => d.id === fresh.id)
    if (i !== -1) documents.value[i] = fresh
    if (fresh.processing_status !== 'pending') {
      clearInterval(timer)
      timers.delete(doc.id)
    }
  }, 2000)
  timers.set(doc.id, timer)
}

async function upload(files: FileList | null) {
  if (!files?.length) return
  uploading.value = true
  try {
    for (const file of Array.from(files)) {
      const doc = await api.uploadDocument(props.vehicleId, file)
      documents.value = [doc, ...documents.value]
      poll(doc)
    }
  } finally {
    uploading.value = false
  }
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  upload(e.dataTransfer?.files ?? null)
}

const tone: Record<string, string> = { ready: 'text-success', failed: 'text-danger', pending: 'text-warning' }

onMounted(load)
onUnmounted(() => timers.forEach((t) => clearInterval(t)))
</script>

<template>
  <section>
    <h2 class="mb-2 font-medium">Documents</h2>
    <div
      class="mb-3 rounded-card border border-dashed border-border bg-surface p-6 text-center text-muted"
      @dragover.prevent
      @drop="onDrop"
    >
      <p>Drag a PDF here, or
        <label class="cursor-pointer text-accent">browse
          <input type="file" accept="application/pdf" class="hidden" multiple
                 @change="upload(($event.target as HTMLInputElement).files)" />
        </label>
      </p>
      <p v-if="uploading" class="mt-1 text-sm">Uploading…</p>
    </div>
    <ul class="space-y-1">
      <li v-for="d in documents" :key="d.id" class="flex items-center justify-between rounded bg-surface px-3 py-2">
        <span class="font-mono text-sm">{{ d.file_name }}</span>
        <span class="text-sm" :class="tone[d.processing_status]">{{ d.processing_status }}</span>
      </li>
    </ul>
  </section>
</template>
```

- [ ] **Step 4: Implement `JobList.vue`**

Create `frontend/src/components/JobList.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Job } from '@/api/types'

const props = defineProps<{ vehicleId: number }>()
const router = useRouter()
const jobs = ref<Job[]>([])
const title = ref('')

async function load() {
  jobs.value = await api.listJobs(props.vehicleId)
}

async function add() {
  if (!title.value.trim()) return
  const job = await api.createJob(props.vehicleId, { title: title.value.trim() })
  jobs.value = [job, ...jobs.value]
  title.value = ''
  router.push({ name: 'chat', params: { id: job.id } })
}

onMounted(load)
</script>

<template>
  <section>
    <h2 class="mb-2 font-medium">Jobs</h2>
    <form class="mb-3 flex gap-2" @submit.prevent="add">
      <input v-model="title" placeholder="New job (e.g. Oil leak)" class="flex-1 rounded bg-surface-2 px-3 py-2" />
      <button class="rounded bg-accent px-3 py-2 font-medium text-bg">Start</button>
    </form>
    <ul class="space-y-1">
      <li v-for="j in jobs" :key="j.id">
        <RouterLink :to="{ name: 'chat', params: { id: j.id } }"
                    class="block rounded bg-surface px-3 py-2 hover:bg-surface-2">
          {{ j.title }} <span class="ml-2 text-sm text-muted">{{ j.status }}</span>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
```

- [ ] **Step 5: Implement `VehicleDetailView.vue`**

Replace `frontend/src/views/VehicleDetailView.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { Vehicle } from '@/api/types'
import DocumentList from '@/components/DocumentList.vue'
import JobList from '@/components/JobList.vue'

const route = useRoute()
const vehicleId = Number(route.params.id)
const vehicle = ref<Vehicle | null>(null)

onMounted(async () => {
  vehicle.value = await api.getVehicle(vehicleId)
})
</script>

<template>
  <main class="mx-auto max-w-4xl p-6">
    <RouterLink to="/" class="text-sm text-muted hover:text-text">← Vehicles</RouterLink>
    <h1 v-if="vehicle" class="my-3 text-xl font-semibold">
      {{ vehicle.year }} {{ vehicle.make }} {{ vehicle.model }}
      <span class="ml-2 font-mono text-base text-muted">{{ vehicle.engine }}</span>
    </h1>
    <div class="grid gap-6 md:grid-cols-2">
      <DocumentList :vehicle-id="vehicleId" />
      <JobList :vehicle-id="vehicleId" />
    </div>
  </main>
</template>
```

- [ ] **Step 6: Run the tests + build**

Run (from `frontend/`): `npm test`
Expected: PASS.
Run: `npm run build`
Expected: succeeds.

- [ ] **Step 7: Commit**

```bash
cd .. && git add frontend/src && git commit -m "feat(web): vehicle detail with document upload/polling and jobs"
```

---

### Task 8: Chat view (streaming, tool chips, sources, history)

> **Use the `frontend-design` skill.** This is the centerpiece view — make it feel alive. Logic + tests are the contract.

**Files:**
- Replace/Create: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/components/ToolChip.vue`, `frontend/src/components/MessageBubble.vue`
- Modify: `frontend/src/router/index.ts` (add the `chat` route)
- Test: `frontend/src/views/__tests__/chatView.test.ts`

**Interfaces:**
- Consumes: `api.listMessages` (history), `streamChatMessage` (Task 4), the `chat` route param `id`.
- Produces: `ChatView` loads message history, renders a transcript, sends a message that streams the assistant reply token-by-token, shows a tool-activity row (`ToolChip` per `tool_call`: 🔧 OBD / 📖 search_manuals / 🔎 web_search), and renders source citations from the `sources` event / persisted `sources_json`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/views/__tests__/chatView.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import type { ChatStreamEvent } from '@/api/chatStream'

vi.mock('@/api/client', () => ({
  api: { listMessages: vi.fn().mockResolvedValue([]) },
}))
vi.mock('@/api/chatStream', () => ({
  streamChatMessage: vi.fn(async (_jobId: number, _content: string, onEvent: (e: ChatStreamEvent) => void) => {
    onEvent({ type: 'tool_call', name: 'search_manuals', arguments: { query: 'oil' } })
    onEvent({ type: 'tool_result', name: 'search_manuals' })
    onEvent({ type: 'token', text: 'Use ' })
    onEvent({ type: 'token', text: '5W-30.' })
    onEvent({ type: 'sources', sources: [{ filename: 'm.pdf', page: 3 }] })
    onEvent({ type: 'done' })
  }),
}))

import ChatView from '@/views/ChatView.vue'

function mountChat() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/jobs/:id/chat', name: 'chat', component: ChatView },
  ] })
  router.push('/jobs/1/chat')
  return router.isReady().then(() => mount(ChatView, { global: { plugins: [router] } }))
}

beforeEach(() => setActivePinia(createPinia()))

describe('ChatView', () => {
  it('streams an assistant answer with tool activity and sources', async () => {
    const wrapper = await mountChat()
    await flushPromises()

    await wrapper.find('textarea').setValue('what oil?')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Use 5W-30.')          // streamed tokens assembled
    expect(wrapper.text()).toContain('search_manuals')       // tool chip
    expect(wrapper.text()).toContain('m.pdf')                // source citation
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- chatView`
Expected: FAIL — view not implemented.

- [ ] **Step 3: Implement `ToolChip.vue`**

Create `frontend/src/components/ToolChip.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ name: string }>()
const icon = computed(() => {
  if (props.name === 'search_manuals') return '📖'
  if (props.name === 'web_search') return '🔎'
  return '🔧'
})
</script>

<template>
  <span class="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 font-mono text-xs text-muted">
    {{ icon }} {{ name }}
  </span>
</template>
```

- [ ] **Step 4: Implement `MessageBubble.vue`**

Create `frontend/src/components/MessageBubble.vue`:
```vue
<script setup lang="ts">
defineProps<{ role: string; content: string; sources?: Array<Record<string, unknown>> | null }>()
</script>

<template>
  <div class="mb-3" :class="role === 'user' ? 'text-right' : 'text-left'">
    <div
      class="inline-block max-w-[80%] whitespace-pre-wrap rounded-card px-4 py-2 text-left"
      :class="role === 'user' ? 'bg-accent text-bg' : 'bg-surface'"
    >
      {{ content }}
      <ul v-if="sources?.length" class="mt-2 border-t border-border pt-2 text-xs text-muted">
        <li v-for="(s, i) in sources" :key="i" class="font-mono">
          {{ (s.filename as string) ?? (s.url as string) }}<template v-if="s.page"> · p.{{ s.page }}</template>
        </li>
      </ul>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Implement `ChatView.vue`**

Create `frontend/src/views/ChatView.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import { streamChatMessage, type ChatStreamEvent } from '@/api/chatStream'
import type { ChatMessage } from '@/api/types'
import ToolChip from '@/components/ToolChip.vue'
import MessageBubble from '@/components/MessageBubble.vue'

interface Turn {
  role: string
  content: string
  sources: Array<Record<string, unknown>> | null
}

const route = useRoute()
const jobId = Number(route.params.id)
const turns = ref<Turn[]>([])
const draft = ref('')
const streaming = ref(false)
const activeTools = ref<string[]>([])

onMounted(async () => {
  const history: ChatMessage[] = await api.listMessages(jobId)
  turns.value = history.map((m) => ({ role: m.role, content: m.content, sources: m.sources_json }))
})

async function send() {
  const content = draft.value.trim()
  if (!content || streaming.value) return
  draft.value = ''
  turns.value.push({ role: 'user', content, sources: null })
  const assistant: Turn = { role: 'assistant', content: '', sources: null }
  turns.value.push(assistant)
  streaming.value = true
  activeTools.value = []

  try {
    await streamChatMessage(jobId, content, (e: ChatStreamEvent) => {
      if (e.type === 'token') assistant.content += e.text
      else if (e.type === 'tool_call') activeTools.value.push(e.name)
      else if (e.type === 'sources') assistant.sources = e.sources
      else if (e.type === 'error') assistant.content += `\n[error] ${e.detail}`
    })
  } catch (err) {
    assistant.content += `\n[connection error] ${(err as Error).message}`
  } finally {
    streaming.value = false
  }
}
</script>

<template>
  <main class="mx-auto flex h-[calc(100vh-3.25rem)] max-w-3xl flex-col p-4">
    <div class="flex-1 overflow-y-auto">
      <MessageBubble v-for="(t, i) in turns" :key="i" :role="t.role" :content="t.content" :sources="t.sources" />
      <div v-if="activeTools.length" class="mb-3 flex flex-wrap gap-1">
        <ToolChip v-for="(name, i) in activeTools" :key="i" :name="name" />
      </div>
    </div>

    <form class="mt-2 flex items-end gap-2" @submit.prevent="send">
      <textarea
        v-model="draft" rows="2" placeholder="Ask about this vehicle…"
        class="flex-1 resize-none rounded-card bg-surface px-3 py-2"
        @keydown.enter.exact.prevent="send"
      />
      <button class="rounded-card bg-accent px-4 py-2 font-medium text-bg disabled:opacity-50" :disabled="streaming">
        Send
      </button>
    </form>
  </main>
</template>
```

- [ ] **Step 6: Add the chat route**

In `frontend/src/router/index.ts`, add:
```ts
    { path: '/jobs/:id/chat', name: 'chat', component: () => import('@/views/ChatView.vue') },
```

- [ ] **Step 7: Run the tests + build**

Run (from `frontend/`): `npm test`
Expected: PASS (chatView + all prior).
Run: `npm run build`
Expected: succeeds.

- [ ] **Step 8: Commit**

```bash
cd .. && git add frontend/src && git commit -m "feat(web): streaming chat view with tool chips and source citations"
```

---

### Task 9: Settings view + route finalization

> **Use the `frontend-design` skill.** Logic + test are the contract.

**Files:**
- Create: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/router/index.ts` (add the `settings` route)
- Test: `frontend/src/views/__tests__/settingsView.test.ts`

**Interfaces:**
- Consumes: `useConfigStore` (Task 5), `useScannerStore`.
- Produces: `SettingsView` showing whether the OpenAI key is present, the chat/embed models, web-search status, `obd_mcp_enabled`, the `OBD_PORT`, and the live scanner status — all read-only (no secrets shown).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/views/__tests__/settingsView.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/client', () => ({
  api: {
    getConfig: vi.fn().mockResolvedValue({
      openai_key_present: true, obd_mcp_enabled: false, obd_port: 'socket://localhost:35000',
      web_search_enabled: true, web_search_key_present: false,
      chat_model: 'gpt-4.1-mini', embed_model: 'text-embedding-3-small',
    }),
    getScannerStatus: vi.fn().mockResolvedValue({ available: false, scanner_reachable: false, detail: 'OBD tool server not running.' }),
  },
}))

import SettingsView from '@/views/SettingsView.vue'

beforeEach(() => setActivePinia(createPinia()))

describe('SettingsView', () => {
  it('renders config status without leaking secrets', async () => {
    const wrapper = mount(SettingsView)
    await flushPromises()
    expect(wrapper.text()).toContain('gpt-4.1-mini')
    expect(wrapper.text()).toContain('socket://localhost:35000')
    expect(wrapper.text().toLowerCase()).toContain('openai')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- settingsView`
Expected: FAIL — view not implemented.

- [ ] **Step 3: Implement `SettingsView.vue`**

Create `frontend/src/views/SettingsView.vue`:
```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useScannerStore } from '@/stores/scanner'

const config = useConfigStore()
const scanner = useScannerStore()

onMounted(() => {
  config.load()
  scanner.refresh()
})

function yn(v: boolean | undefined) {
  return v ? 'yes' : 'no'
}
</script>

<template>
  <main class="mx-auto max-w-2xl p-6">
    <h1 class="mb-4 text-xl font-semibold">Settings</h1>
    <dl v-if="config.config" class="grid grid-cols-2 gap-y-2 rounded-card bg-surface p-4 text-sm">
      <dt class="text-muted">OpenAI key present</dt><dd>{{ yn(config.config.openai_key_present) }}</dd>
      <dt class="text-muted">Chat model</dt><dd class="font-mono">{{ config.config.chat_model }}</dd>
      <dt class="text-muted">Embedding model</dt><dd class="font-mono">{{ config.config.embed_model }}</dd>
      <dt class="text-muted">Web search enabled</dt><dd>{{ yn(config.config.web_search_enabled) }}</dd>
      <dt class="text-muted">Web search key present</dt><dd>{{ yn(config.config.web_search_key_present) }}</dd>
      <dt class="text-muted">OBD tools enabled</dt><dd>{{ yn(config.config.obd_mcp_enabled) }}</dd>
      <dt class="text-muted">OBD port</dt><dd class="font-mono">{{ config.config.obd_port }}</dd>
      <dt class="text-muted">Scanner</dt><dd>{{ scanner.status?.detail ?? '…' }}</dd>
    </dl>
  </main>
</template>
```

- [ ] **Step 4: Add the settings route**

In `frontend/src/router/index.ts`, add:
```ts
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
```

- [ ] **Step 5: Run the tests + build**

Run (from `frontend/`): `npm test`
Expected: PASS (settingsView + all prior).
Run: `npm run build`
Expected: succeeds; `frontend/dist` is produced.

- [ ] **Step 6: Commit**

```bash
cd .. && git add frontend/src && git commit -m "feat(web): settings view with read-only config and scanner status"
```

---

## Manual smoke test (after all tasks)

```bash
# Terminal 1 — backend (Phase 3 features optional):
uv run mechanic-sidekick-api          # http://127.0.0.1:8000

# Terminal 2 — frontend dev server:
cd frontend && npm run dev            # http://localhost:5173 (proxies /api → :8000)
```
In the browser at `:5173`: add a vehicle → open it → drag-drop a PDF and watch `processing_status` go `pending → ready` → start a job → ask a question and watch tokens stream with tool chips and citations → open Settings to see config + scanner status.

Single-port production check:
```bash
cd frontend && npm run build          # emits frontend/dist
cd .. && uv run mechanic-sidekick-api # now serves the SPA at http://127.0.0.1:8000
```
Open `http://127.0.0.1:8000` and exercise the same flow (deep links like `/jobs/1/chat` resolve via the `html=True` SPA fallback).

## Self-review

**Spec coverage (design spec §1.10 frontend, §1.11 API surface, §1.12 testing, D1):**
- Vite + Vue 3 SPA, Pinia, fetch-based SSE reader → Tasks 2–4. ✔
- Vehicles list/add/select + global scanner badge → Task 6. ✔
- Vehicle detail: documents (drag-drop upload + live `processing_status`) + jobs (list/create) → Task 7. ✔
- Chat: streaming answers, tool-activity chips (🔧/📖/🔎), source citations, input → Task 8. ✔
- Settings: OpenAI key present?, obd-mcp status, OBD_PORT → Task 9 (+ the `GET /api/config` endpoint, Task 1). ✔
- Dev proxy + single-port prod via `StaticFiles` → Task 2 (proxy) + existing `main.py` mount (no change needed). ✔
- Vitest component tests for chat rendering/streaming; Playwright deferred → every view task has a Vitest test; no e2e. ✔

**Placeholder scan:** No TBD/TODO. View tasks carry complete, working baseline markup plus exact behavior tests; the `frontend-design` note authorizes visual elevation, not missing code. ✔

**Type/interface consistency:**
- `api.*` method names/signatures match between Task 3 (def) and their callers in Tasks 5–9. ✔
- `ChatStreamEvent` union and `streamChatMessage(jobId, content, onEvent, signal?)` match between Task 4 (def), the Task 8 view, and the Task 8 test mock. ✔
- Store names/shapes (`useVehiclesStore.{vehicles,selected,load,create,select}`, `useScannerStore.{status,refresh}`, `useConfigStore.{config,load}`) match between Task 5 (def) and Tasks 6/9 (use). ✔
- `ConfigOut` fields (Task 1) match the `AppConfig` TS interface (Task 3) and the Settings view/test (Task 9). ✔
- Route names `vehicles` / `vehicle` / `chat` / `settings` are introduced and referenced consistently across Tasks 2, 6, 7, 8, 9. ✔
- `sources_json` consumed as a parsed array (matches the backend `field_validator`) in `MessageBubble`/`ChatView`. ✔
```
