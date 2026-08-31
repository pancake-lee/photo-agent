import { ref } from 'vue'
import type {
  Session,
  ChatMessage,
  ChatSessionDetail,
  SendMessageResponse,
  Granularity,
  RuntimeStep,
} from '../types/chat'

import { getAgentBase } from '../config'
import { createChatStreamParser } from '../utils/chatStream'

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
      last_granularity: data.last_granularity,
      message_count: data.messages.length,
      created_at: data.created_at,
      updated_at: data.updated_at,
    }
    messages.value = data.messages
  } finally {
    isLoading.value = false
  }
}

async function sendMessage(
  question: string,
  granularity: Granularity = 'photo'
): Promise<SendMessageResponse> {
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
        body: JSON.stringify({ question, granularity }),
      }
    )
    if (!resp.ok) {
      const errText = await resp.text()
      throw new Error(errText || '请求失败')
    }
    if (!resp.body) throw new Error('服务未返回流式响应')
    const parser = createChatStreamParser()
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let runtimeMsg: ChatMessage | undefined
    let finalData: SendMessageResponse | undefined

    const applyEvent = (event: string, data: Record<string, unknown>) => {
      if (event === 'runtime.started') {
        runtimeMsg = {
          id: 0, session_id: sessionId, role: 'assistant', content: '',
          query_type: 'runtime', trace_id: String(data.trace_id || ''),
          granularity, photos: [], runtime_steps: [], created_at: new Date().toISOString(),
        }
        messages.value.push(runtimeMsg)
      }
      if (event === 'runtime.step' && runtimeMsg) {
        runtimeMsg.runtime_steps = (data.steps || []) as RuntimeStep[]
      }
      if (event === 'final') {
        finalData = data as unknown as SendMessageResponse
        const target: ChatMessage = runtimeMsg || {
          id: 0, session_id: sessionId, role: 'assistant' as const, content: '', created_at: new Date().toISOString(),
        }
        Object.assign(target, {
          id: finalData.message_id, content: finalData.answer, query_type: finalData.query_type,
          trace_id: finalData.trace_id, granularity: finalData.granularity,
          photos: finalData.photos || [], runtime_steps: finalData.runtime_steps || target.runtime_steps || [],
        })
        if (!runtimeMsg) messages.value.push(target)
      }
      if (event === 'error') throw new Error(String(data.message || '处理请求失败'))
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      for (const item of parser.push(decoder.decode(value, { stream: true }))) {
        applyEvent(item.event, item.data)
      }
    }
    if (!finalData) throw new Error('服务未返回最终结果')

    // 更新会话标题（首条消息后标题可能已变）
    if (currentSession.value) {
      currentSession.value.message_count = messages.value.length
    }

    // 刷新会话列表以获取更新的标题
    fetchSessions()

    return finalData
  } finally {
    isLoading.value = false
  }
}

async function updateLastGranularity(granularity: Granularity) {
  if (!currentSession.value) return
  const sessionId = currentSession.value.session_id
  const resp = await fetch(`${getAgentBase()}/chat/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ last_granularity: granularity }),
  })
  if (!resp.ok) throw new Error('保存检索粒度失败')
  currentSession.value.last_granularity = granularity
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
    updateLastGranularity,
    deleteSession,
    deleteSessions,
    resetChat,
  }
}
