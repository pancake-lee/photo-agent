import { ref, onUnmounted } from 'vue'
import { VLM_POLL_INTERVAL } from '../config'
import { vlmApi } from '../backend-sdk-client'
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
      const data = await vlmApi.vlmServiceGetVlmQueueStatus()
      const wasRunning = status.value.running
      const s = data.status
      status.value = {
        running: s?.running ?? false,
        total: s?.total ?? 0,
        completed: s?.completed ?? 0,
        failed: s?.failed ?? 0,
        current_file: s?.currentFile ?? undefined,
      }

      // VLM 结束（从运行中变为未运行）时触发回调
      if (!status.value.running && wasRunning && onCompleteCallback) {
        onCompleteCallback()
      }

      // 自动停止轮询
      if (!status.value.running) {
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
    const data = await vlmApi.vlmServiceStartVlmQueue({ force })
    if (data.total && data.total > 0) {
      startPolling()
    }
    return data
  }

  async function stopQueue() {
    await vlmApi.vlmServiceStopVlmQueue({})
    stopPolling()
    // 重置状态
    status.value = { running: false, total: 0, completed: 0, failed: 0 }
  }

  async function enqueuePhoto(photoId: string) {
    return vlmApi.vlmServiceDescribePhoto({ id: photoId }, photoId)
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
