import { consumeSseStream } from '@/api/sse'

export type ChatStreamEvent =
  | { type: 'token'; text: string }
  | { type: 'tool_call'; name: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; name: string }
  | { type: 'sources'; sources: Array<Record<string, unknown>> }
  | { type: 'done' }
  | { type: 'error'; detail: string }

export async function streamChatMessage(
  jobId: number,
  content: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/jobs/${jobId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status}`)
  }
  await consumeSseStream<ChatStreamEvent>(response.body, onEvent)
}
