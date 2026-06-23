import { ref, onUnmounted } from 'vue'
import { AGENT_BASE, EMBED_POLL_INTERVAL } from '../config'
import type { EmbedQueueStatus } from '../types/photo'

// Embed 队列全局状态
const status = ref<EmbedQueueStatus>({
  running: false,
  total: 0,
  completed: 0,
  failed: 0,
  current_file: undefined,
})

const polling = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null
let onCompleteCallback: (() => void) | null = null

export function useEmbedQueue() {
  async function fetchStatus() {
    try {
      const resp = await fetch(`${AGENT_BASE}/embed/queue/status`)
      if (!resp.ok) return
      const data: EmbedQueueStatus = await resp.json()
      const wasRunning = status.value.running
      status.value = data

      // Embed 结束（从运行中变为未运行）时触发回调
      if (!data.running && wasRunning && onCompleteCallback) {
        onCompleteCallback()
      }

      // 自动停止轮询
      if (!data.running) {
        stopPolling()
      }
    } catch {
      // 静默失败（Agent 可能未启动）
    }
  }

  function startPolling() {
    if (pollTimer) return
    polling.value = true
    fetchStatus()
    pollTimer = setInterval(fetchStatus, EMBED_POLL_INTERVAL)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    polling.value = false
  }

  async function startQueue(force = false) {
    const resp = await fetch(`${AGENT_BASE}/embed/queue/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.error || err.detail || '启动失败')
    }
    const data = await resp.json()
    if (data.total > 0) {
      startPolling()
    }
    return data
  }

  async function stopQueue() {
    try {
      await fetch(`${AGENT_BASE}/embed/queue/stop`, { method: 'POST' })
      stopPolling()
      status.value = { running: false, total: 0, completed: 0, failed: 0 }
    } catch {
      // 静默失败
    }
  }

  async function enqueuePhoto(photoId: string) {
    const resp = await fetch(`${AGENT_BASE}/embed/photos/${photoId}`, {
      method: 'POST',
    })
    if (!resp.ok) throw new Error('入队失败')
    return await resp.json()
  }

  function onComplete(fn: (() => void) | null) {
    onCompleteCallback = fn
  }

  onUnmounted(() => {
    stopPolling()
  })

  return {
    status,
    polling,
    fetchStatus,
    startPolling,
    stopPolling,
    startQueue,
    stopQueue,
    enqueuePhoto,
    onComplete,
  }
}
