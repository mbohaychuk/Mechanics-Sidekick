# Live Telemetry Dashboard — Frontend (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **View tasks (3–5) must additionally use the `frontend-design` skill** to produce polished UI while keeping the specified script logic and passing the listed tests.

**Goal:** Build the Vue Live view — a per-vehicle real-time telemetry dashboard (dense vitals list with per-row sparklines + a focus chart, a PID picker, connection/VIN/Hz status, and past-session replay) consuming the backend's `/live` SSE + `supported-pids` + `sessions` endpoints.

**Architecture:** A `liveStream` fetch-based SSE reader (GET, mirroring the existing `chatStream`) + a `useLiveSession` composable holding rolling per-PID buffers and connection state. ECharts (via `vue-echarts`, tree-shaken, SVG renderer) renders sparklines + the focus chart with reactive `:option` (modest 1 Hz data). A new `LiveView` ties it together; the vehicle-detail page links to it.

**Tech Stack:** Vue 3 (`<script setup lang="ts">`), TypeScript, Vite, Tailwind v4 (existing), Pinia/vue-router (existing), `echarts` + `vue-echarts` (new), Vitest + @vue/test-utils + jsdom.

This is **Plan B (frontend)** of the live telemetry dashboard; it builds on **Plan A (backend)**. It produces the working dashboard UI.

## Backend contract (reference — exact shapes this plan consumes)

```
GET /api/vehicles/{id}/live?pids=RPM,SPEED        -> text/event-stream (open-ended)
   events: {type:"session",   session_id, target_hz}
           {type:"sample",     seq, t, hz, values: { <PID>: {value, unit} | null }}   // filtered to subscribed PIDs
           {type:"vin_mismatch", detail}
           {type:"disconnected", detail}
           {type:"error",      detail}
           {type:"done"}                                                              // only on the no-manager path
   409 (JSON) if a session is already active for ANOTHER vehicle.
GET /api/vehicles/{id}/supported-pids  -> { available: bool, curated: string[], supported: [{pid,name,description}] }
GET /api/vehicles/{id}/sessions        -> [{ id, vehicle_id, status, started_utc, ended_utc, achieved_hz, sample_count, pids }]
GET /api/sessions/{id}                 -> { session:{id,vehicle_id,status,pids,sample_count}, samples:[{seq,t,values}] }
```
A live `sample`'s `values[pid]` is `{value, unit}` on success or `null` (PID unsupported / no-data). `value` is a number for chartable PIDs.

## Global Constraints

- All frontend work is inside `frontend/`; run Vitest from there (`npm test`). Node ≥ 20.19.
- New deps: `echarts` + `vue-echarts` (latest; echarts 6 / vue-echarts 8). Register ECharts **tree-shaken** in one side-effect module (`src/echarts.ts`) imported once in `main.ts`; use the **SVG renderer** (sparkline-dense page, jsdom-friendly). No other new dependency.
- ECharts touches canvas/ResizeObserver that jsdom lacks — **component tests MUST stub `vue-echarts`** via `vi.mock('vue-echarts', ...)` (a `<div>` stub exposing the `option` prop). Never render a real chart under Vitest.
- API calls use relative `/api/...` paths (never a hardcoded host). The live stream is a **GET** SSE; the reader mirrors `frontend/src/api/chatStream.ts`'s buffer/flush loop. Aborting the stream (`AbortController`) is a clean stop, not an error.
- Strict TS; `npm run build` (`vue-tsc -b && vite build`) passes. The existing 17 frontend tests stay green; tests never hit the network (`fetch`/the API client/`vue-echarts` are stubbed/mocked).
- Reuse the established patterns: the `api`/`request<T>` client (`src/api/client.ts`), the SSE-reader shape (`chatStream.ts`), Pinia setup-stores, the Tailwind `@theme` "garage console" tokens. Each view owns its single `<main>`; `AppLayout` is the chrome.
- Commit messages plain, conventional-commit; no AI attribution.

---

### Task 1: ECharts setup + live SSE reader + live types/client

**Files:**
- Modify: `frontend/package.json` (add deps — via npm)
- Create: `frontend/src/echarts.ts`
- Modify: `frontend/src/main.ts` (import the echarts side-effect module)
- Modify: `frontend/src/api/types.ts` (add live types)
- Modify: `frontend/src/api/client.ts` (add live read methods)
- Create: `frontend/src/api/liveStream.ts`
- Test: `frontend/src/api/__tests__/liveStream.test.ts`, `frontend/src/api/__tests__/liveClient.test.ts`

**Interfaces:**
- Produces:
  - `src/echarts.ts` — registers `LineChart`, `GridComponent`, `TooltipComponent`, `DataZoomComponent`, `SVGRenderer`; exports the `ECOption` type.
  - `types.ts` — `LiveValue`, `LiveSampleEvent`, `LiveEvent` (union), `SupportedPid`, `SupportedPids`, `LiveSessionSummary`, `LiveSessionDetail`.
  - `client.ts` `api` gains `getSupportedPids(vehicleId)`, `listLiveSessions(vehicleId)`, `getLiveSession(sessionId)`.
  - `liveStream.ts` — `streamLive(vehicleId: number, pids: string[], onEvent: (e: LiveEvent) => void, signal?: AbortSignal): Promise<void>`.

- [ ] **Step 1: Install ECharts**

From `frontend/`:
```bash
npm install echarts vue-echarts
```
Expected: `package.json` gains `echarts` + `vue-echarts`; lockfile updates.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/api/__tests__/liveClient.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { api } from '@/api/client'

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body), text: () => Promise.resolve('') } as Response
}
afterEach(() => vi.restoreAllMocks())

describe('live api client', () => {
  it('gets supported pids', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ available: true, curated: ['RPM'], supported: [{ pid: '0C', name: 'RPM', description: 'Engine RPM' }] }))
    vi.stubGlobal('fetch', fetchMock)
    const res = await api.getSupportedPids(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/vehicles/1/supported-pids', expect.objectContaining({ method: 'GET' }))
    expect(res.curated).toContain('RPM')
    expect(res.supported[0].name).toBe('RPM')
  })

  it('lists and gets sessions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse([{ id: 3, vehicle_id: 1, status: 'ended', started_utc: 'x', ended_utc: 'y', achieved_hz: 0.9, sample_count: 12, pids: ['RPM'] }])))
    const list = await api.listLiveSessions(1)
    expect(list[0].sample_count).toBe(12)

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ session: { id: 3, vehicle_id: 1, status: 'ended', pids: ['RPM'], sample_count: 2 }, samples: [{ seq: 1, t: 0, values: { RPM: { value: 800, unit: 'rpm' } } }] })))
    const detail = await api.getLiveSession(3)
    expect(detail.samples[0].values.RPM!.value).toBe(800)
  })
})
```

Create `frontend/src/api/__tests__/liveStream.test.ts`:
```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamLive } from '@/api/liveStream'
import type { LiveEvent } from '@/api/types'

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({ start(c) { for (const f of frames) c.enqueue(enc.encode(f)); c.close() } })
}
afterEach(() => vi.restoreAllMocks())

describe('streamLive', () => {
  it('GETs the live URL with pids and parses events in order', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream([
        'data: {"type":"session","session_id":7,"target_hz":1.0}\n\n',
        'data: {"type":"sample","seq":1,"t":0,"hz":1.0,"values":{"RPM":{"value":820,"unit":"rpm"}}}\n\n',
        'data: {"type":"disconnected","detail":"adapter dropped"}\n\n',
      ]),
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    const events: LiveEvent[] = []
    await streamLive(1, ['RPM', 'SPEED'], (e) => events.push(e))

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/vehicles/1/live?pids=RPM%2CSPEED')
    expect(events.map((e) => e.type)).toEqual(['session', 'sample', 'disconnected'])
    expect((events[1] as { values: Record<string, { value: number }> }).values.RPM.value).toBe(820)
  })

  it('throws on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409, body: null } as Response))
    await expect(streamLive(1, ['RPM'], () => {})).rejects.toBeTruthy()
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `frontend/`): `npm test -- live`
Expected: FAIL — modules/methods missing.

- [ ] **Step 4: ECharts registration module**

Create `frontend/src/echarts.ts`:
```ts
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption } from 'echarts/charts'
import type { GridComponentOption, TooltipComponentOption, DataZoomComponentOption } from 'echarts/components'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, SVGRenderer])

export type ECOption = ComposeOption<
  LineSeriesOption | GridComponentOption | TooltipComponentOption | DataZoomComponentOption
>

export default echarts
```

In `frontend/src/main.ts`, add the side-effect import near the top (after `import './style.css'`):
```ts
import '@/echarts'
```

- [ ] **Step 5: Add the live types**

Append to `frontend/src/api/types.ts`:
```ts
export interface LiveValue {
  value: number | string | null
  unit: string | null
}

export interface LiveSampleEvent {
  type: 'sample'
  seq: number
  t: number
  hz: number
  values: Record<string, LiveValue | null>
}

export type LiveEvent =
  | { type: 'session'; session_id: number; target_hz: number }
  | LiveSampleEvent
  | { type: 'vin_mismatch'; detail: string }
  | { type: 'disconnected'; detail: string }
  | { type: 'error'; detail: string }
  | { type: 'done' }

export interface SupportedPid {
  pid: string
  name: string
  description: string
}

export interface SupportedPids {
  available: boolean
  curated: string[]
  supported: SupportedPid[]
}

export interface LiveSessionSummary {
  id: number
  vehicle_id: number
  status: string
  started_utc: string
  ended_utc: string | null
  achieved_hz: number | null
  sample_count: number
  pids: string[]
}

export interface LiveSessionDetail {
  session: { id: number; vehicle_id: number; status: string; pids: string[]; sample_count: number }
  samples: { seq: number; t: number; values: Record<string, LiveValue | null> }[]
}
```

- [ ] **Step 6: Add the client methods**

In `frontend/src/api/client.ts`, extend the imports and the `api` object:
```ts
import type {
  AppConfig, ChatMessage, Document, Job, JobCreate, LiveSessionDetail, LiveSessionSummary,
  ScannerStatus, SupportedPids, Vehicle, VehicleCreate,
} from '@/api/types'
```
Add these three entries to the `api` object (after `getConfig`):
```ts
  getSupportedPids: (vehicleId: number) =>
    request<SupportedPids>(`/api/vehicles/${vehicleId}/supported-pids`),
  listLiveSessions: (vehicleId: number) =>
    request<LiveSessionSummary[]>(`/api/vehicles/${vehicleId}/sessions`),
  getLiveSession: (sessionId: number) =>
    request<LiveSessionDetail>(`/api/sessions/${sessionId}`),
```

- [ ] **Step 7: Write the live SSE reader**

Create `frontend/src/api/liveStream.ts`:
```ts
import type { LiveEvent } from '@/api/types'

export async function streamLive(
  vehicleId: number,
  pids: string[],
  onEvent: (event: LiveEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const qs = new URLSearchParams({ pids: pids.join(',') })
  const response = await fetch(`/api/vehicles/${vehicleId}/live?${qs}`, { signal })
  if (!response.ok || !response.body) {
    throw new Error(`Live request failed: ${response.status}`)
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
        onEvent(JSON.parse(payload) as LiveEvent)
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

- [ ] **Step 8: Run the tests + build**

Run (from `frontend/`): `npm test -- live` → PASS.
Run: `npm test` → all green (incl. the prior 17).
Run: `npm run build` → strict TS + build succeed.

- [ ] **Step 9: Commit**

```bash
cd .. && git add frontend/package.json frontend/package-lock.json frontend/src/echarts.ts frontend/src/main.ts frontend/src/api
git commit -m "feat(web): ECharts setup, live SSE reader, and telemetry API client/types"
```

---

### Task 2: `useLiveSession` composable

**Files:**
- Create: `frontend/src/composables/useLiveSession.ts`
- Test: `frontend/src/composables/__tests__/useLiveSession.test.ts`

**Interfaces:**
- Consumes: `streamLive` (Task 1), the `LiveEvent` types.
- Produces: `useLiveSession(vehicleId: number)` returning `{ status, detail, vinMismatch, achievedHz, sessionId, activePids, latest, series, start, stop }`:
  - `status: Ref<'idle' | 'connecting' | 'streaming' | 'error'>`, `detail: Ref<string>`, `vinMismatch: Ref<string | null>`, `achievedHz: Ref<number>`, `sessionId: Ref<number | null>`, `activePids: Ref<string[]>`.
  - `latest: reactive Record<string, LiveValue | null>` (latest value per PID).
  - `series: reactive Record<string, [number, number][]>` (rolling `[t, value]` per PID, capped at `WINDOW = 120`).
  - `start(pids: string[]): Promise<void>` (opens the stream), `stop(): void` (aborts — a clean stop).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/composables/__tests__/useLiveSession.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import type { LiveEvent } from '@/api/types'

const handlers: { current: ((e: LiveEvent) => void) | null } = { current: null }

vi.mock('@/api/liveStream', () => ({
  streamLive: vi.fn(async (_vid: number, _pids: string[], onEvent: (e: LiveEvent) => void, signal?: AbortSignal) => {
    handlers.current = onEvent
    // resolve when aborted (mirrors a real stop)
    await new Promise<void>((resolve) => {
      if (signal) signal.addEventListener('abort', () => resolve())
    })
  }),
}))

import { useLiveSession } from '@/composables/useLiveSession'

beforeEach(() => { handlers.current = null })

describe('useLiveSession', () => {
  it('streams samples into latest + capped series and tracks state', async () => {
    const s = useLiveSession(1)
    s.start(['RPM', 'SPEED'])
    await flushPromises()

    handlers.current!({ type: 'session', session_id: 7, target_hz: 1 })
    expect(s.status.value).toBe('streaming')
    expect(s.sessionId.value).toBe(7)

    handlers.current!({ type: 'sample', seq: 1, t: 0, hz: 0.9, values: { RPM: { value: 800, unit: 'rpm' }, SPEED: null } })
    handlers.current!({ type: 'sample', seq: 2, t: 1000, hz: 0.95, values: { RPM: { value: 820, unit: 'rpm' }, SPEED: null } })

    expect(s.achievedHz.value).toBe(0.95)
    expect(s.latest.RPM!.value).toBe(820)
    expect(s.series.RPM).toEqual([[0, 800], [1000, 820]])
    expect(s.series.SPEED ?? []).toEqual([])  // null values are not charted

    s.stop()
    await flushPromises()
    expect(s.status.value).toBe('idle')
  })

  it('surfaces vin_mismatch and disconnected', async () => {
    const s = useLiveSession(1)
    s.start(['RPM'])
    await flushPromises()
    handlers.current!({ type: 'vin_mismatch', detail: 'scanner VIN differs' })
    expect(s.vinMismatch.value).toContain('VIN')
    handlers.current!({ type: 'disconnected', detail: 'adapter dropped' })
    expect(s.status.value).toBe('error')
    expect(s.detail.value).toContain('adapter')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- useLiveSession`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the composable**

Create `frontend/src/composables/useLiveSession.ts`:
```ts
import { ref, reactive } from 'vue'
import { streamLive } from '@/api/liveStream'
import type { LiveEvent, LiveValue } from '@/api/types'

const WINDOW = 120

export function useLiveSession(vehicleId: number) {
  const status = ref<'idle' | 'connecting' | 'streaming' | 'error'>('idle')
  const detail = ref('')
  const vinMismatch = ref<string | null>(null)
  const achievedHz = ref(0)
  const sessionId = ref<number | null>(null)
  const activePids = ref<string[]>([])
  const latest = reactive<Record<string, LiveValue | null>>({})
  const series = reactive<Record<string, [number, number][]>>({})

  let controller: AbortController | null = null

  function onEvent(event: LiveEvent) {
    if (event.type === 'session') {
      sessionId.value = event.session_id
      status.value = 'streaming'
    } else if (event.type === 'sample') {
      achievedHz.value = event.hz
      for (const [pid, v] of Object.entries(event.values)) {
        latest[pid] = v
        if (v && typeof v.value === 'number') {
          const buf = series[pid] ?? (series[pid] = [])
          buf.push([event.t, v.value])
          if (buf.length > WINDOW) buf.splice(0, buf.length - WINDOW)
        }
      }
    } else if (event.type === 'vin_mismatch') {
      vinMismatch.value = event.detail
    } else if (event.type === 'disconnected' || event.type === 'error') {
      status.value = 'error'
      detail.value = event.detail
    }
  }

  async function start(pids: string[]) {
    stop()
    activePids.value = [...pids]
    vinMismatch.value = null
    detail.value = ''
    status.value = 'connecting'
    controller = new AbortController()
    try {
      await streamLive(vehicleId, pids, onEvent, controller.signal)
      if (status.value === 'streaming') status.value = 'idle'  // stream ended cleanly
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        status.value = 'idle'
      } else {
        status.value = 'error'
        detail.value = (err as Error).message
      }
    }
  }

  function stop() {
    controller?.abort()
    controller = null
    if (status.value !== 'error') status.value = 'idle'
  }

  return { status, detail, vinMismatch, achievedHz, sessionId, activePids, latest, series, start, stop }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- useLiveSession` → PASS.

- [ ] **Step 5: Commit**

```bash
cd .. && git add frontend/src/composables && git commit -m "feat(web): useLiveSession composable (stream state + rolling buffers)"
```

---

### Task 3: chart components — `LiveSparkline` + `LiveFocusChart`

> **Use the `frontend-design` skill** for visual polish; the props/computed-`option` logic and the tests are the contract.

**Files:**
- Create: `frontend/src/components/LiveSparkline.vue`, `frontend/src/components/LiveFocusChart.vue`
- Test: `frontend/src/components/__tests__/liveCharts.test.ts`

**Interfaces:**
- Consumes: `vue-echarts` (`VChart`), the `ECOption` type (Task 1).
- Produces:
  - `LiveSparkline` — props `{ points: [number, number][] }`; renders a bare SVG line (no axes/grid/tooltip, `animation:false`) sized ~`32px × 120px`. Computes `option` with a single line series from `points`.
  - `LiveFocusChart` — props `{ series: { name: string; points: [number, number][] }[] }`; renders a line chart with a value y-axis, tooltip, inside dataZoom, and one line per series. Computes `option` accordingly.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/liveCharts.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'initOptions', 'autoresize', 'manualUpdate'], template: '<div class="v-chart-stub" />' },
}))

import LiveSparkline from '@/components/LiveSparkline.vue'
import LiveFocusChart from '@/components/LiveFocusChart.vue'

function chartOption(wrapper: ReturnType<typeof mount>) {
  return wrapper.findComponent({ name: 'VChart' }).props('option') as {
    series: { data: [number, number][]; name?: string }[]
  }
}

describe('LiveSparkline', () => {
  it('puts the points into a single line series', () => {
    const wrapper = mount(LiveSparkline, { props: { points: [[0, 800], [1000, 820]] } })
    expect(wrapper.find('.v-chart-stub').exists()).toBe(true)
    expect(chartOption(wrapper).series[0].data).toEqual([[0, 800], [1000, 820]])
  })
})

describe('LiveFocusChart', () => {
  it('renders one series per input series with names', () => {
    const wrapper = mount(LiveFocusChart, {
      props: { series: [{ name: 'RPM', points: [[0, 800]] }, { name: 'SPEED', points: [[0, 0]] }] },
    })
    const opt = chartOption(wrapper)
    expect(opt.series.map((s) => s.name)).toEqual(['RPM', 'SPEED'])
    expect(opt.series[0].data).toEqual([[0, 800]])
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- liveCharts`
Expected: FAIL — components missing.

- [ ] **Step 3: Implement `LiveSparkline.vue`**

Create `frontend/src/components/LiveSparkline.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { ECOption } from '@/echarts'

const props = defineProps<{ points: [number, number][] }>()

const option = computed<ECOption>(() => ({
  animation: false,
  grid: { top: 2, bottom: 2, left: 2, right: 2 },
  xAxis: { type: 'value', show: false },
  yAxis: { type: 'value', show: false, scale: true },
  series: [{ type: 'line', data: props.points, showSymbol: false, lineStyle: { width: 1.5 } }],
}))
</script>

<template>
  <VChart :option="option" :init-options="{ renderer: 'svg' }" autoresize class="h-8 w-28" />
</template>
```

- [ ] **Step 4: Implement `LiveFocusChart.vue`**

Create `frontend/src/components/LiveFocusChart.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { ECOption } from '@/echarts'

const props = defineProps<{ series: { name: string; points: [number, number][] }[] }>()

const option = computed<ECOption>(() => ({
  grid: { left: 48, right: 16, top: 24, bottom: 48 },
  tooltip: { trigger: 'axis' },
  legend: { top: 0, textStyle: { color: '#8b97a6' } },
  xAxis: { type: 'value', name: 't (ms)', axisLabel: { color: '#8b97a6' } },
  yAxis: { type: 'value', scale: true, axisLabel: { color: '#8b97a6' } },
  dataZoom: [{ type: 'inside' }],
  series: props.series.map((s) => ({
    type: 'line',
    name: s.name,
    data: s.points,
    showSymbol: false,
    lineStyle: { width: 2 },
  })),
}))
</script>

<template>
  <VChart :option="option" :init-options="{ renderer: 'svg' }" autoresize class="h-72 w-full" />
</template>
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `frontend/`): `npm test -- liveCharts` → PASS.
Run: `npm run build` → succeeds (TS resolves `@/echarts` types).

- [ ] **Step 6: Commit**

```bash
cd .. && git add frontend/src/components/LiveSparkline.vue frontend/src/components/LiveFocusChart.vue frontend/src/components/__tests__/liveCharts.test.ts
git commit -m "feat(web): LiveSparkline and LiveFocusChart ECharts components"
```

---

### Task 4: `LiveView` + PID picker + route + vehicle-detail entry

> **Use the `frontend-design` skill.** Logic + tests are the contract; elevate the dense-list / picker / header markup (garage-console tokens). Each view owns its single `<main>`.

**Files:**
- Create: `frontend/src/views/LiveView.vue`
- Modify: `frontend/src/router/index.ts` (add the `live` route)
- Modify: `frontend/src/views/VehicleDetailView.vue` (add a "Live data" entry link)
- Test: `frontend/src/views/__tests__/liveView.test.ts`

**Interfaces:**
- Consumes: `useLiveSession` (Task 2), `LiveSparkline`/`LiveFocusChart` (Task 3), `api.getSupportedPids` (Task 1), the `live` route param `id`.
- Produces: `LiveView` — loads supported PIDs on mount (default selection = curated ∩ supported, or curated if `supported` empty); a Start/Stop control driving `useLiveSession`; a dense vitals list (row per selected PID: name · latest value+unit or "—" · `LiveSparkline` · pin toggle); a "+ Add PID" picker over supported PIDs not yet selected; a `LiveFocusChart` of the pinned PIDs; a header with connection status + achieved Hz + a `vin_mismatch` banner. Adds route `/vehicles/:id/live` (name `live`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/views/__tests__/liveView.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('vue-echarts', () => ({
  default: { name: 'VChart', props: ['option', 'initOptions', 'autoresize', 'manualUpdate'], template: '<div class="v-chart-stub" />' },
}))
vi.mock('@/api/client', () => ({
  api: {
    getSupportedPids: vi.fn().mockResolvedValue({
      available: true, curated: ['RPM', 'SPEED'],
      supported: [{ pid: '0C', name: 'RPM', description: 'Engine RPM' }, { pid: '0D', name: 'SPEED', description: 'Speed' }],
    }),
  },
}))

import LiveView from '@/views/LiveView.vue'

function mountAt(id: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/vehicles/:id/live', name: 'live', component: LiveView },
    { path: '/vehicles/:id', name: 'vehicle', component: { template: '<div/>' } },
  ] })
  router.push(`/vehicles/${id}/live`)
  return router.isReady().then(() => mount(LiveView, { global: { plugins: [router] } }))
}

beforeEach(() => setActivePinia(createPinia()))

describe('LiveView', () => {
  it('lists the default (curated ∩ supported) PIDs and a start control', async () => {
    const wrapper = await mountAt('1')
    await flushPromises()
    expect(wrapper.text()).toContain('RPM')
    expect(wrapper.text()).toContain('SPEED')
    expect(wrapper.text().toLowerCase()).toContain('start')
    // a sparkline per PID row is rendered (stubbed chart)
    expect(wrapper.findAll('.v-chart-stub').length).toBeGreaterThanOrEqual(2)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- liveView`
Expected: FAIL — view/route missing.

- [ ] **Step 3: Implement `LiveView.vue`**

Create `frontend/src/views/LiveView.vue` (baseline — elevate visually with `frontend-design`, keep the logic + the rendered text/structure the test asserts):
```vue
<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import { useLiveSession } from '@/composables/useLiveSession'
import type { SupportedPid } from '@/api/types'
import LiveSparkline from '@/components/LiveSparkline.vue'
import LiveFocusChart from '@/components/LiveFocusChart.vue'

const route = useRoute()
const vehicleId = Number(route.params.id)
const live = useLiveSession(vehicleId)

const supported = ref<SupportedPid[]>([])
const available = ref(false)
const selected = ref<string[]>([])
const pinned = ref<string[]>([])

onMounted(async () => {
  const res = await api.getSupportedPids(vehicleId)
  available.value = res.available
  supported.value = res.supported
  const supportedNames = new Set(res.supported.map((p) => p.name))
  const defaults = res.curated.filter((p) => supportedNames.has(p))
  selected.value = defaults.length ? defaults : res.curated
  pinned.value = selected.value.slice(0, 1)
})

onUnmounted(() => live.stop())

const addable = computed(() =>
  supported.value.filter((p) => !selected.value.includes(p.name)),
)
const focusSeries = computed(() =>
  pinned.value.map((name) => ({ name, points: live.series[name] ?? [] })),
)

function toggleStart() {
  if (live.status.value === 'streaming' || live.status.value === 'connecting') live.stop()
  else live.start(selected.value)
}
function addPid(name: string) {
  if (!selected.value.includes(name)) selected.value.push(name)
}
function removePid(name: string) {
  selected.value = selected.value.filter((p) => p !== name)
  pinned.value = pinned.value.filter((p) => p !== name)
}
function togglePin(name: string) {
  pinned.value = pinned.value.includes(name)
    ? pinned.value.filter((p) => p !== name)
    : [...pinned.value, name]
}
function fmt(name: string): string {
  const v = live.latest[name]
  if (!v || v.value === null) return '—'
  return `${v.value}${v.unit ? ' ' + v.unit : ''}`
}
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-8">
    <RouterLink :to="{ name: 'vehicle', params: { id: vehicleId } }" class="mb-4 inline-block font-mono text-xs text-muted hover:text-text">← Vehicle</RouterLink>

    <header class="mb-6 flex items-center justify-between">
      <h1 class="text-xl font-semibold">Live data</h1>
      <div class="flex items-center gap-3 text-sm">
        <span class="text-muted">{{ live.status.value }}<template v-if="live.achievedHz.value"> · {{ live.achievedHz.value }} Hz</template></span>
        <button class="rounded bg-accent px-3 py-1.5 font-medium text-bg" @click="toggleStart">
          {{ live.status.value === 'streaming' || live.status.value === 'connecting' ? 'Stop' : 'Start' }}
        </button>
      </div>
    </header>

    <p v-if="live.vinMismatch.value" class="mb-4 rounded bg-warning/15 px-3 py-2 text-sm text-warning">
      {{ live.vinMismatch.value }}
    </p>
    <p v-if="live.status.value === 'error'" class="mb-4 rounded bg-danger/15 px-3 py-2 text-sm text-danger">
      {{ live.detail.value }}
    </p>

    <ul class="mb-6 divide-y divide-border rounded-card bg-surface">
      <li v-for="name in selected" :key="name" class="flex items-center gap-3 px-4 py-2">
        <span class="w-40 font-mono text-sm">{{ name }}</span>
        <span class="w-24 text-right tabular-nums">{{ fmt(name) }}</span>
        <LiveSparkline class="flex-1" :points="live.series[name] ?? []" />
        <button class="text-xs" :class="pinned.includes(name) ? 'text-accent' : 'text-muted'" @click="togglePin(name)">pin</button>
        <button class="text-xs text-muted hover:text-danger" @click="removePid(name)">✕</button>
      </li>
    </ul>

    <div class="mb-6">
      <label class="text-sm text-muted">+ Add PID
        <select class="ml-2 rounded bg-surface-2 px-2 py-1" @change="addPid(($event.target as HTMLSelectElement).value)">
          <option value="">…</option>
          <option v-for="p in addable" :key="p.name" :value="p.name">{{ p.name }}</option>
        </select>
      </label>
    </div>

    <LiveFocusChart v-if="pinned.length" :series="focusSeries" />
  </main>
</template>
```

- [ ] **Step 4: Add the route**

In `frontend/src/router/index.ts`, add:
```ts
    { path: '/vehicles/:id/live', name: 'live', component: () => import('@/views/LiveView.vue') },
```

- [ ] **Step 5: Add the entry link on the vehicle detail page**

In `frontend/src/views/VehicleDetailView.vue`, add a "Live data" link in the vehicle header block (after the `<h1>...</h1>` / engine span, inside the `v-else` header `div`):
```vue
      <RouterLink
        :to="{ name: 'live', params: { id: vehicleId } }"
        class="mt-3 inline-flex items-center gap-1.5 rounded bg-surface-2 px-3 py-1.5 font-mono text-xs text-accent hover:bg-surface"
      >
        ● Live data
      </RouterLink>
```
(Place it so it renders only once the vehicle has loaded; `vehicleId` is already in scope.)

- [ ] **Step 6: Run the tests + build**

Run (from `frontend/`): `npm test` → all green (liveView + prior).
Run: `npm run build` → succeeds.

- [ ] **Step 7: Commit**

```bash
cd .. && git add frontend/src/views/LiveView.vue frontend/src/router/index.ts frontend/src/views/VehicleDetailView.vue frontend/src/views/__tests__/liveView.test.ts
git commit -m "feat(web): Live view — vitals list, PID picker, focus chart, and entry link"
```

---

### Task 5: past-session replay

> **Use the `frontend-design` skill.** Logic + test are the contract.

**Files:**
- Create: `frontend/src/components/SessionHistory.vue`
- Modify: `frontend/src/views/LiveView.vue` (mount the history panel + a replay focus chart)
- Test: `frontend/src/components/__tests__/sessionHistory.test.ts`

**Interfaces:**
- Consumes: `api.listLiveSessions` / `api.getLiveSession` (Task 1), `LiveFocusChart` (Task 3).
- Produces: `SessionHistory` — props `{ vehicleId: number }`, emits `replay` with `{ name, points }[]` built from a chosen session's samples. It lists the vehicle's past sessions (id, status, sample_count, started time); selecting one loads `getLiveSession` and emits the per-PID series for the focus chart. `LiveView` renders it and, when a replay is active, shows the replayed series in a `LiveFocusChart`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/sessionHistory.test.ts`:
```ts
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => ({
  api: {
    listLiveSessions: vi.fn().mockResolvedValue([
      { id: 3, vehicle_id: 1, status: 'ended', started_utc: '2026-06-19T10:00:00Z', ended_utc: '2026-06-19T10:01:00Z', achieved_hz: 0.9, sample_count: 2, pids: ['RPM'] },
    ]),
    getLiveSession: vi.fn().mockResolvedValue({
      session: { id: 3, vehicle_id: 1, status: 'ended', pids: ['RPM'], sample_count: 2 },
      samples: [
        { seq: 1, t: 0, values: { RPM: { value: 800, unit: 'rpm' } } },
        { seq: 2, t: 1000, values: { RPM: { value: 820, unit: 'rpm' } } },
      ],
    }),
  },
}))

import SessionHistory from '@/components/SessionHistory.vue'

beforeEach(() => vi.clearAllMocks())

describe('SessionHistory', () => {
  it('lists sessions and emits replay series for a chosen session', async () => {
    const wrapper = mount(SessionHistory, { props: { vehicleId: 1 } })
    await flushPromises()
    expect(wrapper.text()).toContain('#3')          // session id shown
    expect(wrapper.text().toLowerCase()).toContain('ended')

    await wrapper.find('button[data-session="3"]').trigger('click')
    await flushPromises()

    const emitted = wrapper.emitted('replay')
    expect(emitted).toBeTruthy()
    const series = emitted![0][0] as { name: string; points: [number, number][] }[]
    expect(series[0].name).toBe('RPM')
    expect(series[0].points).toEqual([[0, 800], [1000, 820]])
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm test -- sessionHistory`
Expected: FAIL — component missing.

- [ ] **Step 3: Implement `SessionHistory.vue`**

Create `frontend/src/components/SessionHistory.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import type { LiveSessionSummary } from '@/api/types'

const props = defineProps<{ vehicleId: number }>()
const emit = defineEmits<{ replay: [series: { name: string; points: [number, number][] }[]] }>()

const sessions = ref<LiveSessionSummary[]>([])

onMounted(async () => {
  sessions.value = await api.listLiveSessions(props.vehicleId)
})

async function open(id: number) {
  const detail = await api.getLiveSession(id)
  const series = detail.session.pids.map((name) => ({
    name,
    points: detail.samples
      .map((s) => {
        const v = s.values[name]
        return v && typeof v.value === 'number' ? ([s.t, v.value] as [number, number]) : null
      })
      .filter((p): p is [number, number] => p !== null),
  }))
  emit('replay', series)
}
</script>

<template>
  <section>
    <h2 class="mb-2 font-medium">Past sessions</h2>
    <ul v-if="sessions.length" class="space-y-1">
      <li v-for="s in sessions" :key="s.id">
        <button
          :data-session="s.id"
          class="flex w-full items-center justify-between rounded bg-surface px-3 py-2 text-left text-sm hover:bg-surface-2"
          @click="open(s.id)"
        >
          <span class="font-mono">#{{ s.id }}</span>
          <span class="text-muted">{{ s.status }} · {{ s.sample_count }} samples</span>
        </button>
      </li>
    </ul>
    <p v-else class="text-sm text-muted">No recorded sessions yet.</p>
  </section>
</template>
```

- [ ] **Step 4: Mount it in `LiveView` with a replay chart**

In `frontend/src/views/LiveView.vue`:
- Add to the script: an import + replay state:
```ts
import SessionHistory from '@/components/SessionHistory.vue'
const replaySeries = ref<{ name: string; points: [number, number][] }[]>([])
function onReplay(series: { name: string; points: [number, number][] }[]) {
  replaySeries.value = series
}
```
- Add to the template (after the live `LiveFocusChart`):
```vue
    <div class="mt-8">
      <SessionHistory :vehicle-id="vehicleId" @replay="onReplay" />
      <LiveFocusChart v-if="replaySeries.length" class="mt-3" :series="replaySeries" />
    </div>
```

- [ ] **Step 5: Run the tests + build**

Run (from `frontend/`): `npm test` → all green (sessionHistory + liveView + prior).
Run: `npm run build` → succeeds; `frontend/dist` produced.

- [ ] **Step 6: Commit**

```bash
cd .. && git add frontend/src/components/SessionHistory.vue frontend/src/views/LiveView.vue frontend/src/components/__tests__/sessionHistory.test.ts
git commit -m "feat(web): past-session history list with focus-chart replay"
```

---

## Manual smoke test (after all tasks)

Backend on (Plan A): `.env` with `OBD_MCP_ENABLED=true`, `OBD_MCP_DIR`, `OBD_PORT`, a running simulator/adapter.
```bash
uv run mechanic-sidekick-api            # :8000
cd frontend && npm run dev              # :5173
```
Open a vehicle → click **● Live data** → **Start**: rows show live values + sparklines, the achieved-Hz updates, the focus chart plots pinned PIDs; add/remove PIDs; **Stop**; then pick a past session under "Past sessions" and see it replay in the chart. Single-port: `npm run build` then open `http://127.0.0.1:8000`.

## Self-review

**Spec coverage (design spec §Frontend — Live view):**
- `useLiveSession` over the generalized SSE reader, rolling buffers, connection/VIN/Hz state → Tasks 1–2. ✔
- Dense vitals list (value + per-row mini chart), "+ Add PID" picker over supported PIDs, large focus chart for pinned PID(s), header status → Tasks 3–4. ✔
- Route `/vehicles/:id/live` + entry from vehicle detail + per-vehicle scanner cue → Task 4. ✔
- ECharts (vue-echarts, tree-shaken, SVG) → Task 1 setup + Task 3 components. ✔
- Light past-session list + replay in the focus chart → Task 5. ✔
- Out of scope: Phase 3 copilot (commentary/guided actions/report). Correctly excluded.

**Placeholder scan:** every code step is complete; every test asserts behavior; view tasks carry a working baseline template + the `frontend-design` note (elevation, not missing code). No TBD/TODO. ✔

**Type/interface consistency:**
- `streamLive(vehicleId, pids, onEvent, signal?)` + the `LiveEvent` union match between Task 1 (def), the Task 2 composable, and their test mocks. ✔
- `useLiveSession` return shape (`status/detail/vinMismatch/achievedHz/sessionId/activePids/latest/series/start/stop`) matches between Task 2 (def) and Task 4 (use). ✔
- `LiveSparkline {points}` / `LiveFocusChart {series:{name,points}[]}` props match between Task 3 (def) and Tasks 4–5 (use). ✔
- `api.getSupportedPids/listLiveSessions/getLiveSession` + the `SupportedPids`/`LiveSessionSummary`/`LiveSessionDetail` types match between Task 1 (def) and Tasks 4–5 (use), and mirror the backend contract table. ✔
- `SessionHistory` emits `replay` with `{name,points}[]` consumed by Task 5's `onReplay` → `LiveFocusChart`. ✔
- The `[t, value]` point shape is identical across the composable buffers, the sparkline/focus props, and the replay mapping. ✔
```
