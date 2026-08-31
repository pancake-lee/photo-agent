import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '../types/chat'
import { canSaveAsGoldenQuery } from './goldenQuery'

function reply(queryType?: string, withPhotos = true): ChatMessage {
  return {
    id: 1,
    session_id: 'session',
    role: 'assistant',
    content: '回答',
    query_type: queryType,
    photos: withPhotos ? [{ photo_id: 'photo', filename: 'photo.jpg', image_url: '' }] : [],
    created_at: '2026-08-31T00:00:00Z',
  }
}

describe('黄金用例保存资格', () => {
  it('仅允许带照片的 RAG 回复', () => {
    expect(canSaveAsGoldenQuery(reply('rag'))).toBe(true)
    expect(canSaveAsGoldenQuery(reply('rag', false))).toBe(false)
  })

  it.each(['runtime', 'sql', 'combined', 'tool', 'error', undefined])(
    '拒绝非 RAG 路由 %s',
    (queryType) => {
      expect(canSaveAsGoldenQuery(reply(queryType))).toBe(false)
    },
  )
})
