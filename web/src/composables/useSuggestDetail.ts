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
  RerunProgress,
} from '../types/suggest'

// ── 状态 ──

const detailLoading = ref(false)
const detail = ref<SuggestHistoryDetail | null>(null)
const detailError = ref('')
const rerunLoading = ref(false)
const manualLoading = ref(false)
const rerunProgress = ref<RerunProgress | null>(null)

// 版本对比状态
const compareMode = ref(false)
const selectedCompareVersions = ref<string[]>([])

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

/** SSE 版本的 rerun，推送阶段进度。*/
async function rerunFromStepStream(
  itemId: string,
  fromStep: string,
  overrides: Record<string, any>,
): Promise<SuggestHistoryDetail | null> {
  rerunLoading.value = true
  rerunProgress.value = null

  try {
    const body: RerunRequest = { from_step: fromStep, overrides }
    const resp = await fetch(`${AGENT_BASE}/suggest/history/${itemId}/rerun-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      detailError.value = err.detail || '重跑失败'
      return null
    }

    const reader = resp.body?.getReader()
    if (!reader) {
      detailError.value = '浏览器不支持流式读取'
      return null
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6))
            if (event.event === 'progress') {
              rerunProgress.value = event.data as RerunProgress
            } else if (event.event === 'complete') {
              rerunProgress.value = null
              detail.value = event.data as SuggestHistoryDetail
              return event.data as SuggestHistoryDetail
            } else if (event.event === 'error') {
              detailError.value = event.data?.message || '重跑失败'
              return null
            }
          } catch {
            // skip unparseable lines
          }
        }
      }
    }

    return null
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : '重跑失败'
    return null
  } finally {
    rerunLoading.value = false
    rerunProgress.value = null
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
  compareMode.value = false
  selectedCompareVersions.value = []
}

// 版本对比相关
function toggleCompareMode() {
  compareMode.value = !compareMode.value
  selectedCompareVersions.value = []
}

function toggleCompareVersion(versionId: string) {
  const idx = selectedCompareVersions.value.indexOf(versionId)
  if (idx >= 0) {
    selectedCompareVersions.value.splice(idx, 1)
  } else {
    if (selectedCompareVersions.value.length >= 2) {
      selectedCompareVersions.value.shift()
    }
    selectedCompareVersions.value.push(versionId)
  }
}

const canCompare = computed(() => {
  if (!detail.value) return false
  return detail.value.versions.length >= 2
})

const compareVersions = computed<SuggestVersion[]>(() => {
  if (!detail.value || selectedCompareVersions.value.length < 2) return []
  return selectedCompareVersions.value
    .map(vid => detail.value!.versions.find(v => v.version_id === vid))
    .filter((v): v is SuggestVersion => v != null)
})

// ── 导出 ──

export function useSuggestDetail() {
  return {
    // state
    detailLoading,
    detail,
    detailError,
    rerunLoading,
    manualLoading,
    rerunProgress,
    compareMode,
    selectedCompareVersions,
    // computed
    currentVersion,
    stepGroups,
    sortedVersions,
    canCompare,
    compareVersions,
    // actions
    loadDetail,
    switchVersion,
    rerunFromStep,
    rerunFromStepStream,
    manualRun,
    randomSample,
    resetDetail,
    toggleCompareMode,
    toggleCompareVersion,
  }
}
