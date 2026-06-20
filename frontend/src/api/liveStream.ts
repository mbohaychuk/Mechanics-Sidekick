import { consumeSseStream } from '@/api/sse'
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
  await consumeSseStream<LiveEvent>(response.body, onEvent)
}
