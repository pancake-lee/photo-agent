import { ref, computed } from 'vue'
import { AGENT_BASE } from '../config'
import type {
  HistoryItem,
  SuggestHistoryDetail,
  SuggestVersion,
  PipelineStep,
  RerunRequest,
  ManualSuggestRequest,
  RandomSampleResult,
} from '../types/suggest'

// ── 状态 ──

const detailLoading = ref(false)
const detail = ref<SuggestHistoryDetail | null>(null)
const detailError = ref('')
const rerunLoading = ref(false)
const manualLoading = ref(false)

// 当前活跃版本（computed）
const currentVersion = computed<SuggestVersion | null>(() => {
  if (!detail.value) return null
  const vid = detail.value.current_version_id
  return detail.value.versions.find(v => v.version_id === vid) || null
})

// 当前版本的步骤按 group 分组
const stepGroups = computed<Array<{ group: string; steps: PipelineStep[] }>>(() => {
  const ver = currentVersion.value
  if (!ver || !ver.steps) return []
  const map = new Map<string, PipelineStep[]>()
  for (const s of ver.steps) {
    const key = s.group || '其他'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(s)
  }
  return Array.from(map.entries()).map(([group, steps]) => ({ group, steps }))
})

// 所有版本按时间排序
const sortedVersions = computed<SuggestVersion[]>(() => {
  if (!detail.value) return []
  return [...detail.value.versions].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  )
})

// ── API 调用 ──

async function loadDetail(itemId: string): Promise<SuggestHistoryDetail | null> {
  detailLoading.value = true
  detailError.value = ''
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/history/${itemId}/detail`)
    if (resp.ok) {
      const data = await resp.json()
      detail.value = data
      return data
    }
    const err = await resp.json().catch(() => ({}))
    detailError.value = err.detail || '加载详情失败'
    return null
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : '网络请求失败'
    return null
  } finally {
    detailLoading.value = false
  }
}

async function switchVersion(itemId: string, versionId: string): Promise<boolean> {
  if (!detail.value) return false
  try {
    const resp = await fetch(
      `${AGENT_BASE}/suggest/history/${itemId}/version/${versionId}/switch`,
      { method: 'PATCH' }
    )
    if (resp.ok) {
      const data = await resp.json()
      detail.value.current_version_id = data.current_version_id
      return true
    }
    return false
  } catch {
    return false
  }
}

async function rerunFromStep(itemId: string, fromStep: string, overrides: Record<string, any>): Promise<SuggestHistoryDetail | null> {
  rerunLoading.value = true
  try {
    const body: RerunRequest = { from_step: fromStep, overrides }
    const resp = await fetch(`${AGENT_BASE}/suggest/history/${itemId}/rerun`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      const data = await resp.json()
      detail.value = data
      return data
    }
    const err = await resp.json().catch(() => ({}))
    detailError.value = err.detail || '重跑失败'
    return null
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : '重跑失败'
    return null
  } finally {
    rerunLoading.value = false
  }
}

async function manualRun(req: ManualSuggestRequest): Promise<SuggestHistoryDetail | null> {
  manualLoading.value = true
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/manual-run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    if (resp.ok) {
      const data = await resp.json()
      detail.value = data
      return data
    }
    const err = await resp.json().catch(() => ({}))
    detailError.value = err.detail || '手动选题失败'
    return null
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : '请求失败'
    return null
  } finally {
    manualLoading.value = false
  }
}

async function randomSample(): Promise<RandomSampleResult | null> {
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/random-sample`, { method: 'POST' })
    if (resp.ok) {
      return await resp.json()
    }
    return null
  } catch {
    return null
  }
}

function resetDetail() {
  detail.value = null
  detailError.value = ''
}

// ── 导出 ──

export function useSuggestDetail() {
  return {
    // state
    detailLoading,
    detail,
    detailError,
    rerunLoading,
    manualLoading,
    // computed
    currentVersion,
    stepGroups,
    sortedVersions,
    // actions
    loadDetail,
    switchVersion,
    rerunFromStep,
    manualRun,
    randomSample,
    resetDetail,
  }
}
