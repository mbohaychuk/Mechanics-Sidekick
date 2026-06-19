import { ref, reactive } from 'vue'
import { streamLive } from '@/api/liveStream'
import type { LiveEvent, LiveValue } from '@/api/types'

const WINDOW = 120

type LiveStatus = 'idle' | 'connecting' | 'streaming' | 'error'

export function useLiveSession(vehicleId: number) {
  const status = ref<LiveStatus>('idle')
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
      // Stream ended cleanly — set idle unless an error event already set error state.
      const current = status.value as LiveStatus
      if (current !== 'error') status.value = 'idle'
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
    const current = status.value as LiveStatus
    if (current !== 'error') status.value = 'idle'
  }

  return { status, detail, vinMismatch, achievedHz, sessionId, activePids, latest, series, start, stop }
}
