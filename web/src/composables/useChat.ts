import { ref } from 'vue'
import type {
  Session,
  ChatMessage,
  ChatSessionDetail,
  SendMessageResponse,
} from '../types/chat'

import { getAgentBase } from '../config'

// ── 响应式状态 ──

const sessions = ref<Session[]>([])
const messages = ref<ChatMessage[]>([])
const currentSession = ref<Session | null>(null)
const isLoading = ref(false)

// ── API 方法 ──

async function fetchSessions() {
  try {
    const resp = await fetch(`${getAgentBase()}/chat/sessions`)
    if (resp.ok) {
      sessions.value = await resp.json()
    }
  } catch (e) {
    console.warn('获取会话列表失败', e)
  }
}

async function createSession(): Promise<string> {
  const resp = await fetch(`${getAgentBase()}/chat/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!resp.ok) {
    throw new Error('创建会话失败')
  }
  const data: Session = await resp.json()
  sessions.value.unshift({ ...data, message_count: 0 })
  return data.session_id
}

async function loadSession(sessionId: string) {
  isLoading.value = true
  try {
    const resp = await fetch(`${getAgentBase()}/chat/sessions/${sessionId}`)
    if (!resp.ok) {
      throw new Error('会话不存在')
    }
    const data: ChatSessionDetail = await resp.json()
    currentSession.value = {
      session_id: data.session_id,
      title: data.title,
      message_count: data.messages.length,
      created_at: data.created_at,
      updated_at: data.updated_at,
    }
    messages.value = data.messages
  } finally {
    isLoading.value = false
  }
}

async function sendMessage(question: string): Promise<SendMessageResponse> {
  if (!currentSession.value) {
    throw new Error('没有活动会话')
  }
  const sessionId = currentSession.value.session_id

  // 添加用户消息（乐观更新）
  const userMsg: ChatMessage = {
    id: 0,
    session_id: sessionId,
    role: 'user',
    content: question,
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMsg)
  isLoading.value = true

  try {
    const resp = await fetch(
      `${getAgentBase()}/chat/sessions/${sessionId}/messages`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      }
    )
    if (!resp.ok) {
      const errText = await resp.text()
      throw new Error(errText || '请求失败')
    }
    const data: SendMessageResponse = await resp.json()

    // 添加 AI 回复
    const aiMsg: ChatMessage = {
      id: data.message_id,
      session_id: sessionId,
      role: 'assistant',
      content: data.answer,
      query_type: data.query_type,
      photos: data.photos || [],
      created_at: new Date().toISOString(),
    }
    messages.value.push(aiMsg)

    // 更新会话标题（首条消息后标题可能已变）
    if (currentSession.value) {
      currentSession.value.message_count = messages.value.length
    }

    // 刷新会话列表以获取更新的标题
    fetchSessions()

    return data
  } finally {
    isLoading.value = false
  }
}

async function deleteSession(sessionId: string) {
  const resp = await fetch(`${getAgentBase()}/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  })
  if (!resp.ok) {
    throw new Error('删除失败')
  }
  sessions.value = sessions.value.filter((s) => s.session_id !== sessionId)
  if (currentSession.value?.session_id === sessionId) {
    currentSession.value = null
    messages.value = []
  }
}

// 批量删除：串行逐个调用，返回成功/失败计数。不因单个失败中断。
async function deleteSessions(sessionIds: string[]): Promise<{ ok: number; fail: number }> {
  let ok = 0
  let fail = 0
  for (const id of sessionIds) {
    try {
      await deleteSession(id)
      ok++
    } catch {
      fail++
    }
  }
  return { ok, fail }
}

function resetChat() {
  currentSession.value = null
  messages.value = []
}

export function useChat() {
  return {
    sessions,
    messages,
    currentSession,
    isLoading,
    fetchSessions,
    createSession,
    loadSession,
    sendMessage,
    deleteSession,
    deleteSessions,
    resetChat,
  }
}
