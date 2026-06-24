import { consumeSseStream } from '@/api/sse'
import type { DiagnosticReport, LiveValue } from '@/api/types'

export type DiagnosticStreamEvent =
  | { type: 'session'; diagnostic_session_id: number; live_session_id: number;
      protocol: { id: string; label: string; instruction: string }[]; vin_mismatch?: string }
  | { type: 'sample'; seq: number; t: number; hz: number; values: Record<string, LiveValue | null> }
  | { type: 'step'; index: number; total: number; id: string; label: string;
      instruction: string; state: 'active' | 'done' | 'skipped'; adhoc: boolean }
  | { type: 'step_progress'; index: number; id: string; pid: string; value: number | null;
      target_low: number | null; target_high: number | null; in_range: boolean;
      dwell_elapsed_s: number; dwell_required_s: number }
  | { type: 'generating' }
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
  await consumeSseStream<DiagnosticStreamEvent>(response.body, onEvent)
}
