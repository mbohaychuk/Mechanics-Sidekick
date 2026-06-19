import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamLive } from '@/api/liveStream'
import type { LiveEvent } from '@/api/types'

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({ start(c) { for (const f of frames) c.enqueue(enc.encode(f)); c.close() } })
}
afterEach(() => vi.restoreAllMocks())

describe('streamLive', () => {
  it('GETs the live URL with pids and parses events in order', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream([
        'data: {"type":"session","session_id":7,"target_hz":1.0}\n\n',
        'data: {"type":"sample","seq":1,"t":0,"hz":1.0,"values":{"RPM":{"value":820,"unit":"rpm"}}}\n\n',
        'data: {"type":"disconnected","detail":"adapter dropped"}\n\n',
      ]),
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    const events: LiveEvent[] = []
    await streamLive(1, ['RPM', 'SPEED'], (e) => events.push(e))

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/vehicles/1/live?pids=RPM%2CSPEED')
    expect(events.map((e) => e.type)).toEqual(['session', 'sample', 'disconnected'])
    expect((events[1] as { values: Record<string, { value: number }> }).values.RPM.value).toBe(820)
  })

  it('throws on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409, body: null } as Response))
    await expect(streamLive(1, ['RPM'], () => {})).rejects.toBeTruthy()
  })
})
