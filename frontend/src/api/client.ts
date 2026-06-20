import type {
  AppConfig, ChatMessage, DiagnosticReportSummary, DiagnosticSessionDetail, Document, Job,
  JobCreate, LiveSessionDetail, LiveSessionSummary, ScannerStatus, SupportedPids, Vehicle,
  VehicleCreate,
} from '@/api/types'

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
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

  getSupportedPids: (vehicleId: number) =>
    request<SupportedPids>(`/api/vehicles/${vehicleId}/supported-pids`),
  listLiveSessions: (vehicleId: number) =>
    request<LiveSessionSummary[]>(`/api/vehicles/${vehicleId}/sessions`),
  getLiveSession: (sessionId: number) =>
    request<LiveSessionDetail>(`/api/sessions/${sessionId}`),

  listDiagnosticReports: (vehicleId: number) =>
    request<DiagnosticReportSummary[]>(`/api/vehicles/${vehicleId}/diagnostic-reports`),
  getDiagnosticSession: (sessionId: number) =>
    request<DiagnosticSessionDetail>(`/api/diagnostic-sessions/${sessionId}`),
}
