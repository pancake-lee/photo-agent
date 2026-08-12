import { ref } from 'vue'
import { getAgentBase } from '../config'
import type { EmbedStats, EmbedInfo } from '../types/photo'

// 全局嵌入状态（跨组件共享）
const embeddedIds = ref<Set<string>>(new Set())
const embedStats = ref<EmbedStats | null>(null)

export function useEmbedStatus() {
  /**
   * 批量查询照片是否已嵌入。
   * 传入当前页的 photo ID 列表，返回一个 Set 表示哪些 ID 有 embedding。
   */
  async function fetchEmbeddedIds(photoIds: string[]) {
    if (!photoIds.length) {
      embeddedIds.value = new Set()
      return
    }
    try {
      const resp = await fetch(`${getAgentBase()}/embed/photos/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: photoIds }),
      })
      if (!resp.ok) return
      const data: Record<string, boolean> = await resp.json()
      embeddedIds.value = new Set(
        Object.entries(data)
          .filter(([, v]) => v)
          .map(([k]) => k)
      )
    } catch {
      // Agent 未启动时静默失败
      embeddedIds.value = new Set()
    }
  }

  /**
   * 获取 Embedding 统计（以 Go 照片为索引源，交叉比对 ChromaDB）。
   *
   * 与旧版不同，此接口先查询 Go 后端全量照片 ID 再与 Chroma 交叉比对，
   * 因此返回的 with_embedding 只包含"Go 中存在且已嵌入"的照片。
   * 若 Go 后端不可达，返回 { error: "..." }。
   */
  async function fetchEmbedStats() {
    try {
      const resp = await fetch(`${getAgentBase()}/embed/stats`)
      if (!resp.ok) {
        embedStats.value = null
        return
      }
      const data = await resp.json()
      if (data.error) {
        // Go 后端不可达等错误，保留上一次的 stats 不清空
        console.warn('Embed stats 获取失败:', data.error)
        return
      }
      embedStats.value = data
    } catch {
      embedStats.value = null
    }
  }

  /**
   * 获取单张照片的 embedding 详情（模型、时间、分块数等）。
   */
  async function fetchEmbedInfo(photoId: string): Promise<EmbedInfo | null> {
    try {
      const resp = await fetch(`${getAgentBase()}/embed/photos/${photoId}`)
      if (!resp.ok) return null
      return await resp.json()
    } catch {
      return null
    }
  }

  return {
    embeddedIds,
    embedStats,
    fetchEmbeddedIds,
    fetchEmbedStats,
    fetchEmbedInfo,
  }
}
