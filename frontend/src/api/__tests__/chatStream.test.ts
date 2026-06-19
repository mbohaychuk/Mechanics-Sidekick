import { describe, it, expect, vi, afterEach } from 'vitest'
import { streamChatMessage, type ChatStreamEvent } from '@/api/chatStream'

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

describe('streamChatMessage', () => {
  it('parses token, tool, sources, and done frames in order', async () => {
    const frames = [
      'data: {"type":"tool_call","name":"search_manuals","arguments":{"query":"oil"}}\n\n',
      'data: {"type":"tool_result","name":"search_manuals"}\n\n',
      'data: {"type":"token","text":"Use "}\n\n',
      'data: {"type":"token","text":"5W-30."}\n\n',
      'data: {"type":"sources","sources":[{"filename":"m.pdf","page":3}]}\n\n',
      'data: {"type":"done"}\n\n',
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream(frames),
    } as unknown as Response))

    const events: ChatStreamEvent[] = []
    await streamChatMessage(1, 'what oil?', (e) => events.push(e))

    expect(events.map((e) => e.type)).toEqual([
      'tool_call', 'tool_result', 'token', 'token', 'sources', 'done',
    ])
    const tokens = events.filter((e) => e.type === 'token').map((e) => (e as { text: string }).text)
    expect(tokens.join('')).toBe('Use 5W-30.')
  })

  it('handles a frame split across two stream chunks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: sseStream(['data: {"type":"to', 'ken","text":"hi"}\n\n', 'data: {"type":"done"}\n\n']),
    } as unknown as Response))

    const events: ChatStreamEvent[] = []
    await streamChatMessage(1, 'x', (e) => events.push(e))

    expect(events[0]).toEqual({ type: 'token', text: 'hi' })
    expect(events[1]).toEqual({ type: 'done' })
  })

  it('throws on a non-OK response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, body: null } as Response))
    await expect(streamChatMessage(1, 'x', () => {})).rejects.toBeTruthy()
  })
})
