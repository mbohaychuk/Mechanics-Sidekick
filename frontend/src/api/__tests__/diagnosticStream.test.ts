import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamDiagnostic, type DiagnosticStreamEvent } from '@/api/diagnosticStream'

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame))
      controller.close()
    },
  })
}

afterEach(() => vi.restoreAllMocks())

describe('streamDiagnostic', () => {
  it('parses session, step, commentary, report, done in order', async () => {
    const frames = [
      'data: {"type":"session","diagnostic_session_id":3,"live_session_id":9,"protocol":[{"id":"idle_baseline","label":"Idle","instruction":"idle"}]}\n\n',
      'data: {"type":"step","index":0,"total":1,"id":"idle_baseline","label":"Idle","instruction":"idle","state":"active","adhoc":false}\n\n',
      'data: {"type":"commentary","text":"Idle looks steady.","t":1000}\n\n',
      'data: {"type":"report","overall_status":"fair","summary":"ok","findings":[]}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body: sseStream(frames),
    } as unknown as Response))

    const events: DiagnosticStreamEvent[] = []
    await streamDiagnostic(1, 'default', (e) => events.push(e))
    expect(events.map((e) => e.type)).toEqual(['session', 'step', 'commentary', 'report', 'done'])
  })

  it('handles a frame split across two chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream(['data: {"type":"comm', 'entary","text":"hi","t":0}\n\n', 'data: {"type":"done"}\n\n']),
    } as unknown as Response))
    const events: DiagnosticStreamEvent[] = []
    await streamDiagnostic(1, 'default', (e) => events.push(e))
    expect(events[0]).toEqual({ type: 'commentary', text: 'hi', t: 0 })
    expect(events[1]).toEqual({ type: 'done' })
  })

  it('throws on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as Response))
    await expect(streamDiagnostic(1, 'default', () => {})).rejects.toBeTruthy()
  })
})
