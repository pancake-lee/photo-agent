import type { ChatMessage } from '../types/chat'

/** 仅纯 RAG 的照片检索结果具备现有黄金用例的评估语义。 */
export function canSaveAsGoldenQuery(message: ChatMessage): boolean {
  return message.role === 'assistant'
    && message.query_type === 'rag'
    && Boolean(message.photos?.length)
}
