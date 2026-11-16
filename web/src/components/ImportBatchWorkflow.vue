<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NFormItem, NInput, NModal,
  NPagination, NProgress, NSelect, NSpace, NSpin, NStep, NSteps, NTag, useMessage,
} from 'naive-ui'
import PhotoCard from './PhotoCard.vue'
import BurstGroupModal from './BurstGroupModal.vue'
import type { BurstViewLevel } from '../types/photo'
import { getImportBatchApp } from '../utils/importBatch'
import type {
  ImportBatch, ImportBurstProgress, ImportDecision, ImportEntry, ImportPlan, ImportSource, ImportSourceRole, ImportStep,
} from '../utils/importBatch'
import { onWailsEvent, wailsApi, wailsError } from '../utils/wails'
import { settings } from '../stores/settings'
import { getApiBase } from '../config'

const message = useMessage()
const batch = ref<ImportBatch>()
const batches = ref<{ label: string; value: string }[]>([])
const activity = ref('')
const sources = ref<ImportSource[]>([])
const role = ref<ImportSourceRole>('local')
const complete = ref(false)
const busy = ref('')
const grouping = ref(false)
const progress = ref<ImportBurstProgress>()
const filter = ref('all')
const viewLevel = ref<BurstViewLevel>('fine')
const openGroup = ref<string[]>([])
const previewEntry = ref<ImportEntry>()
const page = ref(1)
const images = ref<{ path: string; data: string }[]>([])
const imageLoading = ref(false)
const preview = ref(false)
const uploadPlan = ref<ImportPlan[]>()
const archivePage = ref(1)
interface FileProgress { batch_id: string; completed: number; total: number; path: string }
const uploadProgress = ref<FileProgress>()
const stageProgress = ref<FileProgress>()
const recycleFiles = ref<string[]>()
const loadingStep = ref(false)
const stepError = ref('')
const preparing = ref<boolean>()
let requestNumber = 0
const shotEntry = ref<ImportEntry>()
const shotAt = ref('')
const pageSize = 30

const roleLabels: Record<ImportSourceRole, string> = {
  local: '本地原片', retained: 'iPad 留存', favorite: 'iPad 收藏', starting: 'iPad 起始范围',
}
const roles = Object.entries(roleLabels).map(([value, label]) => ({ label, value }))
const hasIPadRetained = computed(() => sources.value.some((source) => source.role === 'retained'))
const hasIPadStarting = computed(() => sources.value.some((source) => source.role === 'starting'))
const usesCompleteExport = computed(() => hasIPadRetained.value && hasIPadStarting.value && complete.value)
const needsScan = computed(() => {
  const saved = batch.value
  return !saved || saved.complete !== usesCompleteExport.value || saved.sources.length !== sources.value.length ||
    sources.value.some((source, index) => source.path !== saved.sources[index].path || source.role !== saved.sources[index].role)
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
const steps = [
  { key: 'prepare', title: '准备照片' }, { key: 'review', title: '选片' },
  { key: 'reject', title: '回收废片' }, { key: 'archive', title: '入库' },
  { key: 'keep', title: '回收已入库' }, { key: 'finish', title: '完成批次' },
]
const step = computed(() => {
  if (!batch.value) return 'prepare'
  const saved = batch.value.step ?? 'review'
  if (saved === 'review' && (preparing.value ?? (stagedCount.value < stageCandidates.value.length))) return 'prepare'
  return saved
})
const stepNumber = computed(() => step.value === 'done' ? steps.length : steps.findIndex((item) => item.key === step.value) + 1)
const recycleKind = computed(() => step.value === 'reject' ? 'discarded' : 'imported')
const recycleGroups = computed(() => {
  const groups = batch.value?.recycling ?? []
  const relevant = step.value === 'done' || step.value === 'finish' ? groups : groups.filter((group) => group.kind === recycleKind.value)
  const latest = new Map(relevant.flatMap((group) => group.files.map((file) => [file.source, file] as const)))
  return relevant.filter((group) => group.directory || group.files.some((file) => latest.get(file.source) === file))
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
const favoriteCount = computed(() => stagedEntries.value.filter((entry) => entry.decision === 'favorite').length)
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
    if (filter.value === 'favorite') return entry.decision === 'favorite' && canPreview(entry)
    return canPreview(entry)
  })
  return list.filter((entry) => {
    const group = groupByEntry.value.get(entry.id)
    return !group || group[0] === entry.id
  }).sort((a, b) => (a.shot_at ?? '').localeCompare(b.shot_at ?? ''))
})
const shown = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const groupMembers = computed(() => openGroup.value.flatMap((id) => {
  const entry = entriesByID.value.get(id)
  return entry && entry.decision !== 'discarded' && canPreview(entry) ? [photoCard(entry)] : []
}))
const progressValue = computed(() => {
  const state = progress.value
  return state && state.total ? Math.min(100, Math.round(state.done / state.total * 100)) : 0
})

watch([filter, viewLevel], () => { page.value = 1 })
watch([() => batch.value?.id, step, () => settings.backendUrl], () => { void loadStep() })
watch(groupMembers, (members) => { if (!members.length && openGroup.value.length) openGroup.value = [] })
watch(filtered, (list) => { page.value = Math.min(page.value, Math.max(1, Math.ceil(list.length / pageSize))) })

async function perform(label: string, fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = label
  try { await fn() } catch (error) { message.error(wailsError(error)) }
  finally { busy.value = '' }
}

async function refreshBatches() {
  batches.value = (await getImportBatchApp().ListImportBatches()).map((item) => ({
    label: item.name || item.activity, value: item.id,
  }))
}

async function selectBatch(id: string | null) {
  await perform('打开批次', async () => {
    const loaded = id ? await getImportBatchApp().GetImportBatch(id) : undefined
    batch.value = loaded
    preparing.value = undefined
    uploadProgress.value = undefined
    stageProgress.value = undefined
    activity.value = loaded?.activity ?? ''
    sources.value = loaded?.sources.slice() ?? []
    complete.value = loaded?.complete ?? false
    filter.value = 'all'
    openGroup.value = []
    progress.value = undefined
    page.value = 1
  })
}

async function addSource() {
  await perform('选择目录', async () => {
    const picked = await getImportBatchApp().ChooseImportSource()
    if (!picked || sources.value.some((source) => source.path === picked && source.role === role.value)) return
    sources.value.push({ path: picked, role: role.value })
  })
}

async function scan() {
  await perform('扫描来源', async () => {
    batch.value = await getImportBatchApp().ScanImportBatch(
      batch.value?.id ?? '', activity.value.trim(), sources.value,
      usesCompleteExport.value,
    )
    preparing.value = undefined
    openGroup.value = []
    await refreshBatches()
  })
}

async function runGrouping() {
  const current = batch.value
  if (!current || grouping.value) return
  grouping.value = true
  progress.value = { batch_id: current.id, done: 0, failed: 0, total: stagedEntries.value.length, message: '服务器正在计算连拍组' }
  try {
    batch.value = await getImportBatchApp().GroupImportBatch(current.id, settings.backendUrl)
    filter.value = 'all'
    if (viewLevel.value === 'all') viewLevel.value = 'fine'
  } catch (error) {
    const reason = wailsError(error)
    if (reason.includes('context canceled')) message.info('已取消连拍计算')
    else message.error(reason)
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
  const otherIDs = groupMembers.value.filter((member) => member.id !== id).map((member) => member.id)
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

function openBurst(coverID: string) {
  openGroup.value = groupByEntry.value.get(coverID) ?? []
}

function showDetail(id: string) {
  const entry = entriesByID.value.get(id)
  if (entry) void viewImages([entry])
}

function canPreview(entry: ImportEntry) {
  return !!entry.jpg && (isStaged(entry) || !!entry.upload?.verified || !!entry.reference_only)
}

async function viewImages(entries: ImportEntry[]) {
  const list = entries.filter(canPreview)
  if (!list.length) return
  previewEntry.value = list[0]
  preview.value = true
  images.value = []
  imageLoading.value = true
  try {
    images.value = await Promise.all(list.map(async (entry) => {
      const jpg = entry.jpg!
      const data = entry.reference_only
        ? `data:image/jpeg;base64,${await wailsApi.previewImage(jpg.path)}`
        : imageURL(entry)
      return { path: jpg.path, data }
    }))
  } catch (error) { message.error(wailsError(error)) }
  finally { imageLoading.value = false }
}

function stageJPGs() {
  return perform('上传 JPG 到服务器', async () => {
    if (!batch.value) return
    stageProgress.value = { batch_id: batch.value.id, completed: 0, total: stageCandidates.value.length, path: '' }
    batch.value = await getImportBatchApp().StageImportJPGs(batch.value.id, settings.backendUrl)
    const failed = batch.value.entries.filter((entry) => entry.stage_error).length
    if (failed) message.warning(`${failed} 张 JPG 暂存失败，可重试`)
    else preparing.value = false
  })
}

async function loadStep() {
  const id = batch.value?.id
  const current = step.value
  const server = settings.backendUrl
  const request = ++requestNumber
  recycleFiles.value = undefined
  uploadPlan.value = undefined
  stepError.value = ''
  loadingStep.value = false
  if (!id || (current !== 'archive' && current !== 'reject' && current !== 'keep')) return
  loadingStep.value = true
  if (current === 'archive') archivePage.value = 1
  try {
    if (current === 'archive') {
      const plans = await getImportBatchApp().PreviewImportUploads(id, server)
      if (request === requestNumber) uploadPlan.value = plans
    } else {
      const files = await getImportBatchApp().PreviewImportRecycle(id, current === 'reject' ? 'discarded' : 'imported')
      if (request === requestNumber) recycleFiles.value = files.map((file) => file.source)
    }
  } catch (error) {
    if (request === requestNumber) stepError.value = wailsError(error)
  } finally {
    if (request === requestNumber) loadingStep.value = false
  }
}

function upload() {
  const plans = readyPlans.value
  return perform('上传原片', async () => {
    if (!batch.value || !plans.length) return
    uploadProgress.value = { batch_id: batch.value.id, completed: 0, total: plans.length, path: '' }
    batch.value = await getImportBatchApp().UploadImportBatch(batch.value.id, settings.backendUrl, plans)
    const verified = batch.value.entries.filter((entry) => entry.upload?.verified).length
    const failed = batch.value.entries.filter((entry) => entry.upload?.error).length
    message[failed ? 'warning' : 'success'](`已核验 ${verified} 张，待重试 ${failed} 张`)
    await loadStep()
  })
}

function advance(next: ImportStep, leaveLocal = false) {
  return perform('切换导入步骤', async () => {
    if (!batch.value) return
    batch.value = await getImportBatchApp().AdvanceImportBatch(batch.value.id, next, leaveLocal)
    if (next === 'review') {
      preparing.value = false
      filter.value = 'all'
    }
    openGroup.value = []
  })
}

function submitRecycle() {
  const paths = recycleFiles.value
  const kind = recycleKind.value
  return perform('处理本地文件', async () => {
    if (!batch.value || !paths?.length) return
    batch.value = await getImportBatchApp().RecycleImportFiles(batch.value.id, kind, paths, false)
    await loadStep()
  })
}

function finishBatch() {
  return perform('清理服务器暂存', async () => {
    if (!batch.value) return
    batch.value = await getImportBatchApp().FinishImportBatch(batch.value.id)
    message.success('批次已完成')
  })
}

function restoreLocal(directory: string) {
  return perform('恢复本地原片', async () => {
    if (!batch.value) return
    batch.value = await getImportBatchApp().RestoreImportDirectory(batch.value.id, directory)
    await loadStep()
  })
}

function resolvePair(entry: ImportEntry, path: string) {
  return perform('保存配对', async () => {
    if (batch.value) batch.value = await getImportBatchApp().ResolveImportPair(batch.value.id, entry.id, path)
  })
}

function editShotAt(entry: ImportEntry) {
  shotEntry.value = entry
  shotAt.value = entry.shot_at ?? ''
}

function saveShotAt() {
  return perform('保存拍摄时间', async () => {
    if (!batch.value || !shotEntry.value) return
    batch.value = await getImportBatchApp().SetImportShotAt(batch.value.id, shotEntry.value.id, shotAt.value)
    shotEntry.value = undefined
  })
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
    if (value.batch_id === batch.value?.id) stageProgress.value = value
  })
})
onUnmounted(() => {
  if (grouping.value) void getImportBatchApp().CancelImportBursts()
  unsubscribeBurst()
  unsubscribeUpload()
  unsubscribeStage()
})
</script>

<template>
  <div class="batch-workflow">
    <NCard title="导入批次">
      <NSpace align="center">
        <NSelect :value="batch?.id ?? null" :options="batches" placeholder="继续已有批次" clearable
          :disabled="!!busy || grouping" style="width: 280px" @update:value="selectBatch" />
        <NButton v-if="batch" :disabled="!!busy || grouping" @click="selectBatch(null)">新建批次</NButton>
      </NSpace>
      <NSteps class="form-row" :current="stepNumber" :status="step === 'done' ? 'finish' : 'process'" size="small">
        <NStep v-for="item in steps" :key="item.key" :title="item.title" />
      </NSteps>
    </NCard>

    <NCard v-if="step === 'prepare'" title="准备照片">
      <NFormItem label="服务器活动目录" class="form-row">
        <NInput v-model:value="activity" :disabled="!!batch || !!busy" placeholder="例如 202611-桂林" />
      </NFormItem>
      <NSpace align="center">
        <NSelect v-model:value="role" :options="roles" style="width: 180px" />
        <NButton :disabled="!!busy || grouping" @click="addSource">添加目录</NButton>
        <NButton :type="needsScan ? 'primary' : 'default'" :loading="busy === '扫描来源'"
          :disabled="!activity.trim() || !sources.length || !!busy || grouping" @click="scan">{{ batch ? '重新扫描来源' : '扫描来源' }}</NButton>
      </NSpace>
      <ul v-if="sources.length" class="paths">
        <li v-for="(source, index) in sources" :key="`${source.role}/${source.path}`">
          <span>{{ roleLabels[source.role] }} · {{ source.path }}</span>
          <NButton text :disabled="!!busy || grouping" @click="sources.splice(index, 1)">移除</NButton>
        </li>
      </ul>
      <fieldset v-if="hasIPadStarting" class="ipad-options">
        <legend>如何使用 iPad 的筛片结果</legend>
        <div v-if="hasIPadRetained && hasIPadStarting">
          <NCheckbox v-model:checked="complete" :disabled="!!busy || grouping">
            根据完整导出找出待确认废片
          </NCheckbox>
          <p>确认这是完整的导出。属于 iPad 起始范围、且在留存和收藏中都找不到的照片会列为待确认废弃。</p>
        </div>
        <p v-else-if="hasIPadStarting">添加 iPad 留存目录后，即可对照导出核对废片。</p>
      </fieldset>
      <NAlert v-if="batch?.issues.length" type="warning" title="部分来源读取失败" class="form-row">
        <div v-for="(issue, index) in batch.issues" :key="index">{{ issue }}</div>
      </NAlert>
      <div v-if="batch && !needsScan" class="form-row">
        <NSpace align="center">
          <span>服务器已暂存 {{ stagedCount }} / {{ stageCandidates.length }} 张 JPG</span>
          <NButton v-if="stagedCount < stageCandidates.length" type="primary" :disabled="!!busy || grouping"
            :loading="busy === '上传 JPG 到服务器'" @click="stageJPGs">上传 JPG 并进入选片</NButton>
          <NButton v-if="stagedCount || !stageCandidates.length" :type="stagedCount === stageCandidates.length ? 'primary' : 'default'" :disabled="!!busy || grouping"
            @click="preparing = false">进入选片</NButton>
        </NSpace>
        <div v-if="stageProgress && busy === '上传 JPG 到服务器'" aria-live="polite">
          <NProgress :percentage="Math.round(stageProgress.completed / Math.max(1, stageProgress.total) * 100)" processing />
          <p>{{ stageProgress.completed }} / {{ stageProgress.total }} 张</p>
        </div>
      </div>
    </NCard>

    <template v-if="batch">
      <NCard v-if="step === 'review'" title="选片">
        <template #header-extra>
          <NSpace>
            <NButton :disabled="!!busy || grouping" @click="preparing = true">返回准备照片</NButton>
            <NButton type="primary" :disabled="!batch.entries.length || !!busy || grouping" @click="advance('reject')">选片完成，下一步</NButton>
          </NSpace>
        </template>
        <NSpace align="center">
          <span>{{ stagedEntries.length }} 张可选 · {{ favoriteCount }} 张收藏 · {{ deletedCount }} 张标记删除</span>
          <NButton :disabled="!stagedEntries.length || grouping || !!busy" :loading="grouping" @click="runGrouping">计算连拍组</NButton>
          <NButton v-if="grouping" @click="getImportBatchApp().CancelImportBursts()">取消计算</NButton>
          <NSelect v-model:value="viewLevel" :options="viewLevels" :disabled="filter !== 'all' || !batch.bursts"
            style="width: 128px" aria-label="连拍展示" />
        </NSpace>
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
              @view-detail="showDetail" @open-burst-group="openBurst">
              <template #actions>
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
        <NSpin v-if="loadingStep" />
        <NAlert v-else-if="stepError" type="error">{{ stepError }} <NButton text @click="loadStep">重试</NButton></NAlert>
        <template v-else-if="recycleFiles">
          <p v-if="recycleFiles.length">将 {{ recycleFiles.length }} 个本地文件移入 Windows 回收站，目录名为「{{ batch.name }}{{ step === 'reject' ? '-reject' : '-keep' }}」。</p>
          <p v-else>{{ recycleGroups.length ? '这一项已处理。' : '这一步没有需要回收的文件。' }}</p>
          <NSpace>
            <NButton v-if="step === 'reject'" :disabled="!!busy" @click="advance('review')">返回选片</NButton>
            <NButton v-if="recycleFiles.length > 0" type="primary" :loading="busy === '处理本地文件'" :disabled="!!busy"
              @click="submitRecycle">{{ recycleFailed ? '重试回收' : step === 'reject' ? '回收废片' : '回收已入库' }}</NButton>
            <NButton v-if="!recycleFiles.length" type="primary" :disabled="!!busy"
              @click="advance(step === 'reject' ? 'archive' : 'finish')">{{ step === 'reject' ? '下一步，入库' : '下一步，完成批次' }}</NButton>
            <NButton v-else-if="recycleFailed" :disabled="!!busy" @click="advance(step === 'reject' ? 'archive' : 'finish', true)">剩余文件留在原处，继续</NButton>
          </NSpace>
        </template>
      </NCard>

      <NCard v-if="step === 'archive'" title="入库">
        <template #header-extra>
          <NButton v-if="archiveEntries.length" type="primary" :loading="busy === '上传原片'"
            :disabled="!readyPlans.length || !!busy || loadingStep" @click="upload">确认入库</NButton>
          <NButton v-else type="primary" :disabled="!uploadPlan || !!busy" @click="advance('keep')">下一步，回收已入库</NButton>
        </template>
        <p>服务器活动目录 {{ batch.activity }} · 已核验 {{ verifiedCount }} 张</p>
        <NAlert v-if="excludedCount" type="warning">{{ excludedCount }} 张照片仍需核对来源或配对，未列入本次入库。</NAlert>
        <NSpace v-if="loadingStep" align="center"><NSpin size="small" />正在核对入库文件</NSpace>
        <NAlert v-else-if="stepError" type="error">{{ stepError }} <NButton text @click="loadStep">重试</NButton></NAlert>
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
          <NButton v-if="uploadPlan && uploadPlan.length > readyPlans.length" :disabled="!!busy" @click="loadStep">重新检查入库</NButton>
        </NSpace>
      </NCard>

      <NCard v-if="step === 'finish' || step === 'done'" :title="step === 'done' ? '批次已完成' : '完成批次'">
        <p>已核验 {{ verifiedCount }} 张照片。{{ step === 'done' ? '服务器暂存已清理。' : '完成后清理本批次的服务器暂存 JPG 和缩略图。' }}</p>
        <p v-if="excludedCount">{{ excludedCount }} 张照片因来源或配对待核对，未入库。</p>
        <NButton v-if="step === 'finish'" type="primary" :loading="busy === '清理服务器暂存'" :disabled="!!busy" @click="finishBatch">完成批次并清理暂存</NButton>
        <NButton v-else type="primary" :disabled="!!busy" @click="selectBatch(null)">开始新批次</NButton>
      </NCard>

      <NCard v-if="recycleGroups.length && ['reject', 'keep', 'finish', 'done'].includes(step)" title="回收结果">
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
          <details v-if="group.directory && group.status !== 'restored'">
            <summary>恢复原片</summary>
            <p>请先在 Windows 回收站还原目录，再核对并恢复到各自的原路径。</p>
            <NButton size="small" :disabled="!!busy" @click="restoreLocal(group.directory)">核对并恢复原路径</NButton>
          </details>
        </div>
      </NCard>
    </template>

    <BurstGroupModal :show="groupMembers.length > 0" :group-id="openGroup[0] ?? ''"
      :members="groupMembers" :cover-id="groupMembers[0]?.id ?? ''" :loading="false" mode="browse"
      @close="openGroup = []" @view-detail="showDetail">
      <template #actions="{ selected }">
        <NSpace>
          <NButton size="small" :disabled="!!busy || grouping" @click="toggleFavorite([selected.id])">{{ favoriteLabel([selected.id]) }}</NButton>
          <NButton size="small" type="error" secondary :disabled="!!busy || grouping" @click="decide([selected.id], 'discarded')">删除当前照片</NButton>
          <NButton size="small" type="error" secondary :disabled="!!busy || grouping || groupMembers.length < 2"
            @click="keepOnlyCurrent(selected.id)">只保留当前照片</NButton>
          <NButton size="small" :disabled="!!busy || grouping" @click="toggleFavorite(groupMembers.map((item) => item.id))">{{ favoriteLabel(groupMembers.map((item) => item.id)) }}</NButton>
          <NButton size="small" type="error" secondary :disabled="!!busy || grouping" @click="decide(groupMembers.map((item) => item.id), 'discarded')">删除整组</NButton>
        </NSpace>
      </template>
    </BurstGroupModal>

    <NModal v-model:show="preview" preset="card" title="审阅原片" class="preview-modal">
      <NSpin :show="imageLoading"><div class="compare">
        <figure v-for="item in images" :key="item.path">
          <img v-if="item.data" :src="item.data" :alt="item.path" @error="item.data = ''" />
          <NEmpty v-else description="无法读取照片预览" />
          <figcaption>{{ item.path }}</figcaption>
        </figure>
      </div></NSpin>
      <NSpace v-if="previewEntry" align="center" class="form-row">
        <span v-if="previewEntry.nef">{{ previewEntry.nef.path }}</span>
        <NButton v-if="canEdit(previewEntry) && !previewEntry.reference_only && !previewEntry.upload" text :disabled="!!busy || grouping"
          @click="editShotAt(previewEntry)">{{ previewEntry.shot_at || '填写拍摄时间' }}</NButton>
      </NSpace>
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
.ipad-options { display: grid; gap: 8px; margin: 16px 0 0; padding: 8px 16px; border: 1px solid var(--n-border-color); }
.ipad-options p { margin: 4px 0 0; }
.paths { margin: 8px 0 16px; padding: 0; list-style: none; overflow-wrap: anywhere; }
.paths li { padding: 4px 0; }
.paths li .n-button { margin-left: 8px; }
.review-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 16px; padding: 0; list-style: none; }
.review-grid li { min-width: 0; overflow-wrap: anywhere; }
.review-actions { margin-top: 8px; }
.review-issues { display: grid; gap: 8px; padding: 8px 0; }
.batch-modal { width: min(760px, 90vw); }
.preview-modal { width: min(1320px, 94vw); }
.compare { display: flex; gap: 16px; }
.compare figure { margin: 0; flex: 1; min-width: 0; }
.compare img { display: block; width: 100%; height: min(60vh, 620px); object-fit: contain; }
.compare figcaption { overflow-wrap: anywhere; }
</style>
