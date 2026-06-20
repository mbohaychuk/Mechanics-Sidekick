import type { DiagnosticReport, LiveValue } from '@/api/types'

export type DiagnosticStreamEvent =
  | { type: 'session'; diagnostic_session_id: number; live_session_id: number;
      protocol: { id: string; label: string; instruction: string }[]; vin_mismatch?: string }
  | { type: 'sample'; seq: number; t: number; hz: number; values: Record<string, LiveValue | null> }
  | { type: 'step'; index: number; total: number; id: string; label: string;
      instruction: string; state: 'active' | 'done' | 'skipped'; adhoc: boolean }
  | { type: 'commentary'; text: string; t: number }
  | { type: 'anomaly'; system: string; severity: string; pid: string; detail: string }
  | ({ type: 'report' } & DiagnosticReport)
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
