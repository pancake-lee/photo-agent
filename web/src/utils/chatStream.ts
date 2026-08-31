export interface ChatStreamEvent {
  event: string
  data: Record<string, unknown>
}

/** 增量解析 fetch 响应中的 SSE 帧，兼容网络分段落在任意位置。 */
export function createChatStreamParser() {
  let buffer = ''

  function parseFrame(frame: string): ChatStreamEvent | null {
    const event = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim() || 'message'
    const rawData = frame.match(/^data:\s*(.+)$/m)?.[1]
    if (!rawData) return null
    try {
      const data = JSON.parse(rawData)
      return data && typeof data === 'object' ? { event, data } : null
    } catch {
      return null
    }
  }

  return {
    push(chunk: string): ChatStreamEvent[] {
      buffer += chunk.replace(/\r\n/g, '\n')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      return frames.map(parseFrame).filter((item): item is ChatStreamEvent => item !== null)
    },
  }
}
