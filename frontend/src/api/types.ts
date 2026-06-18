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
