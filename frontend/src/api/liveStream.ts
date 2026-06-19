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
