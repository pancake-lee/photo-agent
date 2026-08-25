import { ref, onUnmounted } from 'vue'
import { getAgentBase, EMBED_POLL_INTERVAL } from '../config'
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
let usageCount = 0

// 单张 Embed 处理进度跟踪（纯内存状态，由后端 /api/embed/progress 驱动）
const embedProcessingIds = ref<Set<string>>(new Set())
let embedProgressTimer: ReturnType<typeof setInterval> | null = null

export function useEmbedQueue() {
  async function fetchStatus() {
    try {
      const resp = await fetch(`${getAgentBase()}/embed/queue/status`)
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
    } catch (e) {
      // Agent 可能未启动，轮询 404 属于预期行为
      console.debug('Embed 队列状态查询失败', e)
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
    const resp = await fetch(`${getAgentBase()}/embed/queue/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.error || err.detail || '启动失败')
    }
    const data = await resp.json()
    startPolling()
    return data
  }

  async function stopQueue() {
    try {
      await fetch(`${getAgentBase()}/embed/queue/stop`, { method: 'POST' })
      stopPolling()
      status.value = { running: false, total: 0, completed: 0, failed: 0 }
    } catch (e) {
      console.debug('Embed 队列停止失败', e)
    }
  }

  async function enqueuePhoto(photoId: string) {
    const resp = await fetch(`${getAgentBase()}/embed/photos/${photoId}`, {
      method: 'POST',
    })
    if (!resp.ok) throw new Error('入队失败')
    return await resp.json()
  }

  // 连拍组重建后同步组向量集合：复用全量集合的封面向量，不重跑 Embedding
  async function syncGroupCollections(): Promise<Record<string, number>> {
    const resp = await fetch(`${getAgentBase()}/embed/groups/sync`, {
      method: 'POST',
    })
    if (!resp.ok) throw new Error('连拍组向量同步失败')
    return await resp.json()
  }

  async function fetchEmbedProgress() {
    try {
      const resp = await fetch(`${getAgentBase()}/embed/progress`)
      if (!resp.ok) return
      const data: { processing_ids: string[] } = await resp.json()
      const ids = new Set(data.processing_ids || [])
      embedProcessingIds.value = ids
      if (ids.size > 0 && !embedProgressTimer) {
        embedProgressTimer = setInterval(fetchEmbedProgress, EMBED_POLL_INTERVAL)
      } else if (ids.size === 0) {
        stopEmbedProgressPolling()
      }
    } catch (e) {
      console.debug('Embed 进度查询失败', e)
    }
  }

  function stopEmbedProgressPolling() {
    if (embedProgressTimer) {
      clearInterval(embedProgressTimer)
      embedProgressTimer = null
    }
  }

  function onComplete(fn: (() => void) | null) {
    onCompleteCallback = fn
  }

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
    syncGroupCollections,
    onComplete,
    embedProcessingIds,
    fetchEmbedProgress,
    stopEmbedProgressPolling,
  }
}
