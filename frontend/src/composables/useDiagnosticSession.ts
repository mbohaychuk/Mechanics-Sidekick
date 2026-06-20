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
        state: event.state, adhoc: event.adhoc,
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
