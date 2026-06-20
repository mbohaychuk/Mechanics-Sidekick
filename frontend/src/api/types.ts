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
