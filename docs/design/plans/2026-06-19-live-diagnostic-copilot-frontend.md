# Live Diagnostic Copilot — Frontend Implementation Plan (Phase 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Vue diagnostic-session UI for Phase 3 — a `/vehicles/:id/diagnostic` view that streams the guided health test (live vitals + focus chart on the left; step tracker, LLM commentary, and the generated health report on the right), and renders past-report citations inside chat.

**Architecture:** A new `streamDiagnostic` POST-SSE reader (mirrors `streamChatMessage`), a `useDiagnosticSession` composable (mirrors `useLiveSession`, reusing the rolling per-PID buffer logic), a `DiagnosticSessionView` that reuses `LiveFocusChart`, and small presentational components (`DiagnosticStep`, `CommentaryItem`, `HealthReport`). One existing component (`MessageBubble`) gains a diagnostic-source line. Backend endpoints (from the backend plan) are assumed live.

**Tech Stack:** Vue 3 `<script setup>` + TypeScript (strict), Vite, Tailwind v4 (existing tokens: `text-text`, `bg-surface`, `border-border`, `text-accent`, `text-muted`, `text-success`, `text-warning`, `text-danger`), Pinia, vue-router (lazy routes), ECharts via `vue-echarts` (mocked in tests), Vitest + jsdom + `@vue/test-utils`.

## Global Constraints

- **Reuse, don't rebuild.** Reuse `LiveFocusChart.vue` for charts and copy the rolling-window buffer logic (`WINDOW = 120`, push `[t, value]`, splice) from `useLiveSession`. Do NOT add a new chart library or a second ECharts registration.
- **SSE readers follow the existing frame-split pattern** exactly (`buffer.indexOf('\n\n')`, take `data:` line, `JSON.parse`, ignore unparseable). Accept and respect an `AbortSignal`.
- **Lazy routes only:** `component: () => import('@/views/...')` — never a top-level import in the router.
- **Strict TypeScript, no `any`.** Define a `DiagnosticStreamEvent` discriminated union for every event type. Run `vue-tsc -b` (via `npm run build`) clean.
- **Tests mock `vue-echarts`** with the stub `{ default: { name: 'VChart', props: ['option','initOptions','autoresize','manualUpdate'], template: '<div class="v-chart-stub" />' } }` (jsdom can't render a real chart).
- **Tailwind tokens only** for styling (match the "garage console" look of `LiveView.vue`); no arbitrary hex values.
- **No AI/tool attribution** anywhere in code or comments.
- **Backend event contract (consumed verbatim):** `session {diagnostic_session_id, live_session_id, protocol:[{id,label,instruction}], vin_mismatch?}` · `sample {seq,t,values}` · `step {index,total,id,label,instruction,state,adhoc}` · `commentary {text,t}` · `anomaly {system,severity,pid,detail}` · `report {overall_status,summary,findings:[{system,severity,observation,interpretation,recommendation,evidence}]}` · `done` · `error {detail}`.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/api/diagnosticStream.ts` | `streamDiagnostic` POST-SSE reader + `DiagnosticStreamEvent` union. |
| `frontend/src/api/types.ts` (modify) | `DiagnosticFinding`, `DiagnosticReport`, `DiagnosticReportSummary`, `DiagnosticSessionDetail`. |
| `frontend/src/api/client.ts` (modify) | `listDiagnosticReports`, `getDiagnosticSession`. |
| `frontend/src/composables/useDiagnosticSession.ts` | Reactive session state machine over `streamDiagnostic`. |
| `frontend/src/components/DiagnosticStep.vue` | One step row (index, label, instruction, state icon). |
| `frontend/src/components/CommentaryItem.vue` | One commentary timeline entry. |
| `frontend/src/components/HealthReport.vue` | Overall badge + per-system finding cards with citations. |
| `frontend/src/views/DiagnosticSessionView.vue` | Two-pane diagnostic view; reuses `LiveFocusChart`. |
| `frontend/src/router/index.ts` (modify) | `/vehicles/:id/diagnostic` lazy route. |
| `frontend/src/views/VehicleDetailView.vue` + `LiveView.vue` (modify) | "Run health check" entry link. |
| `frontend/src/components/MessageBubble.vue` (modify) | Render a `{kind:'diagnostic'}` source line. |

---

### Task 1: `diagnosticStream` SSE reader + types + client methods

**Files:**
- Create: `frontend/src/api/diagnosticStream.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/__tests__/diagnosticStream.test.ts`, `frontend/src/api/__tests__/diagnosticClient.test.ts`

**Interfaces:**
- Produces:
  - `DiagnosticStreamEvent` union (see code).
  - `streamDiagnostic(vehicleId: number, protocol: string, onEvent: (e: DiagnosticStreamEvent) => void, signal?: AbortSignal): Promise<void>`.
  - Types `DiagnosticFinding`, `DiagnosticReport`, `DiagnosticReportSummary`, `DiagnosticSessionDetail`.
  - `api.listDiagnosticReports(vehicleId)`, `api.getDiagnosticSession(id)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/api/__tests__/diagnosticStream.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamDiagnostic, type DiagnosticStreamEvent } from '@/api/diagnosticStream'

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

describe('streamDiagnostic', () => {
  it('parses session, step, commentary, report, done in order', async () => {
    const frames = [
      'data: {"type":"session","diagnostic_session_id":3,"live_session_id":9,"protocol":[{"id":"idle_baseline","label":"Idle","instruction":"idle"}]}\n\n',
      'data: {"type":"step","index":0,"total":1,"id":"idle_baseline","label":"Idle","instruction":"idle","state":"active","adhoc":false}\n\n',
      'data: {"type":"commentary","text":"Idle looks steady.","t":1000}\n\n',
      'data: {"type":"report","overall_status":"fair","summary":"ok","findings":[]}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body: sseStream(frames),
    } as unknown as Response))

    const events: DiagnosticStreamEvent[] = []
    await streamDiagnostic(1, 'default', (e) => events.push(e))
    expect(events.map((e) => e.type)).toEqual(['session', 'step', 'commentary', 'report', 'done'])
  })

  it('handles a frame split across two chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream(['data: {"type":"comm', 'entary","text":"hi","t":0}\n\n', 'data: {"type":"done"}\n\n']),
    } as unknown as Response))
    const events: DiagnosticStreamEvent[] = []
    await streamDiagnostic(1, 'default', (e) => events.push(e))
    expect(events[0]).toEqual({ type: 'commentary', text: 'hi', t: 0 })
    expect(events[1]).toEqual({ type: 'done' })
  })

  it('throws on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as Response))
    await expect(streamDiagnostic(1, 'default', () => {})).rejects.toBeTruthy()
  })
})
```

`frontend/src/api/__tests__/diagnosticClient.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { api } from '@/api/client'

afterEach(() => vi.restoreAllMocks())

describe('diagnostic client methods', () => {
  it('lists reports and gets one session', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => [{ id: 3, overall_status: 'fair' }] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ session: { id: 3 }, report: { summary: 'ok' } }) } as Response)
    vi.stubGlobal('fetch', fetchMock)

    const list = await api.listDiagnosticReports(1)
    expect(list[0].overall_status).toBe('fair')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/vehicles/1/diagnostic-reports')

    const detail = await api.getDiagnosticSession(3)
    expect(detail.report?.summary).toBe('ok')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/diagnostic-sessions/3')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/__tests__/diagnosticStream.test.ts src/api/__tests__/diagnosticClient.test.ts`
Expected: FAIL — cannot resolve `@/api/diagnosticStream`; `api.listDiagnosticReports is not a function`.

- [ ] **Step 3: Add the types**

Append to `frontend/src/api/types.ts`:
```ts
export interface DiagnosticFinding {
  system: string
  severity: 'good' | 'warn' | 'fail'
  observation: string
  interpretation: string
  recommendation: string
  evidence: Record<string, unknown>
}

export interface DiagnosticReport {
  overall_status: 'good' | 'fair' | 'poor'
  summary: string
  findings: DiagnosticFinding[]
}

export interface DiagnosticReportSummary {
  id: number
  status: string
  protocol_name: string
  started_utc: string
  ended_utc: string | null
  overall_status: 'good' | 'fair' | 'poor' | null
  summary: string | null
}

export interface DiagnosticSessionDetail {
  session: {
    id: number
    vehicle_id: number
    status: string
    protocol_name: string
    overall_status: string | null
    started_utc: string
    ended_utc: string | null
  }
  report: DiagnosticReport | null
}
```

- [ ] **Step 4: Add the SSE reader**

`frontend/src/api/diagnosticStream.ts`:
```ts
import type { LiveValue } from '@/api/types'

export type DiagnosticStreamEvent =
  | { type: 'session'; diagnostic_session_id: number; live_session_id: number;
      protocol: { id: string; label: string; instruction: string }[]; vin_mismatch?: string }
  | { type: 'sample'; seq: number; t: number; values: Record<string, LiveValue | null> }
  | { type: 'step'; index: number; total: number; id: string; label: string;
      instruction: string; state: 'active' | 'done' | 'skipped'; adhoc: boolean }
  | { type: 'commentary'; text: string; t: number }
  | { type: 'anomaly'; system: string; severity: string; pid: string; detail: string }
  | { type: 'report'; overall_status: 'good' | 'fair' | 'poor'; summary: string;
      findings: import('@/api/types').DiagnosticFinding[] }
  | { type: 'done' }
  | { type: 'error'; detail: string }

export async function streamDiagnostic(
  vehicleId: number,
  protocol: string,
  onEvent: (event: DiagnosticStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/vehicles/${vehicleId}/diagnostic?protocol=${protocol}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Diagnostic request failed: ${response.status}`)
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
        onEvent(JSON.parse(payload) as DiagnosticStreamEvent)
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

- [ ] **Step 5: Add the client methods**

In `frontend/src/api/client.ts`, extend the type import to include the new types:
```ts
import type {
  AppConfig, ChatMessage, DiagnosticReportSummary, DiagnosticSessionDetail, Document, Job,
  JobCreate, LiveSessionDetail, LiveSessionSummary, ScannerStatus, SupportedPids, Vehicle,
  VehicleCreate,
} from '@/api/types'
```
And add two methods inside the `api` object (after `getLiveSession`):
```ts
  listDiagnosticReports: (vehicleId: number) =>
    request<DiagnosticReportSummary[]>(`/api/vehicles/${vehicleId}/diagnostic-reports`),
  getDiagnosticSession: (sessionId: number) =>
    request<DiagnosticSessionDetail>(`/api/diagnostic-sessions/${sessionId}`),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/__tests__/diagnosticStream.test.ts src/api/__tests__/diagnosticClient.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/diagnosticStream.ts frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/__tests__/diagnosticStream.test.ts frontend/src/api/__tests__/diagnosticClient.test.ts
git commit -m "feat(diagnostic-ui): SSE reader, types, and client methods"
```

---

### Task 2: `useDiagnosticSession` composable

**Files:**
- Create: `frontend/src/composables/useDiagnosticSession.ts`
- Test: `frontend/src/composables/__tests__/useDiagnosticSession.test.ts`

**Interfaces:**
- Consumes: `streamDiagnostic`; `DiagnosticStreamEvent`; `LiveValue`, `DiagnosticReport`.
- Produces: `useDiagnosticSession(vehicleId: number)` returning `{ status, detail, steps, currentIndex, commentary, anomalies, report, latest, series, start, stop }`:
  - `status: Ref<'idle'|'connecting'|'running'|'complete'|'error'>`.
  - `steps: Ref<StepView[]>` where `StepView = { id; label; instruction; state: 'pending'|'active'|'done'|'skipped'; adhoc }`.
  - `currentIndex: Ref<number>`.
  - `commentary: Ref<{ text: string; t: number }[]>`, `anomalies: Ref<{ system; severity; detail }[]>`.
  - `report: Ref<DiagnosticReport | null>`.
  - `latest: Reactive<Record<string, LiveValue | null>>`, `series: Reactive<Record<string, [number, number][]>>` (capped `WINDOW = 120`).
  - `start(protocol = 'default')`, `stop()`.

- [ ] **Step 1: Write the failing test**

`frontend/src/composables/__tests__/useDiagnosticSession.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import type { DiagnosticStreamEvent } from '@/api/diagnosticStream'

const handlers: { current: ((e: DiagnosticStreamEvent) => void) | null } = { current: null }

vi.mock('@/api/diagnosticStream', () => ({
  streamDiagnostic: vi.fn(async (_v: number, _p: string, onEvent: (e: DiagnosticStreamEvent) => void, signal?: AbortSignal) => {
    handlers.current = onEvent
    await new Promise<void>((resolve) => { if (signal) signal.addEventListener('abort', () => resolve()) })
  }),
}))

import { useDiagnosticSession } from '@/composables/useDiagnosticSession'

beforeEach(() => { handlers.current = null })

describe('useDiagnosticSession', () => {
  it('tracks protocol steps, samples, commentary, anomalies, and the report', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()

    handlers.current!({
      type: 'session', diagnostic_session_id: 3, live_session_id: 9,
      protocol: [{ id: 'idle_baseline', label: 'Idle', instruction: 'idle' },
                 { id: 'rev_2500', label: 'Rev', instruction: 'rev' }],
    })
    expect(d.status.value).toBe('running')
    expect(d.steps.value.map((s) => s.state)).toEqual(['pending', 'pending'])

    handlers.current!({ type: 'step', index: 0, total: 2, id: 'idle_baseline', label: 'Idle', instruction: 'idle', state: 'active', adhoc: false })
    expect(d.steps.value[0].state).toBe('active')
    expect(d.currentIndex.value).toBe(0)

    handlers.current!({ type: 'sample', seq: 1, t: 0, values: { RPM: { value: 700, unit: 'rpm' } } })
    handlers.current!({ type: 'sample', seq: 2, t: 1000, values: { RPM: { value: 720, unit: 'rpm' } } })
    expect(d.latest.RPM!.value).toBe(720)
    expect(d.series.RPM).toEqual([[0, 700], [1000, 720]])

    handlers.current!({ type: 'step', index: 0, total: 2, id: 'idle_baseline', label: 'Idle', instruction: 'idle', state: 'done', adhoc: false })
    expect(d.steps.value[0].state).toBe('done')

    handlers.current!({ type: 'commentary', text: 'Idle steady.', t: 1000 })
    expect(d.commentary.value[0].text).toBe('Idle steady.')

    handlers.current!({ type: 'anomaly', system: 'fuel', severity: 'warn', pid: 'LONG_FUEL_TRIM_1', detail: '+14% lean' })
    expect(d.anomalies.value[0].system).toBe('fuel')

    handlers.current!({ type: 'report', overall_status: 'fair', summary: 'ok', findings: [] })
    expect(d.report.value?.overall_status).toBe('fair')

    handlers.current!({ type: 'done' })
    expect(d.status.value).toBe('complete')
  })

  it('goes to error on an error event', async () => {
    const d = useDiagnosticSession(1)
    d.start()
    await flushPromises()
    handlers.current!({ type: 'error', detail: 'no scanner' })
    expect(d.status.value).toBe('error')
    expect(d.detail.value).toContain('scanner')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/composables/__tests__/useDiagnosticSession.test.ts`
Expected: FAIL — cannot resolve `@/composables/useDiagnosticSession`.

- [ ] **Step 3: Implement the composable**

`frontend/src/composables/useDiagnosticSession.ts`:
```ts
import { ref, reactive } from 'vue'
import { streamDiagnostic, type DiagnosticStreamEvent } from '@/api/diagnosticStream'
import type { DiagnosticReport, LiveValue } from '@/api/types'

const WINDOW = 120

type DiagStatus = 'idle' | 'connecting' | 'running' | 'complete' | 'error'

interface StepView {
  id: string
  label: string
  instruction: string
  state: 'pending' | 'active' | 'done' | 'skipped'
  adhoc: boolean
}

export function useDiagnosticSession(vehicleId: number) {
  const status = ref<DiagStatus>('idle')
  const detail = ref('')
  const steps = ref<StepView[]>([])
  const currentIndex = ref(-1)
  const commentary = ref<{ text: string; t: number }[]>([])
  const anomalies = ref<{ system: string; severity: string; detail: string }[]>([])
  const report = ref<DiagnosticReport | null>(null)
  const latest = reactive<Record<string, LiveValue | null>>({})
  const series = reactive<Record<string, [number, number][]>>({})

  let controller: AbortController | null = null

  function onEvent(event: DiagnosticStreamEvent) {
    if (event.type === 'session') {
      status.value = 'running'
      steps.value = event.protocol.map((s) => ({
        id: s.id, label: s.label, instruction: s.instruction, state: 'pending', adhoc: false,
      }))
      if (event.vin_mismatch) detail.value = event.vin_mismatch
    } else if (event.type === 'step') {
      currentIndex.value = event.index
      const existing = steps.value[event.index]
      const view: StepView = {
        id: event.id, label: event.label, instruction: event.instruction,
        state: event.state === 'active' ? 'active' : event.state, adhoc: event.adhoc,
      }
      if (existing) steps.value[event.index] = view
      else steps.value.splice(event.index, 0, view)
    } else if (event.type === 'sample') {
      for (const [pid, v] of Object.entries(event.values)) {
        latest[pid] = v
        if (v && typeof v.value === 'number') {
          const buf = series[pid] ?? (series[pid] = [])
          buf.push([event.t, v.value])
          if (buf.length > WINDOW) buf.splice(0, buf.length - WINDOW)
        }
      }
    } else if (event.type === 'commentary') {
      commentary.value.push({ text: event.text, t: event.t })
    } else if (event.type === 'anomaly') {
      anomalies.value.push({ system: event.system, severity: event.severity, detail: event.detail })
    } else if (event.type === 'report') {
      report.value = { overall_status: event.overall_status, summary: event.summary, findings: event.findings }
    } else if (event.type === 'done') {
      if (status.value !== 'error') status.value = 'complete'
    } else if (event.type === 'error') {
      status.value = 'error'
      detail.value = event.detail
    }
  }

  async function start(protocol = 'default') {
    stop()
    status.value = 'connecting'
    detail.value = ''
    steps.value = []
    commentary.value = []
    anomalies.value = []
    report.value = null
    currentIndex.value = -1
    for (const k of Object.keys(latest)) delete latest[k]
    for (const k of Object.keys(series)) delete series[k]
    controller = new AbortController()
    try {
      await streamDiagnostic(vehicleId, protocol, onEvent, controller.signal)
      const current = status.value as DiagStatus
      if (current !== 'error' && current !== 'complete') status.value = 'idle'
    } catch (err) {
      if ((err as Error).name === 'AbortError') status.value = 'idle'
      else { status.value = 'error'; detail.value = (err as Error).message }
    }
  }

  function stop() {
    controller?.abort()
    controller = null
    const current = status.value as DiagStatus
    if (current !== 'error' && current !== 'complete') status.value = 'idle'
  }

  return { status, detail, steps, currentIndex, commentary, anomalies, report, latest, series, start, stop }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/composables/__tests__/useDiagnosticSession.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useDiagnosticSession.ts frontend/src/composables/__tests__/useDiagnosticSession.test.ts
git commit -m "feat(diagnostic-ui): session composable tracking steps, commentary, report"
```

---

### Task 3: `DiagnosticStep` + `CommentaryItem` components

**Files:**
- Create: `frontend/src/components/DiagnosticStep.vue`, `frontend/src/components/CommentaryItem.vue`
- Test: `frontend/src/components/__tests__/diagnosticFeed.test.ts`

**Interfaces:**
- `DiagnosticStep` props: `{ index: number; label: string; instruction: string; state: 'pending'|'active'|'done'|'skipped'; adhoc: boolean }`.
- `CommentaryItem` props: `{ text: string }`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/__tests__/diagnosticFeed.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import DiagnosticStep from '@/components/DiagnosticStep.vue'
import CommentaryItem from '@/components/CommentaryItem.vue'

describe('DiagnosticStep', () => {
  it('shows label, instruction, and a done marker', () => {
    const w = mount(DiagnosticStep, {
      props: { index: 0, label: 'Idle baseline', instruction: 'Let it idle', state: 'done', adhoc: false },
    })
    expect(w.text()).toContain('Idle baseline')
    expect(w.text()).toContain('Let it idle')
    expect(w.html()).toContain('✓')
  })

  it('marks the active step', () => {
    const w = mount(DiagnosticStep, {
      props: { index: 1, label: 'Rev', instruction: 'rev to 2500', state: 'active', adhoc: false },
    })
    expect(w.attributes('data-state')).toBe('active')
  })

  it('tags ad-hoc steps', () => {
    const w = mount(DiagnosticStep, {
      props: { index: 2, label: 'Hold 2000', instruction: 'hold', state: 'active', adhoc: true },
    })
    expect(w.text().toLowerCase()).toContain('added')
  })
})

describe('CommentaryItem', () => {
  it('renders the commentary text', () => {
    const w = mount(CommentaryItem, { props: { text: 'Idle looks steady.' } })
    expect(w.text()).toContain('Idle looks steady.')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/diagnosticFeed.test.ts`
Expected: FAIL — cannot resolve `@/components/DiagnosticStep.vue`.

- [ ] **Step 3: Implement the components**

`frontend/src/components/DiagnosticStep.vue`:
```vue
<script setup lang="ts">
defineProps<{
  index: number
  label: string
  instruction: string
  state: 'pending' | 'active' | 'done' | 'skipped'
  adhoc: boolean
}>()
</script>

<template>
  <div
    :data-state="state"
    class="flex items-start gap-3 border-b border-border/50 px-4 py-3 last:border-b-0"
    :class="state === 'active' ? 'bg-surface-2' : ''"
  >
    <span
      class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[0.65rem]"
      :class="{
        'bg-success/15 text-success': state === 'done',
        'bg-accent/15 text-accent animate-pulse': state === 'active',
        'bg-muted/15 text-muted/50': state === 'pending',
        'bg-warning/15 text-warning': state === 'skipped',
      }"
    >
      <template v-if="state === 'done'">✓</template>
      <template v-else-if="state === 'skipped'">–</template>
      <template v-else>{{ index + 1 }}</template>
    </span>
    <div class="min-w-0">
      <p class="font-mono text-xs font-semibold tracking-wider text-text">
        {{ label }}
        <span v-if="adhoc" class="ml-1.5 rounded bg-accent/15 px-1 py-0.5 text-[0.55rem] uppercase tracking-widest text-accent">added</span>
      </p>
      <p class="mt-0.5 text-xs text-muted">{{ instruction }}</p>
    </div>
  </div>
</template>
```

`frontend/src/components/CommentaryItem.vue`:
```vue
<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
  <div class="flex items-start gap-2 px-4 py-2">
    <span class="mt-1 text-accent/60 select-none" aria-hidden="true">▸</span>
    <p class="text-sm leading-relaxed text-text/90">{{ text }}</p>
  </div>
</template>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/diagnosticFeed.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DiagnosticStep.vue frontend/src/components/CommentaryItem.vue frontend/src/components/__tests__/diagnosticFeed.test.ts
git commit -m "feat(diagnostic-ui): step tracker and commentary timeline components"
```

---

### Task 4: `HealthReport` component

**Files:**
- Create: `frontend/src/components/HealthReport.vue`
- Test: `frontend/src/components/__tests__/healthReport.test.ts`

**Interfaces:**
- `HealthReport` props: `{ report: DiagnosticReport }`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/__tests__/healthReport.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import HealthReport from '@/components/HealthReport.vue'
import type { DiagnosticReport } from '@/api/types'

const report: DiagnosticReport = {
  overall_status: 'fair',
  summary: 'One lean bank, otherwise healthy.',
  findings: [
    { system: 'fuel', severity: 'warn', observation: 'LTFT +14% at 2500 rpm',
      interpretation: 'Running lean under load.', recommendation: 'Check for a vacuum leak.',
      evidence: { sources: [{ filename: 'service.pdf', page: 142 }] } },
    { system: 'cooling', severity: 'good', observation: 'Coolant held at 88C',
      interpretation: '', recommendation: '', evidence: {} },
  ],
}

describe('HealthReport', () => {
  it('renders overall status, summary, findings, and citations', () => {
    const w = mount(HealthReport, { props: { report } })
    expect(w.text().toLowerCase()).toContain('fair')
    expect(w.text()).toContain('One lean bank')
    expect(w.text()).toContain('fuel')
    expect(w.text()).toContain('Check for a vacuum leak.')
    expect(w.text()).toContain('service.pdf')
    expect(w.text()).toContain('142')
  })

  it('applies severity styling per finding', () => {
    const w = mount(HealthReport, { props: { report } })
    const fuel = w.find('[data-system="fuel"]')
    expect(fuel.attributes('data-severity')).toBe('warn')
    const cooling = w.find('[data-system="cooling"]')
    expect(cooling.attributes('data-severity')).toBe('good')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/healthReport.test.ts`
Expected: FAIL — cannot resolve `@/components/HealthReport.vue`.

- [ ] **Step 3: Implement**

`frontend/src/components/HealthReport.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { DiagnosticReport } from '@/api/types'

const props = defineProps<{ report: DiagnosticReport }>()

const overallClass = computed(() => ({
  good: 'border-success/40 bg-success/10 text-success',
  fair: 'border-warning/40 bg-warning/10 text-warning',
  poor: 'border-danger/40 bg-danger/10 text-danger',
}[props.report.overall_status]))

function sources(evidence: Record<string, unknown>): { filename?: string; page?: number }[] {
  const s = evidence?.sources
  return Array.isArray(s) ? (s as { filename?: string; page?: number }[]) : []
}
</script>

<template>
  <section class="rounded-card border border-border bg-surface p-4">
    <div class="mb-3 flex items-center gap-3">
      <span class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Health report</span>
      <div class="h-px flex-1 bg-border/50" />
      <span
        class="rounded-md border px-2.5 py-1 font-mono text-[0.65rem] font-semibold uppercase tracking-widest"
        :class="overallClass"
      >{{ report.overall_status }}</span>
    </div>

    <p class="mb-4 text-sm leading-relaxed text-text/90">{{ report.summary }}</p>

    <ul class="space-y-2">
      <li
        v-for="f in report.findings"
        :key="f.system"
        :data-system="f.system"
        :data-severity="f.severity"
        class="rounded-md border border-border/60 bg-surface-2 px-3 py-2.5"
      >
        <div class="flex items-center gap-2">
          <span
            class="h-2 w-2 shrink-0 rounded-full"
            :class="{ 'bg-success': f.severity === 'good', 'bg-warning': f.severity === 'warn', 'bg-danger': f.severity === 'fail' }"
          />
          <span class="font-mono text-xs font-semibold uppercase tracking-wider text-text">{{ f.system }}</span>
          <span class="font-mono text-[0.6rem] uppercase tracking-widest text-muted/50">{{ f.severity }}</span>
        </div>
        <p class="mt-1.5 text-xs text-text/80">{{ f.observation }}</p>
        <p v-if="f.interpretation" class="mt-1 text-xs text-muted">{{ f.interpretation }}</p>
        <p v-if="f.recommendation" class="mt-1 text-xs text-accent/90">→ {{ f.recommendation }}</p>
        <ul v-if="sources(f.evidence).length" class="mt-1.5 text-[0.65rem] text-muted/60">
          <li v-for="(s, i) in sources(f.evidence)" :key="i" class="font-mono">
            › {{ s.filename }}<template v-if="s.page"> · p.{{ s.page }}</template>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/healthReport.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HealthReport.vue frontend/src/components/__tests__/healthReport.test.ts
git commit -m "feat(diagnostic-ui): structured health report component"
```

---

### Task 5: `DiagnosticSessionView` + route + entry links

**Files:**
- Create: `frontend/src/views/DiagnosticSessionView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/views/LiveView.vue` (add a "Run health check" link)
- Test: `frontend/src/views/__tests__/diagnosticView.test.ts`

**Interfaces:**
- Consumes: `useDiagnosticSession`; `LiveFocusChart`; `DiagnosticStep`; `CommentaryItem`; `HealthReport`.
- Produces: route `{ path: '/vehicles/:id/diagnostic', name: 'diagnostic', component: () => import('@/views/DiagnosticSessionView.vue') }`.

- [ ] **Step 1: Write the failing test**

`frontend/src/views/__tests__/diagnosticView.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import type { DiagnosticStreamEvent } from '@/api/diagnosticStream'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'initOptions', 'autoresize', 'manualUpdate'], template: '<div class="v-chart-stub" />' },
}))

const handlers: { current: ((e: DiagnosticStreamEvent) => void) | null } = { current: null }
vi.mock('@/api/diagnosticStream', () => ({
  streamDiagnostic: vi.fn(async (_v: number, _p: string, onEvent: (e: DiagnosticStreamEvent) => void, signal?: AbortSignal) => {
    handlers.current = onEvent
    await new Promise<void>((resolve) => { if (signal) signal.addEventListener('abort', () => resolve()) })
  }),
}))

import DiagnosticSessionView from '@/views/DiagnosticSessionView.vue'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id/diagnostic', name: 'diagnostic', component: DiagnosticSessionView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}/diagnostic`)
  return router.isReady().then(() => mount(DiagnosticSessionView, { global: { plugins: [router] } }))
}

beforeEach(() => { setActivePinia(createPinia()); handlers.current = null })

describe('DiagnosticSessionView', () => {
  it('starts a session and renders steps, commentary, vitals, and the report', async () => {
    const wrapper = await mountAt('1')
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()

    handlers.current!({
      type: 'session', diagnostic_session_id: 3, live_session_id: 9,
      protocol: [{ id: 'idle_baseline', label: 'Idle baseline', instruction: 'Let it idle' }],
    })
    handlers.current!({ type: 'step', index: 0, total: 1, id: 'idle_baseline', label: 'Idle baseline', instruction: 'Let it idle', state: 'active', adhoc: false })
    handlers.current!({ type: 'sample', seq: 1, t: 0, values: { RPM: { value: 700, unit: 'rpm' } } })
    handlers.current!({ type: 'commentary', text: 'Idle looks steady.', t: 0 })
    await flushPromises()

    expect(wrapper.text()).toContain('Idle baseline')
    expect(wrapper.text()).toContain('Idle looks steady.')
    expect(wrapper.text()).toContain('RPM')
    expect(wrapper.findAll('.v-chart-stub').length).toBeGreaterThanOrEqual(1)

    handlers.current!({ type: 'report', overall_status: 'good', summary: 'All clear.', findings: [] })
    handlers.current!({ type: 'done' })
    await flushPromises()
    expect(wrapper.text()).toContain('All clear.')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/views/__tests__/diagnosticView.test.ts`
Expected: FAIL — cannot resolve `@/views/DiagnosticSessionView.vue`.

- [ ] **Step 3: Implement the view**

`frontend/src/views/DiagnosticSessionView.vue`:
```vue
<script setup lang="ts">
import { computed, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useDiagnosticSession } from '@/composables/useDiagnosticSession'
import LiveFocusChart from '@/components/LiveFocusChart.vue'
import DiagnosticStep from '@/components/DiagnosticStep.vue'
import CommentaryItem from '@/components/CommentaryItem.vue'
import HealthReport from '@/components/HealthReport.vue'

const route = useRoute()
const vehicleId = Number(route.params.id)
const d = useDiagnosticSession(vehicleId)

onUnmounted(() => d.stop())

const running = computed(() => d.status.value === 'running' || d.status.value === 'connecting')
const vitalNames = computed(() => Object.keys(d.latest))
const focusSeries = computed(() =>
  vitalNames.value.slice(0, 4).map((name) => ({ name, points: d.series[name] ?? [] })),
)

function fmt(name: string): string {
  const v = d.latest[name]
  if (!v || v.value === null) return '—'
  return `${v.value}${v.unit ? ' ' + v.unit : ''}`
}
function toggle() {
  if (running.value) d.stop()
  else d.start()
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-8">
    <RouterLink
      :to="{ name: 'vehicle', params: { id: vehicleId } }"
      class="mb-6 inline-flex items-center gap-1.5 font-mono text-xs text-muted/60 hover:text-muted"
    >‹ Vehicle</RouterLink>

    <header class="mb-6 flex items-center justify-between rounded-card border border-border bg-surface p-4">
      <div>
        <h1 class="font-mono text-sm font-semibold uppercase tracking-widest text-text">Diagnostic copilot</h1>
        <p class="font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">
          VID <span class="text-muted/70">{{ vehicleId }}</span> · {{ d.status.value }}
        </p>
      </div>
      <button
        data-test="start"
        class="rounded-md border px-4 py-2 font-mono text-xs font-semibold uppercase tracking-widest transition-all duration-150"
        :class="running ? 'border-danger/40 bg-danger/10 text-danger hover:bg-danger/20' : 'border-accent/40 bg-accent/10 text-accent hover:bg-accent/20'"
        @click="toggle"
      >{{ running ? 'Stop' : 'Start health check' }}</button>
    </header>

    <div v-if="d.status.value === 'error'" class="mb-4 rounded-md border border-danger/30 bg-danger/8 px-4 py-3">
      <p class="font-mono text-xs text-danger">{{ d.detail.value }}</p>
    </div>

    <div class="grid gap-6 lg:grid-cols-2">
      <!-- Left: live vitals + focus chart -->
      <section class="space-y-4">
        <ul class="overflow-hidden rounded-card border border-border bg-surface">
          <li v-for="name in vitalNames" :key="name"
              class="flex items-center justify-between border-b border-border/50 px-4 py-2 last:border-b-0">
            <span class="font-mono text-xs tracking-wider text-text/90">{{ name }}</span>
            <span class="font-mono text-sm tabular-nums" :class="fmt(name) === '—' ? 'text-muted/30' : 'text-accent'">{{ fmt(name) }}</span>
          </li>
          <li v-if="vitalNames.length === 0" class="px-4 py-6 text-center font-mono text-xs text-muted/30">
            Start the health check to stream live vitals.
          </li>
        </ul>
        <div v-if="focusSeries.length" class="overflow-hidden rounded-card border border-border bg-surface">
          <LiveFocusChart :series="focusSeries" />
        </div>
      </section>

      <!-- Right: copilot feed + report -->
      <section class="space-y-4">
        <div class="overflow-hidden rounded-card border border-border bg-surface">
          <div class="border-b border-border/50 px-4 py-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Guided steps</div>
          <DiagnosticStep
            v-for="(s, i) in d.steps.value" :key="s.id + i"
            :index="i" :label="s.label" :instruction="s.instruction" :state="s.state" :adhoc="s.adhoc"
          />
          <p v-if="d.steps.value.length === 0" class="px-4 py-6 text-center font-mono text-xs text-muted/30">No active protocol.</p>
        </div>

        <div v-if="d.commentary.value.length" class="overflow-hidden rounded-card border border-border bg-surface">
          <div class="border-b border-border/50 px-4 py-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/50">Live commentary</div>
          <CommentaryItem v-for="(c, i) in d.commentary.value" :key="i" :text="c.text" />
        </div>

        <HealthReport v-if="d.report.value" :report="d.report.value" />
      </section>
    </div>
  </main>
</template>
```

- [ ] **Step 4: Add the route**

In `frontend/src/router/index.ts`, add this route after the `live` route:
```ts
    { path: '/vehicles/:id/diagnostic', name: 'diagnostic', component: () => import('@/views/DiagnosticSessionView.vue') },
```

- [ ] **Step 5: Add an entry link from the Live view**

In `frontend/src/views/LiveView.vue`, add a link in the header. Insert this `RouterLink` immediately before the Start/Stop `<button>` in the right-hand `div.flex.items-center.gap-4` block (right after the closing `</div>` of the status-text block, before `<!-- Start / Stop button -->`):
```vue
          <RouterLink
            :to="{ name: 'diagnostic', params: { id: vehicleId } }"
            class="rounded-md border border-border px-3 py-2 font-mono text-[0.65rem] uppercase tracking-widest text-muted/70 transition-colors hover:text-accent"
          >Health check</RouterLink>
```

- [ ] **Step 6: Run the view test + the existing LiveView test (entry link must not break it)**

Run: `cd frontend && npx vitest run src/views/__tests__/diagnosticView.test.ts src/views/__tests__/liveView.test.ts`
Expected: PASS (both files green).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/DiagnosticSessionView.vue frontend/src/router/index.ts frontend/src/views/LiveView.vue frontend/src/views/__tests__/diagnosticView.test.ts
git commit -m "feat(diagnostic-ui): diagnostic session view, route, and entry link"
```

---

### Task 6: Diagnostic source citation in chat (`MessageBubble`)

**Files:**
- Modify: `frontend/src/components/MessageBubble.vue`
- Test: `frontend/src/components/__tests__/messageBubble.test.ts`

**Interfaces:**
- Consumes: a chat `sources` entry of shape `{ kind: 'diagnostic', session_id: number, date: string, overall_status: string }` (from the backend `get_diagnostic_reports` tool), alongside the existing `{ filename, page }` manual sources.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/__tests__/messageBubble.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import MessageBubble from '@/components/MessageBubble.vue'

describe('MessageBubble sources', () => {
  it('renders a manual source (filename + page)', () => {
    const w = mount(MessageBubble, {
      props: { role: 'assistant', content: 'Use 5W-30.', sources: [{ filename: 'm.pdf', page: 3 }] },
    })
    expect(w.text()).toContain('m.pdf')
    expect(w.text()).toContain('3')
  })

  it('renders a diagnostic source (date + status)', () => {
    const w = mount(MessageBubble, {
      props: {
        role: 'assistant', content: 'Last check was fair.',
        sources: [{ kind: 'diagnostic', session_id: 7, date: '2026-06-15', overall_status: 'fair' }],
      },
    })
    expect(w.text().toLowerCase()).toContain('health check')
    expect(w.text()).toContain('2026-06-15')
    expect(w.text().toLowerCase()).toContain('fair')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/messageBubble.test.ts`
Expected: FAIL — the diagnostic-source assertion fails (current template only renders `filename`/`url` + `page`).

- [ ] **Step 3: Update `MessageBubble.vue`**

Replace the `<li>` body inside the sources `<ul>` (the block rendering `‹s.filename›`/`p.{{ s.page }}`) with a `kind`-aware branch:
```vue
        <li
          v-for="(s, i) in sources"
          :key="i"
          class="flex items-center gap-1.5 font-mono leading-5"
        >
          <span class="text-accent/50 select-none">›</span>
          <template v-if="s.kind === 'diagnostic'">
            <span>Health check</span>
            <span class="text-muted/40">·</span>
            <span class="text-muted/70">{{ s.date }}</span>
            <span class="text-muted/40">·</span>
            <span class="uppercase text-muted/70">{{ s.overall_status }}</span>
          </template>
          <template v-else>
            <span>{{ (s.filename as string) ?? (s.url as string) }}</span>
            <template v-if="s.page">
              <span class="text-muted/40">·</span>
              <span class="text-muted/70">p.{{ s.page }}</span>
            </template>
          </template>
        </li>
```
(The `defineProps` type — `sources?: Array<Record<string, unknown>> | null` — already accommodates the extra keys; no prop-type change needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/messageBubble.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full frontend suite + type-check**

Run: `cd frontend && npx vitest run && npm run build`
Expected: all Vitest files PASS; `vue-tsc -b` + `vite build` succeed (no type errors; ECharts stays code-split into the lazy diagnostic/live chunks).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MessageBubble.vue frontend/src/components/__tests__/messageBubble.test.ts
git commit -m "feat(diagnostic-ui): cite past health reports in chat sources"
```

---

## Self-Review

**Spec coverage:** Separate diagnostic view + route (T5) = DC1; the view consumes `step`/`commentary`/`anomaly`/`report` events that carry the hybrid protocol + periodic commentary (DC2/DC3) produced by the backend; `HealthReport` renders the structured persisted report (DC4); `MessageBubble` diagnostic citation (DC8). Reuse: `LiveFocusChart` and the `WINDOW=120` buffer logic are reused, not rebuilt. Past-report listing/detail client methods (T1) back a future history panel and the chat tool's data.

**Placeholder scan:** No TBD/TODO; every step has complete code and an exact run command.

**Type consistency:** `DiagnosticStreamEvent` (T1) is consumed unchanged by `useDiagnosticSession` (T2) and `DiagnosticSessionView` (T5). `DiagnosticReport`/`DiagnosticFinding` (T1) flow into `HealthReport` (T4) and the composable's `report` ref. The composable's returned shape (`status, detail, steps, currentIndex, commentary, anomalies, report, latest, series, start, stop`) matches what the view consumes. The `{kind:'diagnostic', session_id, date, overall_status}` source shape (T6) matches the backend tool's output exactly.

---

## Execution Handoff

**Plan complete.** Build the **backend plan first** (the endpoints this UI calls), then this frontend plan. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.
2. **Inline Execution** — batch with checkpoints.
