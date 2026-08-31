import { describe, expect, it } from 'vitest'
import { createChatStreamParser } from './chatStream'

describe('chat SSE parser', () => {
  it('reconstructs a split Runtime step event', () => {
    const parser = createChatStreamParser()
    expect(parser.push('event: runtime.step\ndata: {"steps":[')).toEqual([])
    expect(parser.push('{"step":1,"title":"查询照片"}]}\n\n')).toEqual([{
      event: 'runtime.step',
      data: { steps: [{ step: 1, title: '查询照片' }] },
    }])
  })

  it('ignores malformed frames and accepts final results', () => {
    const parser = createChatStreamParser()
    const events = parser.push('event: runtime.step\ndata: nope\n\nevent: final\ndata: {"answer":"完成"}\n\n')
    expect(events).toEqual([{ event: 'final', data: { answer: '完成' } }])
  })
})
