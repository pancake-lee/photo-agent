<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NFormItem, NInput, NModal,
  NPagination, NProgress, NRadioButton, NRadioGroup, NSelect, NSpace, NSpin, NStep, NSteps, NTag, useMessage,
} from 'naive-ui'
import PhotoCard from './PhotoCard.vue'
import type { BurstViewLevel } from '../types/photo'
import { getImportBatchApp } from '../utils/importBatch'
import type {
  ImportBatch, ImportBurstProgress, ImportDecision, ImportEntry, ImportMode, ImportPlan, ImportSource, ImportSourceRole, ImportStep, ImportSummary,
} from '../utils/importBatch'
import { onWailsEvent, wailsApi, wailsError } from '../utils/wails'
import { settings } from '../stores/settings'
import { getApiBase } from '../config'

const message = useMessage()
const router = useRouter()
const batch = ref<ImportBatch>()
const batches = ref<ImportSummary[]>([])
const showCleanup = ref(false)
const cleanupIDs = ref<string[]>([])
const cleanupErrors = ref<Record<string, string>>({})
const continueOptions = computed(() => batches.value.filter((item) => item.step !== 'abandoning').map((item) => ({
  label: item.name || item.activity, value: item.id,
})))
const selectedBatchID = computed(() => continueOptions.value.find((option) => option.value === batch.value?.id)?.value ?? null)
const activity = ref('')
const sources = ref<ImportSource[]>([])
const mode = ref<ImportMode>('pc')
const complete = ref(false)
const busy = ref('')
const grouping = ref(false)
const groupingError = ref('')
const progress = ref<ImportBurstProgress>()
const filter = ref('all')
const viewLevel = ref<BurstViewLevel>('coarse')
const previewID = ref('')
const previewStrip = ref<HTMLDivElement>()
const page = ref(1)
const localPreview = ref('')
const previewLoaded = ref(false)
const previewFailed = ref(false)
const originalReady = ref(false)
const allowOriginal = ref(false)
const boundary = ref<{ id: string; direction: -1 | 1 }>()
let boundaryTimer: ReturnType<typeof setTimeout> | undefined
const uploadPlan = ref<ImportPlan[]>()
const archivePage = ref(1)
interface FileProgress {
  batch_id: string
  completed: number
  total: number
  path: string
  entry_id?: string
  staged_on?: string
  error?: string
}
const uploadProgress = ref<FileProgress>()
const stageProgress = ref<FileProgress>()
const recycleFiles = ref<string[]>()
const confirmRecycle = ref(false)
const loadingStep = ref(false)
const stepError = ref('')
const preparing = ref<boolean>()
let disposed = false
const shotEntry = ref<ImportEntry>()
const shotAt = ref('')
const pageSize = 30

const scanMode = computed(() => batch.value ? batch.value.mode ?? '' : mode.value)
const sourceFields = computed<{ role: ImportSourceRole; label: string; required: boolean; hint?: string }[]>(() => {
  const fromIPad = mode.value === 'ipad'
  const local = { role: 'local' as const, label: '本地原片', required: !fromIPad,
    hint: fromIPad ? '用于匹配相机 JPG 和 NEF、核对本地废片。' : undefined }
  const favorite = { role: 'favorite' as const, label: 'iPad 收藏', required: false,
    hint: scanMode.value === 'pc' ? '为匹配到的本地原片标记收藏。' : '继承收藏标记，收藏导出中的独有照片也会加入选片。' }
  if (!fromIPad) return [local, favorite]
  return [
    { role: 'starting', label: 'iPad 筛选前的 JPG 范围', required: true, hint: '选择当时导入 iPad 参与选片的那批 JPG。' },
    { role: 'retained', label: 'iPad 筛选后的留存', required: true, hint: '选择筛选完成后导出的留存照片。' },
    favorite,
    local,
  ]
})
const activeSources = computed(() => sources.value.filter((source) => sourceFields.value.some((field) => field.role === source.role)))
function hasSource(role: ImportSourceRole) {
  return activeSources.value.some((source) => source.role === role)
}
const canCompareExports = computed(() => hasSource('retained') && hasSource('starting'))
const usesCompleteExport = computed(() => canCompareExports.value && complete.value)
const canPrepare = computed(() => !!activity.value.trim() && !!activeSources.value.length &&
  (!scanMode.value || sourceFields.value.every((field) => !field.required || hasSource(field.role))))
const needsScan = computed(() => {
  const saved = batch.value
  return !saved || saved.complete !== usesCompleteExport.value || saved.sources.length !== activeSources.value.length ||
    activeSources.value.some((source, index) => source.path !== saved.sources[index].path || source.role !== saved.sources[index].role)
})
const filters = [
  { label: '全部照片', value: 'all' },
  { label: '收藏', value: 'favorite' },
  { label: '已标记删除', value: 'discarded' },
  { label: '需核对', value: 'review' },
]
const viewLevels = [
  { label: '全部展开', value: 'all' },
  { label: '精细合并', value: 'fine' },
  { label: '模糊合并', value: 'coarse' },
]
function canStage(entry: ImportEntry) {
  return !!entry.jpg && !entry.reference_only && !entry.historical && !entry.upload?.verified && entry.decision !== 'discarded'
}
function isStaged(entry: ImportEntry) {
  return !!settings.backendUrl && entry.staged_server === settings.backendUrl
}
function canArchive(entry: ImportEntry) {
  return canStage(entry) && !entry.conflict && entry.pair !== 'review'
}
const stageCandidates = computed(() => batch.value?.entries.filter(canStage) ?? [])
const stagedCount = computed(() => stageCandidates.value.filter(isStaged).length)
const stageFailureCount = computed(() => stageCandidates.value.filter((entry) => !isStaged(entry) && entry.stage_error).length)
const steps = [
  { key: 'prepare', title: '准备照片' }, { key: 'review', title: '选片' },
  { key: 'reject', title: '回收废片' }, { key: 'archive', title: '入库' },
  { key: 'keep', title: '回收已入库' }, { key: 'finish', title: '完成批次' },
]
const step = computed(() => {
  if (!batch.value) return 'prepare'
  const saved = batch.value.step ?? 'review'
  if (saved === 'review' && (preparing.value ?? (!batch.value.entries.length || stagedCount.value < stageCandidates.value.length))) return 'prepare'
  return saved
})
const stepNumber = computed(() => step.value === 'done' ? steps.length : steps.findIndex((item) => item.key === step.value) + 1)
const recycleKind = computed(() => step.value === 'reject' ? 'discarded' : 'imported')
const recycleGroups = computed(() => {
  const groups = batch.value?.recycling ?? []
  const relevant = step.value === 'done' || step.value === 'finish' ? groups : groups.filter((group) => group.kind === recycleKind.value)
  const latest = new Map(relevant.flatMap((group) => group.files.map((file) => [file.source, file] as const)))
  return relevant.filter((group) => group.files.length &&
    (group.directory || group.files.some((file) => latest.get(file.source) === file)))
})
const recycleFailed = computed(() => recycleGroups.value.some((group) => group.error || group.files.some((file) => file.error)))
const verifiedCount = computed(() => batch.value?.entries.filter((entry) => entry.upload?.verified).length ?? 0)
const archiveEntries = computed(() => batch.value?.entries.filter(canArchive) ?? [])
const archiveIssues = computed(() => new Map(uploadPlan.value?.map((item) => [item.entry_id, item.plan.error])))
const readyPlans = computed(() => uploadPlan.value?.filter((item) => !item.plan.error) ?? [])
const shownArchiveEntries = computed(() => archiveEntries.value.slice((archivePage.value - 1) * pageSize, archivePage.value * pageSize))
const reviewIssueCount = computed(() => batch.value?.entries.filter((entry) => !entry.historical &&
  entry.decision !== 'discarded' && !entry.upload?.verified && needsReview(entry)).length ?? 0)
const excludedCount = computed(() => batch.value?.entries.filter((entry) => !entry.historical &&
  entry.decision !== 'discarded' && !entry.upload?.verified && !canArchive(entry) && needsReview(entry)).length ?? 0)
const stagedEntries = computed(() => stageCandidates.value.filter((entry) =>
  isStaged(entry) && canArchive(entry),
))
const entriesByID = computed(() => new Map((batch.value?.entries ?? []).map((entry) => [entry.id, entry])))
const deletedCount = computed(() => (batch.value?.entries ?? []).filter((entry) => entry.decision === 'discarded').length)
const favoriteEntries = computed(() => (batch.value?.entries ?? []).filter(isPreviewableFavorite))
const ipadFavoriteCount = computed(() => favoriteEntries.value.filter((entry) => entry.origin === 'ipad').length)
const hasFavoriteSource = computed(() => batch.value?.sources.some((source) => source.role === 'favorite'))
const emptyFavoriteDirs = computed(() => batch.value?.empty_favorite_dirs?.filter((path) =>
  activeSources.value.some((source) => source.role === 'favorite' && source.path === path),
) ?? [])
const burstGroups = computed(() => {
  const bursts = batch.value?.bursts
  if (!bursts || filter.value !== 'all' || viewLevel.value === 'all' || bursts.server !== settings.backendUrl) return []
  return bursts[viewLevel.value]
})
const reviewSet = computed(() => new Set(stagedEntries.value.map((entry) => entry.id)))
const groupByEntry = computed(() => {
  const byId = new Map<string, string[]>()
  for (const group of burstGroups.value) {
    const live = group.filter((id) => reviewSet.value.has(id))
    if (live.length > 1) for (const id of live) byId.set(id, live)
  }
  return byId
})
function needsReview(entry: ImportEntry) {
  return entry.pair === 'review' || !!entry.conflict || !!entry.missing_from_export ||
    !!entry.stage_error || !!entry.upload?.error || !entry.jpg
}
const filtered = computed(() => {
  const entries = batch.value?.entries ?? []
  const list = entries.filter((entry) => {
    if (filter.value === 'discarded') return entry.decision === 'discarded'
    if (entry.decision === 'discarded') return false
    if (filter.value === 'review') return needsReview(entry)
    if (filter.value === 'favorite') return isPreviewableFavorite(entry)
    return canPreview(entry)
  })
  return list.filter((entry) => {
    const group = groupByEntry.value.get(entry.id)
    return !group || group[0] === entry.id
  }).sort((a, b) => (a.shot_at ?? '').localeCompare(b.shot_at ?? ''))
})
const shown = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const favoriteTags = computed(() => {
  const tags = new Map<string, string>()
  for (const entry of shown.value) {
    const group = groupByEntry.value.get(entry.id)
    if (group) {
      const count = group.filter((id) => entriesByID.value.get(id)?.decision === 'favorite').length
      if (count) tags.set(entry.id, `${count} 张已收藏`)
    } else if (entry.decision === 'favorite') {
      tags.set(entry.id, entry.origin === 'ipad' ? 'iPad 收藏' : '已收藏')
    }
  }
  return tags
})
const previewEntry = computed(() => entriesByID.value.get(previewID.value))
const previewGroup = computed(() => step.value === 'review' ? groupByEntry.value.get(previewID.value) ?? [] : [])
const previewIDs = computed(() => step.value === 'archive'
  ? archiveEntries.value.filter(canPreview).map((entry) => entry.id)
  : filtered.value.filter(canPreview).flatMap(targetIDs))
const previewIndex = computed(() => previewIDs.value.indexOf(previewID.value))
const previewThumbnail = computed(() => previewEntry.value ? localPreview.value || imageURL(previewEntry.value, true) : '')
const previewOriginal = computed(() => previewEntry.value && allowOriginal.value ? imageURL(previewEntry.value) : '')
const progressValue = computed(() => {
  const state = progress.value
  return state && state.total ? Math.min(100, Math.round(state.done / state.total * 100)) : 0
})

watch([filter, viewLevel], () => { page.value = 1 })
watch(() => settings.backendUrl, () => { void retryWorkflow() })
watch(filtered, (list) => { page.value = Math.min(page.value, Math.max(1, Math.ceil(list.length / pageSize))) })
watch(previewIDs, (ids, previous) => {
  if (!previewID.value || ids.includes(previewID.value)) return
  const index = previous.indexOf(previewID.value)
  previewID.value = previous.slice(index + 1).find((id) => ids.includes(id)) ??
    previous.slice(0, Math.max(0, index)).reverse().find((id) => ids.includes(id)) ?? ''
})
watch(previewID, async (id) => {
  clearBoundary()
  localPreview.value = ''
  previewLoaded.value = false
  previewFailed.value = false
  originalReady.value = false
  allowOriginal.value = false
  const entry = entriesByID.value.get(id)
  if (!entry?.reference_only || !entry.jpg) return
  try {
    const data = await wailsApi.previewImage(entry.jpg.path)
    if (id === previewID.value) localPreview.value = `data:image/jpeg;base64,${data}`
  } catch {
    if (id === previewID.value) previewFailed.value = true
  }
})
watch(previewID, () => {
  previewStrip.value?.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}, { flush: 'post' })

async function perform(label: string, fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = label
  try { await fn() } catch (error) { message.error(wailsError(error)) }
  finally { busy.value = '' }
}

async function refreshBatches() {
  batches.value = await getImportBatchApp().ListImportBatches()
}

function setBatch(loaded?: ImportBatch) {
  batch.value = loaded
  preparing.value = undefined
  uploadProgress.value = undefined
  stageProgress.value = undefined
  uploadPlan.value = undefined
  recycleFiles.value = undefined
  confirmRecycle.value = false
  stepError.value = ''
  activity.value = loaded?.activity ?? ''
  sources.value = loaded?.sources.slice() ?? []
  mode.value = loaded?.mode ?? (sources.value.some((source) => source.role === 'starting' || source.role === 'retained') ? 'ipad' : 'pc')
  complete.value = loaded?.complete ?? false
  filter.value = 'all'
  viewLevel.value = 'coarse'
  previewID.value = ''
  groupingError.value = ''
  progress.value = undefined
  page.value = 1
}

async function selectBatch(id: string | null) {
  await perform('打开批次', async () => {
    const loaded = id ? await getImportBatchApp().GetImportBatch(id) : undefined
    setBatch(loaded)
    await continueWorkflow()
  })
  await ensureGrouping()
}

function openCleanup() {
  cleanupIDs.value = []
  showCleanup.value = true
}

function toggleCleanup(id: string, checked: boolean) {
  cleanupIDs.value = checked ? [...cleanupIDs.value, id] : cleanupIDs.value.filter((value) => value !== id)
}

function abandonBatches() {
  return perform('废弃批次', async () => {
    const selected = new Set(cleanupIDs.value)
    if (batch.value && selected.has(batch.value.id)) setBatch()
    const failed: Record<string, string> = {}
    let removed = 0
    for (const id of selected) {
      try {
        await getImportBatchApp().AbandonImportBatch(id)
        batches.value = batches.value.filter((item) => item.id !== id)
        removed++
      } catch (error) {
        failed[id] = wailsError(error)
      }
    }
    cleanupErrors.value = failed
    cleanupIDs.value = Object.keys(failed)
    if (removed) message.success(`已废弃 ${removed} 个批次`)
    if (!cleanupIDs.value.length) showCleanup.value = false
    await refreshBatches()
  })
}

async function addSource(role: ImportSourceRole) {
  await perform('选择目录', async () => {
    const picked = await getImportBatchApp().ChooseImportSource()
    if (!picked || sources.value.some((source) => source.path === picked && source.role === role)) return
    sources.value.push({ path: picked, role })
    if (!activity.value.trim() && role === 'local') {
      const folder = picked.split(/[\\/]/).filter(Boolean).at(-1)
      if (folder && !folder.includes(':')) activity.value = folder
    }
  })
}

function preparePhotos(rescan: boolean) {
  return perform('准备照片', async () => {
    if (!canPrepare.value) return
    if (rescan || needsScan.value || !batch.value?.entries.length) {
      busy.value = '扫描来源'
      batch.value = await getImportBatchApp().ScanImportBatch(
        batch.value?.id ?? '', activity.value.trim(), activeSources.value, usesCompleteExport.value, scanMode.value,
      )
      activity.value = batch.value.activity
      preparing.value = true
      previewID.value = ''
      groupingError.value = ''
      progress.value = undefined
      if (emptyFavoriteDirs.value.length) message.warning('所选 iPad 收藏目录中没有 JPG 或 JPEG 照片')
      await refreshBatches()
    }
    if (!batch.value?.entries.length || disposed) return
    if (stagedCount.value < stageCandidates.value.length) {
      busy.value = '上传 JPG 到服务器'
      stageProgress.value = { batch_id: batch.value.id, completed: 0, total: stageCandidates.value.length, path: '' }
      batch.value = await getImportBatchApp().StageImportJPGs(batch.value.id, settings.backendUrl)
      const failed = batch.value.entries.filter((entry) => entry.stage_error).length
      if (failed) message.warning(`${failed} 张 JPG 暂存失败，可重试`)
      if (!stagedCount.value && stageCandidates.value.length) return
    }
    preparing.value = false
    await ensureGrouping()
  })
}

async function ensureGrouping() {
  if (step.value === 'review' && stagedEntries.value.length && batch.value?.bursts?.server !== settings.backendUrl) {
    await runGrouping()
  }
}

async function runGrouping() {
  const current = batch.value
  if (disposed || !current || grouping.value || !stagedEntries.value.length) return
  grouping.value = true
  groupingError.value = ''
  progress.value = { batch_id: current.id, done: 0, failed: 0, total: stagedEntries.value.length, message: '服务器正在计算连拍组' }
  try {
    batch.value = await getImportBatchApp().GroupImportBatch(current.id, settings.backendUrl)
  } catch (error) {
    groupingError.value = wailsError(error)
  } finally {
    grouping.value = false
  }
}

function decide(ids: string[], value: ImportDecision, successMessage?: string) {
  return perform('保存审阅决定', async () => {
    if (!batch.value) return
    batch.value = await getImportBatchApp().DecideImportBatch(batch.value.id, ids, value)
    if (successMessage) message.success(successMessage)
  })
}

function keepOnlyCurrent(id: string) {
  const otherIDs = previewGroup.value.filter((memberID) => memberID !== id)
  if (otherIDs.length) {
    return decide(otherIDs, 'discarded', `已标记删除同组其余 ${otherIDs.length} 张照片，可撤销上一步`)
  }
}

function toggleFavorite(ids: string[]) {
  const allFavorited = ids.every((id) => entriesByID.value.get(id)?.decision === 'favorite')
  return decide(ids, allFavorited ? 'kept' : 'favorite')
}

function entryName(entry: ImportEntry) {
  return (entry.jpg?.path ?? entry.nef?.path ?? '').split(/[\\/]/).pop() ?? ''
}

function imageURL(entry: ImportEntry, thumbnail = false) {
  const jpg = entry.jpg
  if (!jpg) return ''
  if (entry.upload?.verified && entry.upload.photo_id) {
    return `${getApiBase()}/photos/${encodeURIComponent(entry.upload.photo_id)}/image`
  }
  const query = new URLSearchParams({ batch_id: batch.value?.id ?? '', sha256: jpg.sha256 })
  if (thumbnail) query.set('size', 'thumbnail')
  return isStaged(entry) ? `${getApiBase()}/photo-import/stage/image?${query}` : ''
}

function photoCard(entry: ImportEntry) {
  const group = groupByEntry.value.get(entry.id)
  return {
    id: entry.id, filename: entryName(entry), thumbnail_url: imageURL(entry, true), image_url: imageURL(entry), has_nef: !!entry.nef,
    burst_group_id: group?.[0] ?? '', burst_cover: group?.[0] === entry.id,
    burst_count: group?.length ?? 0, shot_at: entry.shot_at,
  }
}

function canEdit(entry: ImportEntry) {
  return step.value === 'review' && !!entry.jpg && !entry.historical && !entry.upload?.verified &&
    (isStaged(entry) || !!entry.reference_only) && entry.decision !== 'discarded'
}

function targetIDs(entry: ImportEntry) {
  return groupByEntry.value.get(entry.id) ?? [entry.id]
}

function favoriteLabel(ids: string[]) {
  const allFavorited = ids.every((id) => entriesByID.value.get(id)?.decision === 'favorite')
  return (allFavorited ? '取消收藏' : '收藏') + (ids.length > 1 ? '整组' : '')
}

function showDetail(id: string) {
  const entry = entriesByID.value.get(id)
  if (entry && canPreview(entry)) previewID.value = id
}

function canPreview(entry: ImportEntry) {
  return !!entry.jpg && (isStaged(entry) || !!entry.upload?.verified || !!entry.reference_only)
}

function isPreviewableFavorite(entry: ImportEntry) {
  return entry.decision === 'favorite' && canPreview(entry)
}

function clearBoundary() {
  clearTimeout(boundaryTimer)
  boundary.value = undefined
}

function navigatePreview(direction: -1 | 1) {
  const next = previewIDs.value[previewIndex.value + direction]
  if (previewIndex.value < 0 || !next) return
  if (previewGroup.value.length && !previewGroup.value.includes(next) &&
    (boundary.value?.id !== previewID.value || boundary.value.direction !== direction)) {
    clearBoundary()
    boundary.value = { id: previewID.value, direction }
    boundaryTimer = setTimeout(clearBoundary, 5000)
    return
  }
  previewID.value = next
}

function handlePreviewKey(event: KeyboardEvent) {
  if (!previewID.value || shotEntry.value || event.defaultPrevented || event.repeat ||
    event.isComposing || event.altKey || event.ctrlKey || event.metaKey) return
  const target = event.target
  if (target instanceof HTMLElement && (target.isContentEditable || target.matches('input, textarea, select'))) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    navigatePreview(event.key === 'ArrowLeft' ? -1 : 1)
    return
  }
  const entry = previewEntry.value
  if (!entry || !canEdit(entry) || busy.value || grouping.value) return
  if (event.key === 'Delete') {
    event.preventDefault()
    void decide([entry.id], 'discarded')
  } else if (event.key.toLowerCase() === 'l' && !entry.reference_only) {
    event.preventDefault()
    void toggleFavorite([entry.id])
  }
}

async function continueWorkflow(promptForRecycle = true) {
  stepError.value = ''
  loadingStep.value = true
  try {
    while (batch.value && !disposed) {
      const id = batch.value.id
      const current = step.value

      if (current === 'finish') {
        batch.value = await getImportBatchApp().FinishImportBatch(id)
        batches.value = batches.value.filter((item) => item.id !== id)
        message.success('批次已完成')
        return
      }
      if (current === 'archive') {
        archivePage.value = 1
        uploadPlan.value = await getImportBatchApp().PreviewImportUploads(id, settings.backendUrl)
        if (uploadPlan.value.length || disposed) return
        await moveToStep('keep')
      } else if (current === 'reject' || current === 'keep') {
        const files = await getImportBatchApp().PreviewImportRecycle(id, recycleKind.value)
        recycleFiles.value = files.map((file) => file.source)
        if (files.length || disposed) {
          if (files.length && promptForRecycle && !disposed) confirmRecycle.value = true
          return
        }
        await moveToStep(current === 'reject' ? 'archive' : 'finish')
      } else {
        return
      }
      promptForRecycle = true
    }
  } catch (error) {
    stepError.value = wailsError(error)
  } finally {
    loadingStep.value = false
  }
}

function retryWorkflow() {
  return perform('检查导入进度', async () => { await continueWorkflow() })
}

function upload() {
  const plans = readyPlans.value
  return perform('上传原片', async () => {
    if (!batch.value || !plans.length) return
    uploadProgress.value = { batch_id: batch.value.id, completed: 0, total: plans.length, path: '' }
    batch.value = await getImportBatchApp().UploadImportBatch(batch.value.id, settings.backendUrl, plans)
    const verified = batch.value.entries.filter((entry) => entry.upload?.verified).length
    const failed = batch.value.entries.filter((entry) => entry.upload?.error).length
    if (failed) message.warning(`已核验 ${verified} 张，待重试 ${failed} 张`)
    else message.success(`已核验 ${verified} 张`)
    await continueWorkflow()
  })
}

function advance(next: ImportStep, leaveLocal = false) {
  return perform('切换导入步骤', async () => {
    await moveToStep(next, leaveLocal)
    await continueWorkflow()
  })
}

async function moveToStep(next: ImportStep, leaveLocal = false) {
  if (!batch.value || disposed) return
  batch.value = await getImportBatchApp().AdvanceImportBatch(batch.value.id, next, leaveLocal)
  if (next === 'review') {
    preparing.value = false
    filter.value = 'all'
  }
  previewID.value = ''
  uploadPlan.value = undefined
  recycleFiles.value = undefined
  confirmRecycle.value = false
}

function submitRecycle() {
  const paths = recycleFiles.value
  const kind = recycleKind.value
  return perform('处理本地文件', async () => {
    if (!batch.value || !paths?.length) return
    batch.value = await getImportBatchApp().RecycleImportFiles(batch.value.id, kind, paths)
    const recycled = new Set((batch.value.recycling ?? []).flatMap((group) => group.files
      .filter((file) => file.status === 'recycled').map((file) => file.source)))
    const count = paths.filter((path) => recycled.has(path)).length
    if (count) message.success(`已将 ${count} 个文件移入 Windows 回收站`)
    confirmRecycle.value = false
    await continueWorkflow(false)
  })
}

async function resolvePair(entry: ImportEntry, path: string) {
  await perform('保存配对', async () => {
    if (batch.value) batch.value = await getImportBatchApp().ResolveImportPair(batch.value.id, entry.id, path)
  })
  await ensureGrouping()
}

function editShotAt(entry: ImportEntry) {
  shotEntry.value = entry
  shotAt.value = entry.shot_at ?? ''
}

async function saveShotAt() {
  await perform('保存拍摄时间', async () => {
    if (!batch.value || !shotEntry.value) return
    batch.value = await getImportBatchApp().SetImportShotAt(batch.value.id, shotEntry.value.id, shotAt.value)
    shotEntry.value = undefined
  })
  await ensureGrouping()
}

let unsubscribeBurst = () => {}
let unsubscribeUpload = () => {}
let unsubscribeStage = () => {}
onMounted(() => {
  void perform('读取批次', refreshBatches)
  unsubscribeBurst = onWailsEvent<ImportBurstProgress>('import:burst', (value) => {
    if (value.batch_id === batch.value?.id) progress.value = value
  })
  unsubscribeUpload = onWailsEvent<FileProgress>('import:upload', (value) => {
    if (value.batch_id === batch.value?.id) uploadProgress.value = value
  })
  unsubscribeStage = onWailsEvent<FileProgress>('import:stage', (value) => {
    if (value.batch_id !== batch.value?.id || busy.value !== '上传 JPG 到服务器') return
    stageProgress.value = value
    const entry = value.entry_id ? entriesByID.value.get(value.entry_id) : undefined
    if (entry) {
      entry.staged_server = value.staged_on
      entry.stage_error = value.error
      if (value.staged_on === settings.backendUrl) preparing.value = false
    }
  })
  window.addEventListener('keydown', handlePreviewKey)
})
onUnmounted(() => {
  disposed = true
  if (grouping.value) void getImportBatchApp().CancelImportBursts()
  clearBoundary()
  window.removeEventListener('keydown', handlePreviewKey)
  unsubscribeBurst()
  unsubscribeUpload()
  unsubscribeStage()
})
</script>

<template>
  <div class="batch-workflow">
    <NCard title="导入批次">
      <NSpace align="center">
        <NSelect :value="selectedBatchID" :options="continueOptions" placeholder="继续已有批次" clearable
          :disabled="!continueOptions.length || !!busy || grouping" style="width: 280px" @update:value="selectBatch" />
        <NButton v-if="batches.length" :disabled="!!busy || grouping" @click="openCleanup">清理批次</NButton>
        <NButton v-if="batch && step !== 'done'" :disabled="!!busy || grouping" @click="selectBatch(null)">新建批次</NButton>
      </NSpace>
      <NSteps class="form-row" :current="stepNumber" :status="step === 'done' ? 'finish' : 'process'" size="small">
        <NStep v-for="item in steps" :key="item.key" :title="item.title" />
      </NSteps>
    </NCard>

    <NAlert v-if="emptyFavoriteDirs.length && (step === 'prepare' || step === 'review')"
      type="warning" title="iPad 收藏目录中没有 JPG 或 JPEG 照片">
      <p>{{ step === 'review' ? '可返回「准备照片」，更换收藏目录后重新扫描。' : '可更换收藏目录，再开始选片。' }}</p>
      <ul class="source-warning-paths">
        <li v-for="path in emptyFavoriteDirs" :key="path">{{ path }}</li>
      </ul>
    </NAlert>
    <NAlert v-if="batch?.issues.length && (step === 'prepare' || step === 'review')" type="warning" title="部分来源读取失败">
      <div v-for="(issue, index) in batch.issues" :key="index">{{ issue }}</div>
    </NAlert>

    <NCard v-if="step === 'prepare'" title="准备照片">
      <NFormItem label="导入模式">
        <NRadioGroup v-model:value="mode" :disabled="!!batch || !!busy || grouping" aria-label="导入模式">
          <NRadioButton value="pc">电脑原片</NRadioButton>
          <NRadioButton value="ipad">按 iPad 选片结果导入</NRadioButton>
        </NRadioGroup>
      </NFormItem>
      <NAlert v-if="batch && !batch.mode" type="info" class="form-row">此批次沿用创建时的来源规则。</NAlert>
      <NFormItem v-for="field in sourceFields" :key="field.role" :label="field.label + (field.required ? '' : '（可选）')"
        :required="!!scanMode && field.required" :show-feedback="false" class="source-field">
        <div>
          <NSpace align="center">
            <NButton :disabled="!!busy || grouping" @click="addSource(field.role)" :aria-label="`添加${field.label}目录`">添加目录</NButton>
            <span v-if="field.hint" class="source-hint">{{ field.hint }}</span>
          </NSpace>
          <ul v-if="hasSource(field.role)" class="paths">
            <template v-for="(source, index) in sources" :key="`${source.role}/${source.path}`">
              <li v-if="source.role === field.role">
                <span>{{ source.path }}</span>
                <NButton text :disabled="!!busy || grouping" :aria-label="`移除 ${source.path}`" @click="sources.splice(index, 1)">移除</NButton>
              </li>
            </template>
          </ul>
        </div>
      </NFormItem>
      <div v-if="canCompareExports" class="form-row">
        <NCheckbox v-model:checked="complete" :disabled="!!busy || grouping">
          留存目录是完整导出，可以比对废片
        </NCheckbox>
        <p class="source-hint">在筛选前的 JPG 范围内，留存和收藏中都找不到的照片会列入「需核对」。</p>
      </div>
      <NFormItem label="服务器活动目录" class="form-row">
        <NInput v-model:value="activity" :disabled="!!batch || !!busy" placeholder="例如 202611-桂林" />
      </NFormItem>
      <NSpace align="center">
        <NButton type="primary" :loading="busy === '扫描来源' || busy === '上传 JPG 到服务器'"
          :disabled="!canPrepare || !!busy || grouping" @click="preparePhotos(false)">
          {{ !needsScan && stageFailureCount ? '重试上传 JPG' : '开始选片' }}
        </NButton>
        <NButton v-if="batch?.entries.length && !needsScan" text :disabled="!canPrepare || !!busy || grouping"
          @click="preparePhotos(true)">重新扫描来源</NButton>
      </NSpace>
      <p v-if="busy === '扫描来源'" aria-live="polite">正在扫描来源目录</p>
      <div v-else-if="batch && !needsScan" class="form-row">
        <div v-if="stageProgress && busy === '上传 JPG 到服务器'" aria-live="polite">
          <p>正在上传 JPG，服务器并行准备缩略图</p>
          <NProgress :percentage="Math.round(stageProgress.completed / Math.max(1, stageProgress.total) * 100)" processing />
          <p>{{ stageProgress.completed }} / {{ stageProgress.total }} 张</p>
        </div>
        <p v-else-if="stageFailureCount">{{ stageFailureCount }} 张 JPG 暂存失败，可重试。</p>
        <p v-else-if="!batch.entries.length">来源目录没有可处理的照片。</p>
      </div>
    </NCard>

    <template v-if="batch">
      <NCard v-if="step === 'review'" title="选片">
        <template #header-extra>
          <NSpace>
            <NButton :disabled="!!busy || grouping" @click="preparing = true">返回准备照片</NButton>
            <NButton type="primary" :disabled="!batch.entries.length || !!busy || grouping" @click="advance('reject')">选片完成</NButton>
          </NSpace>
        </template>
        <NSpace align="center">
          <span>{{ stagedEntries.length }} 张可选 · {{ favoriteEntries.length }} 张收藏<span v-if="hasFavoriteSource">（{{ ipadFavoriteCount }} 张来自 iPad）</span> · {{ deletedCount }} 张标记删除</span>
          <NSelect v-model:value="viewLevel" :options="viewLevels" :disabled="filter !== 'all' || !batch.bursts"
            style="width: 128px" aria-label="连拍展示" />
        </NSpace>
        <div v-if="stageProgress && busy === '上传 JPG 到服务器' && !grouping" class="form-row" aria-live="polite">
          <NProgress :percentage="Math.round(stageProgress.completed / Math.max(1, stageProgress.total) * 100)" :processing="stageProgress.completed < stageProgress.total" />
          <p>正在上传 JPG，已处理 {{ stageProgress.completed }} / {{ stageProgress.total }} 张。服务器并行准备缩略图。</p>
        </div>
        <NAlert v-if="groupingError" type="warning" class="form-row">
          {{ groupingError }} <NButton text :disabled="!!busy || grouping" @click="runGrouping">重试连拍计算</NButton>
        </NAlert>
        <div v-if="progress" class="form-row" aria-live="polite">
          <NProgress :percentage="progressValue" :processing="grouping" />
          <p>{{ progress.message }} · {{ progress.done }}/{{ progress.total }}<span v-if="progress.failed"> · {{ progress.failed }} 张读取失败</span></p>
        </div>
        <NSpace align="center" class="form-row">
          <NSelect v-model:value="filter" :options="filters" style="width: 160px" aria-label="选片范围" />
          <NButton :disabled="!batch.undo?.length || !!busy || grouping" @click="perform('撤销', async () => { if (batch) batch = await getImportBatchApp().UndoImportBatch(batch.id) })">撤销上一步</NButton>
        </NSpace>
        <p>照片默认留存。标记删除后可撤销，原片在确认回收时处理。</p>
        <NAlert v-if="reviewIssueCount && filter !== 'review'" type="warning" class="form-row">
          {{ reviewIssueCount }} 张照片有待核对的来源、配对或上传问题。 <NButton text @click="filter = 'review'">查看需核对照片</NButton>
        </NAlert>
        <NEmpty v-if="!shown.length" :description="filter === 'all' && !stagedCount ? '上传 JPG 后开始选片' : '此范围暂无照片'" />
        <ul v-else class="review-grid">
          <li v-for="entry in shown" :key="entry.id">
            <PhotoCard v-if="imageURL(entry)" :photo="photoCard(entry)" :show-status="false" :show-embed="false"
              :show-delete="false" :show-tooltip="false" :view-level="viewLevel"
              @view-detail="showDetail" @open-burst-group="showDetail">
              <template #actions>
                <NTag v-if="favoriteTags.has(entry.id)" size="small" type="warning" class="favorite-status">{{ favoriteTags.get(entry.id) }}</NTag>
                <NSpace v-if="canEdit(entry)" class="review-actions" :size="4" @click.stop>
                  <NButton size="small" :type="targetIDs(entry).every((id) => entriesByID.get(id)?.decision === 'favorite') ? 'warning' : 'default'"
                    :disabled="!!busy || grouping" @click="toggleFavorite(targetIDs(entry))">{{ favoriteLabel(targetIDs(entry)) }}</NButton>
                  <NButton size="small" secondary type="error" :disabled="!!busy || grouping"
                    @click="decide(targetIDs(entry), 'discarded')">{{ targetIDs(entry).length > 1 ? '删除整组' : '删除' }}</NButton>
                </NSpace>
                <NTag v-else-if="entry.upload?.verified" size="small">已入库</NTag>
              </template>
            </PhotoCard>
            <NCard v-else size="small">
              <NButton v-if="entry.reference_only" text @click="showDetail(entry.id)">{{ entryName(entry) }}</NButton>
              <span v-else>{{ entryName(entry) }}</span>
              <NButton v-if="entry.reference_only && canEdit(entry)" size="small" type="error" secondary
                :disabled="!!busy || grouping" @click="decide([entry.id], 'discarded')">删除</NButton>
            </NCard>
            <div v-if="(filter === 'review' || filter === 'discarded') && needsReview(entry)" class="review-issues">
              <NAlert v-if="entry.stage_error || entry.upload?.error" type="error">{{ entry.stage_error || entry.upload?.error }}</NAlert>
              <div v-if="entry.conflict">
                来源决定需核对
                <NButton v-if="canEdit(entry) && !entry.reference_only" text :disabled="!!busy || grouping"
                  @click="decide([entry.id], entry.decision === 'favorite' ? 'favorite' : 'kept')">确认来源</NButton>
              </div>
              <div v-if="entry.missing_from_export">在完整 iPad 导出中缺席</div>
              <div v-if="!entry.jpg">仅 NEF，需补齐 JPG</div>
              <NSelect v-if="entry.pair === 'review'" :disabled="!!busy || grouping" placeholder="核对 NEF 配对"
                :options="[...(entry.reference_only ? [] : [{ label: '仅 JPG', value: '' }]), ...(entry.nef_candidates ?? []).map((file) => ({ label: file.path, value: file.path }))]"
                @update:value="(value) => resolvePair(entry, value)" />
            </div>
          </li>
        </ul>
        <NPagination v-if="filtered.length > pageSize" v-model:page="page" :page-size="pageSize" :item-count="filtered.length" />
      </NCard>

      <NCard v-if="step === 'reject' || step === 'keep'" :title="step === 'reject' ? '回收废片' : '回收已入库'">
        <NSpace v-if="loadingStep" align="center"><NSpin size="small" />正在核对回收文件</NSpace>
        <NAlert v-else-if="stepError" type="error">{{ stepError }} <NButton text :disabled="!!busy" @click="retryWorkflow">重试</NButton></NAlert>
        <template v-else-if="recycleFiles">
          <p v-if="recycleFiles.length">有 {{ recycleFiles.length }} 个本地文件待移入 Windows 回收站。</p>
          <NSpace>
            <NButton v-if="step === 'reject'" :disabled="!!busy" @click="advance('review')">返回选片</NButton>
            <NButton v-if="recycleFiles.length > 0" type="primary" :loading="busy === '处理本地文件'" :disabled="!!busy"
              @click="confirmRecycle = true">{{ recycleFailed ? '重试回收' : step === 'reject' ? '回收废片' : '回收已入库' }}</NButton>
            <NButton v-if="recycleFiles.length && recycleFailed" :disabled="!!busy" @click="advance(step === 'reject' ? 'archive' : 'finish', true)">剩余文件留在原处，继续</NButton>
          </NSpace>
        </template>
      </NCard>

      <NCard v-if="step === 'archive'" title="入库">
        <template #header-extra>
          <NButton v-if="archiveEntries.length" type="primary" :loading="busy === '上传原片'"
            :disabled="!readyPlans.length || !!busy || loadingStep || !!stepError" @click="upload">确认入库</NButton>
        </template>
        <p>服务器活动目录 {{ batch.activity }} · 已核验 {{ verifiedCount }} 张</p>
        <NAlert v-if="excludedCount" type="warning">{{ excludedCount }} 张照片仍需核对来源或配对，未列入本次入库。</NAlert>
        <NSpace v-if="loadingStep" align="center"><NSpin size="small" />正在核对入库文件</NSpace>
        <NAlert v-else-if="stepError" type="error">{{ stepError }} <NButton text :disabled="!!busy" @click="retryWorkflow">重试</NButton></NAlert>
        <template v-else-if="uploadPlan && busy !== '上传原片'">
          <p v-if="uploadPlan.length">{{ readyPlans.length }} 张可入库<span v-if="uploadPlan.length > readyPlans.length">，{{ uploadPlan.length - readyPlans.length }} 张需处理</span></p>
          <p v-else>没有待入库照片。</p>
        </template>
        <NProgress v-if="uploadProgress && busy === '上传原片'" :percentage="Math.round(uploadProgress.completed / uploadProgress.total * 100)" processing />
        <ul v-if="shownArchiveEntries.length" class="review-grid" aria-label="待入库照片">
          <li v-for="entry in shownArchiveEntries" :key="entry.id">
            <PhotoCard v-if="imageURL(entry)" :photo="photoCard(entry)" :show-status="false" :show-embed="false"
              :show-delete="false" :show-tooltip="false" view-level="all" @view-detail="showDetail" />
            <NCard v-else size="small">{{ entryName(entry) }}</NCard>
            <NAlert v-if="archiveIssues.get(entry.id)" type="error" class="review-issues">{{ archiveIssues.get(entry.id) }}</NAlert>
          </li>
        </ul>
        <NPagination v-if="archiveEntries.length > pageSize" v-model:page="archivePage" :page-size="pageSize" :item-count="archiveEntries.length" />
        <NSpace class="form-row">
          <NButton :disabled="!!busy" @click="advance('review')">返回选片</NButton>
          <NButton v-if="uploadPlan && uploadPlan.length > readyPlans.length" :disabled="!!busy" @click="retryWorkflow">重新检查入库</NButton>
        </NSpace>
      </NCard>

      <NCard v-if="step === 'finish' || step === 'done'" :title="step === 'done' ? '批次已完成' : '清理服务器暂存'">
        <p>已核验 {{ verifiedCount }} 张照片。{{ step === 'done' ? '服务器暂存已清理。' : '' }}</p>
        <p v-if="excludedCount">{{ excludedCount }} 张照片因来源或配对待核对，未入库。</p>
        <template v-if="step === 'finish'">
          <NAlert v-if="stepError" type="error">{{ stepError }} <NButton text :disabled="!!busy" @click="retryWorkflow">重试清理</NButton></NAlert>
          <NSpace v-else align="center"><NSpin size="small" />正在清理本批次暂存</NSpace>
        </template>
        <NSpace v-else>
          <NButton type="primary" @click="router.push({ name: 'photos', query: { activity: batch.activity } })">在图片管理查看导入结果</NButton>
          <NButton :disabled="!!busy" @click="selectBatch(null)">开始新批次</NButton>
        </NSpace>
      </NCard>

      <NCard v-if="recycleGroups.length && ['reject', 'keep', 'finish', 'done'].includes(step)" title="回收结果">
        <p v-if="recycleGroups.some((group) => group.status === 'recycled')">需要还原时，请在 Windows 回收站还原对应目录。</p>
        <div v-for="(group, index) in recycleGroups" :key="group.directory || index" class="form-row">
          <NSpace align="center">
            <NTag>{{ ({ recycled: '已回收', retained: '原位保留', restored: '已恢复', pending: '归集中', sending: '待核对回收', uncertain: '待核对回收站', permanent: '永久删除结果' } as Record<string, string>)[group.status] ?? group.status }}</NTag>
            <span :title="group.directory">{{ group.directory.split(/[\\/]/).pop() || (group.kind === 'imported' ? '已入库原片' : '废片') }} · {{ group.files.length }} 个文件</span>
          </NSpace>
          <details v-if="group.error || group.files.some((file) => file.error || file.restored_to && file.restored_to !== file.source)">
            <summary>查看异常详情</summary>
            <p v-if="group.error">{{ group.error }}</p>
            <ul class="paths">
              <li v-for="file in group.files.filter((item) => item.error || item.restored_to && item.restored_to !== item.source)" :key="file.source">
                {{ file.source }} · {{ file.error || `恢复到 ${file.restored_to}` }}
              </li>
            </ul>
          </details>
        </div>
      </NCard>
    </template>

    <NModal :show="showCleanup" preset="card" title="清理批次" class="batch-modal"
      :mask-closable="!busy" :closable="!busy" @update:show="(show) => { if (!show && !busy) showCleanup = false }">
      <p>勾选要废弃的批次。确认后清理所选批次的服务器暂存，并结束这些批次。</p>
      <ul class="cleanup-list">
        <li v-for="item in batches" :key="item.id">
          <NSpace align="center">
            <NCheckbox :checked="cleanupIDs.includes(item.id)" :disabled="!!busy" @update:checked="toggleCleanup(item.id, $event)">
              {{ item.name || item.activity }}
            </NCheckbox>
            <NTag v-if="item.step === 'abandoning'" size="small" type="warning">清理待重试</NTag>
          </NSpace>
          <NAlert v-if="cleanupErrors[item.id]" type="error" class="cleanup-error">{{ cleanupErrors[item.id] }}</NAlert>
        </li>
      </ul>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="!!busy" @click="showCleanup = false">关闭</NButton>
          <NButton type="error" :disabled="!cleanupIDs.length || !!busy" :loading="busy === '废弃批次'"
            @click="abandonBatches">{{ cleanupIDs.length ? `确认废弃 ${cleanupIDs.length} 个批次` : '确认废弃' }}</NButton>
        </NSpace>
      </template>
    </NModal>

    <NModal :show="confirmRecycle" preset="card" :title="step === 'reject' ? '确认回收废片' : '确认回收已入库'"
      class="batch-modal" :mask-closable="!busy" :closable="!busy" @update:show="(show) => { if (!show && !busy) confirmRecycle = false }">
      <p>将 {{ recycleFiles?.length ?? 0 }} 个文件在各自的原片目录归集后，移入 Windows 回收站。</p>
      <template #footer>
        <NSpace justify="end">
          <NButton :disabled="!!busy" @click="confirmRecycle = false">取消</NButton>
          <NButton type="primary" :loading="busy === '处理本地文件'" :disabled="!recycleFiles?.length || !!busy" @click="submitRecycle">确认移入回收站</NButton>
        </NSpace>
      </template>
    </NModal>

    <NModal :show="!!previewEntry" preset="card" :title="previewEntry ? entryName(previewEntry) : '照片预览'"
      :style="{ width: '95vw', height: '95vh' }" :content-style="{ display: 'flex', flexDirection: 'column', minHeight: 0 }"
      @update:show="(show) => { if (!show) previewID = '' }">
      <template v-if="previewEntry">
        <div class="preview-frame">
          <NSpin v-if="!previewLoaded && !previewFailed && !originalReady" size="small" />
          <NEmpty v-if="previewFailed && !originalReady" description="无法读取照片预览" />
          <img v-if="previewThumbnail" :key="`preview-${previewID}`" class="preview-image" :class="{ visible: previewLoaded }"
            :src="previewThumbnail" :alt="entryName(previewEntry)"
            @load="previewLoaded = true; allowOriginal = true" @error="previewFailed = true; allowOriginal = true" />
          <img v-if="previewOriginal && previewOriginal !== previewThumbnail" :key="`original-${previewID}`"
            class="preview-image" :class="{ visible: originalReady }" :src="previewOriginal" alt="" @load="originalReady = true" />
          <button v-if="previewIndex > 0" type="button" class="preview-nav previous" aria-label="上一张（左方向键）" @click="navigatePreview(-1)">‹</button>
          <button v-if="previewIndex >= 0 && previewIndex < previewIDs.length - 1" type="button" class="preview-nav next"
            aria-label="下一张（右方向键）" @click="navigatePreview(1)">›</button>
          <p v-if="boundary" class="preview-boundary" role="status">已到达{{ boundary.direction === -1 ? '第一张' : '最后一张' }}，再次操作跳出当前连拍组</p>
        </div>
        <NSpace v-if="canEdit(previewEntry)" align="center" class="preview-actions" :size="8">
          <NButton v-if="!previewEntry.reference_only" size="small" :disabled="!!busy || grouping" title="L 快捷键"
            @click="toggleFavorite([previewID])">{{ favoriteLabel([previewID]) }}</NButton>
          <NButton size="small" type="error" secondary :disabled="!!busy || grouping" title="Delete 快捷键"
            @click="decide([previewID], 'discarded')">删除当前照片</NButton>
          <template v-if="previewGroup.length">
            <NButton size="small" type="error" secondary :disabled="!!busy || grouping" @click="keepOnlyCurrent(previewID)">只保留当前照片</NButton>
            <NButton size="small" :disabled="!!busy || grouping" @click="toggleFavorite(previewGroup)">{{ favoriteLabel(previewGroup) }}</NButton>
            <NButton size="small" type="error" secondary :disabled="!!busy || grouping" @click="decide(previewGroup, 'discarded')">删除整组</NButton>
          </template>
          <NButton v-if="!previewEntry.reference_only && !previewEntry.upload" size="small" text :disabled="!!busy || grouping"
            @click="editShotAt(previewEntry)">{{ previewEntry.shot_at || '填写拍摄时间' }}</NButton>
        </NSpace>
        <div v-if="previewGroup.length" ref="previewStrip" class="preview-strip" aria-label="连拍组照片">
          <template v-for="id in previewGroup" :key="id">
            <button v-if="entriesByID.get(id)" type="button" class="preview-thumb" :aria-pressed="id === previewID"
              :aria-label="entryName(entriesByID.get(id)!)" @click="previewID = id">
              <img :src="imageURL(entriesByID.get(id)!, true)" alt="" />
            </button>
          </template>
        </div>
      </template>
    </NModal>

    <NModal :show="!!shotEntry" preset="card" title="修正拍摄时间" class="batch-modal" @update:show="(show) => { if (!show) shotEntry = undefined }">
      <NFormItem label="拍摄时间"><NInput v-model:value="shotAt" placeholder="YYYY-MM-DD HH:mm:ss" /></NFormItem>
      <NButton type="primary" :loading="busy === '保存拍摄时间'" @click="saveShotAt">保存时间</NButton>
    </NModal>
  </div>
</template>

<style scoped>
.batch-workflow { display: grid; gap: 16px; }
.form-row { margin-top: 16px; }
.source-field { margin-top: 16px; }
.source-field .paths { margin-bottom: 0; }
.source-hint { font-size: 13px; }
p.source-hint { margin: 4px 0 0; }
.source-warning-paths { margin: 8px 0 0; padding-inline-start: 20px; overflow-wrap: anywhere; }
.paths { margin: 8px 0 16px; padding: 0; list-style: none; overflow-wrap: anywhere; }
.paths li { padding: 4px 0; }
.paths li .n-button { margin-left: 8px; }
.review-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 16px; padding: 0; list-style: none; }
.review-grid li { min-width: 0; overflow-wrap: anywhere; }
.favorite-status { margin-top: 8px; }
.review-actions { margin-top: 8px; }
.review-issues { display: grid; gap: 8px; padding: 8px 0; }
.batch-modal { width: min(760px, 90vw); }
.cleanup-list { display: grid; gap: 8px; padding: 0; max-height: 45vh; overflow: auto; list-style: none; }
.cleanup-error { margin-top: 4px; }
.preview-frame { flex: 1; min-height: 0; display: grid; place-items: center; position: relative; overflow: hidden; background: #171717; }
.preview-image { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; visibility: hidden; }
.preview-image.visible { visibility: visible; }
.preview-nav { position: absolute; top: 0; bottom: 0; width: 16%; border: 0; background: transparent; color: white; font-size: 40px; text-shadow: 0 1px 6px black; cursor: pointer; }
.preview-nav:hover, .preview-nav:focus-visible { background: rgb(0 0 0 / 30%); }
.previous { left: 0; }
.next { right: 0; }
.preview-boundary { position: absolute; bottom: 16px; padding: 8px 16px; margin: 0; border-radius: 4px; color: white; background: rgb(0 0 0 / 80%); pointer-events: none; }
.preview-actions, .preview-strip { margin-top: 8px; }
.preview-strip { display: flex; gap: 8px; overflow-x: auto; }
.preview-thumb { flex: 0 0 64px; height: 64px; padding: 0; border: 2px solid transparent; border-radius: 4px; background: transparent; cursor: pointer; }
.preview-thumb[aria-pressed="true"] { border-color: var(--primary-color, #18a058); }
.preview-thumb img { display: block; width: 100%; height: 100%; object-fit: cover; }
</style>
