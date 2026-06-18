import { ref, onUnmounted } from 'vue'
import { API_BASE, VLM_POLL_INTERVAL } from '../config'
import type { VlmQueueStatus } from '../types/photo'

// VLM 队列全局状态
const status = ref<VlmQueueStatus>({
  running: false,
  total: 0,
  completed: 0,
  failed: 0,
  current_file: undefined,
})

const polling = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

export function useVlmQueue() {
  async function fetchStatus() {
    try {
      const resp = await fetch(`${API_BASE}/vlm/queue/status`)
      if (!resp.ok) return
      const data: VlmQueueStatus = await resp.json()
      status.value = data

      // 自动停止轮询
      if (!data.running) {
        stopPolling()
      }
    } catch {
      // 静默失败
    }
  }

  function startPolling() {
    if (pollTimer) return
    polling.value = true
    fetchStatus() // 立即请求一次
    pollTimer = setInterval(fetchStatus, VLM_POLL_INTERVAL)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    polling.value = false
  }

  async function startQueue(force = false) {
    try {
      const resp = await fetch(`${API_BASE}/vlm/queue/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.error || '启动失败')
      }
      const data = await resp.json()
      if (data.total > 0) {
        startPolling()
      }
      return data
    } catch (e) {
      throw e
    }
  }

  async function stopQueue() {
    try {
      await fetch(`${API_BASE}/vlm/queue/stop`, { method: 'POST' })
      stopPolling()
      // 重置状态
      status.value = { running: false, total: 0, completed: 0, failed: 0 }
    } catch {
      // 静默失败
    }
  }

  async function enqueuePhoto(photoId: string) {
    try {
      const resp = await fetch(`${API_BASE}/photos/${photoId}/describe`, {
        method: 'POST',
      })
      if (!resp.ok) throw new Error('入队失败')
      return await resp.json()
    } catch (e) {
      throw e
    }
  }

  // 组件卸载时自动清理
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
  }
}
