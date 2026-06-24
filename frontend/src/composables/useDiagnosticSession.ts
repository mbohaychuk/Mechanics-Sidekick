import { ref, reactive } from 'vue'
import { streamDiagnostic, type DiagnosticStreamEvent } from '@/api/diagnosticStream'
import { api } from '@/api/client'
import type { DiagnosticReport, DiagnosticReportSummary, LiveValue } from '@/api/types'

const WINDOW = 120

type DiagStatus = 'idle' | 'connecting' | 'running' | 'generating' | 'complete' | 'error'

interface StepView {
  id: string
  label: string
  instruction: string
  state: 'pending' | 'active' | 'done' | 'skipped'
  adhoc: boolean
}

export interface StepProgress {
  index: number
  id: string
  pid: string
  value: number | null
  target_low: number | null
  target_high: number | null
  in_range: boolean
  dwell_elapsed_s: number
  dwell_required_s: number
}

export function useDiagnosticSession(vehicleId: number) {
  const status = ref<DiagStatus>('idle')
  const detail = ref('')
  const vinMismatch = ref('')
  const steps = ref<StepView[]>([])
  const currentIndex = ref(-1)
  const commentary = ref<{ text: string; t: number }[]>([])
  const progress = ref<StepProgress | null>(null)
  const anomalies = ref<{ system: string; severity: string; detail: string }[]>([])
  const report = ref<DiagnosticReport | null>(null)
  const pastReports = ref<DiagnosticReportSummary[]>([])
  const viewedReport = ref<DiagnosticReport | null>(null)
  const pastError = ref('')
  const latest = reactive<Record<string, LiveValue | null>>({})
  const series = reactive<Record<string, [number, number][]>>({})

  let controller: AbortController | null = null

  function onEvent(event: DiagnosticStreamEvent) {
    if (event.type === 'session') {
      status.value = 'running'
      steps.value = event.protocol.map((s) => ({
        id: s.id, label: s.label, instruction: s.instruction, state: 'pending', adhoc: false,
      }))
      if (event.vin_mismatch) vinMismatch.value = event.vin_mismatch
    } else if (event.type === 'step') {
      currentIndex.value = event.index
      progress.value = null  // step boundary — clear the live gauge until the next sample
      const existing = steps.value[event.index]
      const view: StepView = {
        id: event.id, label: event.label, instruction: event.instruction,
        state: event.state, adhoc: event.adhoc,
      }
      if (existing) steps.value[event.index] = view
      else steps.value.splice(event.index, 0, view)
    } else if (event.type === 'step_progress') {
      progress.value = {
        index: event.index, id: event.id, pid: event.pid, value: event.value,
        target_low: event.target_low, target_high: event.target_high, in_range: event.in_range,
        dwell_elapsed_s: event.dwell_elapsed_s, dwell_required_s: event.dwell_required_s,
      }
    } else if (event.type === 'sample') {
      for (const [pid, v] of Object.entries(event.values)) {
        latest[pid] = v
        if (v && typeof v.value === 'number') {
          const buf = series[pid] ?? (series[pid] = [])
          buf.push([event.t, v.value])
          if (buf.length > WINDOW) buf.splice(0, buf.length - WINDOW)
        }
      }
    } else if (event.type === 'generating') {
      status.value = 'generating'  // phase 3: steps done, building the report
      progress.value = null
    } else if (event.type === 'commentary') {
      commentary.value.push({ text: event.text, t: event.t })
    } else if (event.type === 'anomaly') {
      anomalies.value.push({ system: event.system, severity: event.severity, detail: event.detail })
    } else if (event.type === 'report') {
      report.value = { overall_status: event.overall_status, summary: event.summary, findings: event.findings }
    } else if (event.type === 'done') {
      if (status.value !== 'error') status.value = 'complete'
      void loadPastReports()
    } else if (event.type === 'error') {
      status.value = 'error'
      detail.value = event.detail
    }
  }

  async function start(protocol = 'default') {
    stop()
    status.value = 'connecting'
    detail.value = ''
    vinMismatch.value = ''
    steps.value = []
    commentary.value = []
    anomalies.value = []
    report.value = null
    viewedReport.value = null
    progress.value = null
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

  async function loadPastReports() {
    pastError.value = ''
    try {
      pastReports.value = await api.listDiagnosticReports(vehicleId)
    } catch (err) {
      pastError.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function viewReport(sessionId: number) {
    pastError.value = ''
    try {
      viewedReport.value = (await api.getDiagnosticSession(sessionId)).report
    } catch (err) {
      pastError.value = err instanceof Error ? err.message : String(err)
    }
  }

  return {
    status, detail, vinMismatch, steps, currentIndex, commentary, anomalies, report, latest, series,
    progress, pastReports, viewedReport, pastError, start, stop, loadPastReports, viewReport,
  }
}
