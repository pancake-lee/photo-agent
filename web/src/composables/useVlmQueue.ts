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
// VLM 完成回调（在队列运行结束或中止后触发）
let onCompleteCallback: (() => void) | null = null
// 组件引用计数：仅最后一个使用该 composable 的组件卸载时才停止轮询
let usageCount = 0

export function useVlmQueue() {
  async function fetchStatus() {
    try {
      const resp = await fetch(`${API_BASE}/vlm/queue/status`)
      if (!resp.ok) return
      const data: VlmQueueStatus = await resp.json()
      const wasRunning = status.value.running
      status.value = data

      // VLM 结束（从运行中变为未运行）时触发回调
      if (!data.running && wasRunning && onCompleteCallback) {
        onCompleteCallback()
      }

      // 自动停止轮询
      if (!data.running) {
        stopPolling()
      }
    } catch (e) {
      // Agent 可能未启动，轮询 404 属于预期行为
      console.debug('VLM 队列状态查询失败', e)
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
    } catch (e) {
      console.debug('VLM 队列停止失败', e)
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

  // 注册 VLM 完成回调（自动清除）
  function onComplete(fn: (() => void) | null) {
    onCompleteCallback = fn
  }

  // 组件卸载时递减引用计数，最后一个组件卸载时停止轮询
  usageCount++
  onUnmounted(() => {
    usageCount--
    if (usageCount <= 0) {
      usageCount = 0
      stopPolling()
    }
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
