import { ref } from 'vue'
import type {
  Session,
  ChatMessage,
  ChatSessionDetail,
  SendMessageResponse,
} from '../types/chat'

const API_PREFIX = '/api/chat'

// ── 响应式状态 ──

const sessions = ref<Session[]>([])
const messages = ref<ChatMessage[]>([])
const currentSession = ref<Session | null>(null)
const isLoading = ref(false)

// ── API 方法 ──

async function fetchSessions() {
  try {
    const resp = await fetch(`${API_PREFIX}/sessions`)
    if (resp.ok) {
      sessions.value = await resp.json()
    }
  } catch {
    // 静默失败，sessions 保持旧值
  }
}

async function createSession(): Promise<string> {
  const resp = await fetch(`${API_PREFIX}/sessions`, {
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
    const resp = await fetch(`${API_PREFIX}/sessions/${sessionId}`)
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
      `${API_PREFIX}/sessions/${sessionId}/messages`,
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
  const resp = await fetch(`${API_PREFIX}/sessions/${sessionId}`, {
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
    resetChat,
  }
}
