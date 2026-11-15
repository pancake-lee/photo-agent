<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NAlert, NButton, NCard, NCheckbox, NEmpty, NFormItem, NInput, NModal,
  NPagination, NProgress, NSelect, NSpace, NSpin, NTag, useMessage,
} from 'naive-ui'
import { getImportBatchApp } from '../utils/importBatch'
import type {
  ImportBatch, ImportCullProgress, ImportDecision, ImportEntry, ImportPlan, ImportSource, ImportSourceRole,
} from '../utils/importBatch'
import { onWailsEvent, wailsApi, wailsError } from '../utils/wails'
import { settings } from '../stores/settings'
import { getApiBase } from '../config'

const message = useMessage()
const keepPlan = ref<string[]>([])
const batch = ref<ImportBatch>()
const batches = ref<{ label: string; value: string }[]>([])
const activity = ref('')
const sources = ref<ImportSource[]>([])
const role = ref<ImportSourceRole>('local')
const reviewed = ref(false)
const complete = ref(false)
const busy = ref('')
const culling = ref(false)
const progress = ref<ImportCullProgress>()
const scene = ref('auto')
const filter = ref('all')
const page = ref(1)
const choice = ref<string[]>([])
const images = ref<{ path: string; data: string }[]>([])
const imageLoading = ref(false)
const preview = ref(false)
const uploadPlan = ref<ImportPlan[]>()
const uploadServer = ref('')
interface FileProgress { batch_id: string; completed: number; total: number; path: string }
const uploadProgress = ref<FileProgress>()
const stageProgress = ref<FileProgress>()
const recycle = ref<{ kind: string; files: string[]; permanent: boolean }>()
const shotEntry = ref<ImportEntry>()
const shotAt = ref('')
const pageSize = 30

const roleLabels: Record<ImportSourceRole, string> = {
  local: '本地原片', retained: 'iPad 留存', favorite: 'iPad 收藏', starting: 'iPad 起始范围',
}
const roles = Object.entries(roleLabels).map(([value, label]) => ({ label, value }))
const hasIPadRetained = computed(() => sources.value.some((source) => source.role === 'retained'))
const hasIPadStarting = computed(() => sources.value.some((source) => source.role === 'starting'))
const decisions: { value: ImportDecision; label: string; key: string }[] = [
  { value: 'kept', label: '留存', key: '1' },
  { value: 'favorite', label: '收藏', key: '2' },
  { value: 'discarded', label: '废弃', key: '3' },
  { value: 'later', label: '稍后审阅', key: '4' },
  { value: 'pending', label: '待审', key: '0' },
]
const decisionLabel = (entry: ImportEntry) => decisions.find((row) => row.value === entry.decision)?.label
const filters = [
  { label: '全部照片', value: 'all' },
  { label: '推荐（2 星及以上）', value: 'recommended' },
  { label: '低分', value: 'low' },
  { label: '待审', value: 'pending' },
  { label: '需核对', value: 'review' },
]
const scenes = Object.entries({
  auto: '自动', landscape: '风景', portrait: '人像', event: '活动',
  concert: '演出', wedding: '婚礼', sports: '运动', generic: '通用',
}).map(([value, label]) => ({ label, value }))
function canStage(entry: ImportEntry) {
  return !!entry.jpg && !entry.reference_only && !entry.historical && !entry.upload?.verified
}
function isStaged(entry: ImportEntry) {
  return !!settings.backendUrl && entry.staged_server === settings.backendUrl
}
const stageCandidates = computed(() => batch.value?.entries.filter(canStage) ?? [])
const stagedCount = computed(() => stageCandidates.value.filter(isStaged).length)
const stagedPending = computed(() => stageCandidates.value.filter((entry) =>
  isStaged(entry) && entry.decision === 'pending' && !entry.conflict && entry.pair !== 'review',
))
const selected = computed(() => batch.value?.entries.filter((entry) => choice.value.includes(entry.id)) ?? [])
const pendingCount = computed(() => batch.value?.entries.filter((entry) => entry.decision === 'pending' && entry.jpg && !entry.reference_only && !entry.historical).length ?? 0)
const pendingBatch = computed(() => selected.value.filter((entry) =>
  entry.jpg && isStaged(entry) && entry.decision === 'pending' && !entry.conflict && !entry.reference_only && entry.pair !== 'review',
))
const filtered = computed(() => {
  const entries = batch.value?.entries ?? []
  const list = entries.filter((entry) => {
    if (filter.value === 'recommended') return (entry.score?.rating ?? 0) >= 2
    if (filter.value === 'low') return !!entry.score && entry.score.rating < 2
    if (filter.value === 'review') return entry.pair === 'review' || entry.conflict || entry.missing_from_export || !entry.jpg
    if (filter.value === 'pending') return entry.decision === 'pending'
    return true
  })
  return list.slice().sort((a, b) =>
    (b.score?.rating ?? 0) - (a.score?.rating ?? 0) ||
    (a.score?.rank && a.score.rank > 0 ? a.score.rank : Infinity) -
    (b.score?.rank && b.score.rank > 0 ? b.score.rank : Infinity),
  )
})
const shown = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const progressValue = computed(() => {
  const state = progress.value
  return state && state.total ? Math.min(100, Math.round(state.done / state.total * 100)) : 0
})

watch(filter, () => { page.value = 1 })
watch(filtered, (list) => { page.value = Math.min(page.value, Math.max(1, Math.ceil(list.length / pageSize))) })

async function perform(label: string, fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = label
  try { await fn() } catch (error) { message.error(wailsError(error)) }
  finally { busy.value = '' }
}

async function refreshBatches() {
  batches.value = (await getImportBatchApp().ListImportBatches()).map((item) => ({
    label: `${item.activity} · ${item.id.slice(0, 8)}`, value: item.id,
  }))
}

async function selectBatch(id: string | null) {
  await perform('打开批次', async () => {
    const loaded = id ? await getImportBatchApp().GetImportBatch(id) : undefined
    batch.value = loaded
    uploadProgress.value = undefined
    stageProgress.value = undefined
    activity.value = loaded?.activity ?? ''
    sources.value = loaded?.sources.slice() ?? []
    reviewed.value = loaded?.reviewed ?? false
    complete.value = loaded?.complete ?? false
    choice.value = []
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
      hasIPadRetained.value && reviewed.value,
      hasIPadRetained.value && hasIPadStarting.value && complete.value,
    )
    choice.value = []
    await refreshBatches()
  })
}

async function runCull() {
  const current = batch.value
  if (!current || culling.value) return
  culling.value = true
  progress.value = { batch_id: current.id, done: 0, failed: 0, total: stagedPending.value.length, message: '服务器正在准备待审照片' }
  try {
    batch.value = await getImportBatchApp().AnalyzeImportBatch(current.id, settings.backendUrl, scene.value)
    if (batch.value.entries.some((entry) => entry.score)) filter.value = 'recommended'
  } catch (error) {
    const reason = wailsError(error)
    if (reason.includes('context canceled')) message.info('已取消初筛')
    else message.error(reason)
  } finally {
    culling.value = false
  }
}

function decide(ids: string[], value: ImportDecision, pendingOnly = false) {
  return perform('保存审阅决定', async () => {
    if (batch.value) batch.value = await getImportBatchApp().DecideImportBatch(batch.value.id, ids, value, pendingOnly)
  })
}

async function bulkKeep() {
  await decide(keepPlan.value, 'kept', true)
  keepPlan.value = []
}

function toggle(id: string, enabled: boolean) {
  choice.value = enabled ? [...choice.value, id] : choice.value.filter((value) => value !== id)
}

function canPreview(entry: ImportEntry) {
  return !!entry.jpg && (isStaged(entry) || !!entry.upload?.verified || !!entry.reference_only)
}

async function viewImages(entries: ImportEntry[]) {
  const list = entries.filter(canPreview)
  if (!list.length) return
  preview.value = true
  images.value = []
  imageLoading.value = true
  try {
    images.value = await Promise.all(list.map(async (entry) => {
      const jpg = entry.jpg!
      const query = new URLSearchParams({ batch_id: batch.value?.id ?? '', sha256: jpg.sha256 })
      const photoID = entry.upload?.photo_id
      const data = entry.upload?.verified && photoID
        ? `${getApiBase()}/photos/${encodeURIComponent(photoID)}/image`
        : entry.reference_only
          ? `data:image/jpeg;base64,${await wailsApi.previewImage(jpg.path)}`
          : `${getApiBase()}/photo-import/stage/image?${query}`
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
  })
}

function keyboard(event: KeyboardEvent) {
  if (event.ctrlKey || event.altKey || event.metaKey || busy.value || !batch.value ||
      event.target instanceof HTMLElement && event.target.closest('input, textarea, button, [contenteditable], [role="combobox"]')) return
  if (keepPlan.value.length || uploadPlan.value || recycle.value || shotEntry.value || selected.value.length !== 1) return
  const entry = selected.value[0]
  if (!entry?.jpg || entry.historical || entry.upload?.verified || (!isStaged(entry) && !entry.reference_only)) return
  const decision = decisions.find((item) => item.key === event.key)
  if (decision) {
    event.preventDefault()
    void decide([entry.id], decision.value)
  }
}

function previewUpload() {
  return perform('核对归档目标', async () => {
    if (!batch.value) return
    uploadServer.value = settings.backendUrl
    const result = await getImportBatchApp().PreviewImportUploads(batch.value.id, uploadServer.value)
    if (!result.length) { message.info('暂无可提交的留存或收藏照片'); return }
    uploadPlan.value = result
  })
}

function upload() {
  const plans = uploadPlan.value?.filter((item) => !item.plan.error)
  return perform('上传原片', async () => {
    if (!batch.value || !plans?.length) return
    uploadProgress.value = { batch_id: batch.value.id, completed: 0, total: plans.length, path: '' }
    batch.value = await getImportBatchApp().UploadImportBatch(batch.value.id, uploadServer.value, plans)
    uploadPlan.value = undefined
    const verified = batch.value.entries.filter((entry) => entry.upload?.verified).length
    const failed = batch.value.entries.filter((entry) => entry.upload?.error).length
    message[failed ? 'warning' : 'success'](`已核验 ${verified} 张，待重试 ${failed} 张`)
  })
}

function previewRecycle(kind: string, permanent = false) {
  return perform('准备回收清单', async () => {
    if (!batch.value) return
    const files = await getImportBatchApp().PreviewImportRecycle(batch.value.id, kind)
    if (!files.length) { message.info('暂无可处理的本地文件'); return }
    recycle.value = { kind, files: files.map((file) => file.source), permanent }
  })
}

function submitRecycle() {
  const plan = recycle.value
  return perform('处理本地文件', async () => {
    if (!batch.value || !plan) return
    batch.value = await getImportBatchApp().RecycleImportFiles(batch.value.id, plan.kind, plan.files, plan.permanent)
    recycle.value = undefined
  })
}

function restoreLocal(directory: string) {
  return perform('恢复本地原片', async () => {
    if (batch.value) batch.value = await getImportBatchApp().RestoreImportDirectory(batch.value.id, directory)
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

let unsubscribeCull = () => {}
let unsubscribeUpload = () => {}
let unsubscribeStage = () => {}
onMounted(() => {
  void perform('读取批次', refreshBatches)
  unsubscribeCull = onWailsEvent<ImportCullProgress>('import:cull', (value) => {
    if (value.batch_id === batch.value?.id) progress.value = value
  })
  unsubscribeUpload = onWailsEvent<FileProgress>('import:upload', (value) => {
    if (value.batch_id === batch.value?.id) uploadProgress.value = value
  })
  unsubscribeStage = onWailsEvent<FileProgress>('import:stage', (value) => {
    if (value.batch_id === batch.value?.id) stageProgress.value = value
  })
  window.addEventListener('keydown', keyboard)
})
onUnmounted(() => {
  if (culling.value) void getImportBatchApp().CancelImportCull()
  unsubscribeCull()
  unsubscribeUpload()
  unsubscribeStage()
  window.removeEventListener('keydown', keyboard)
})
</script>

<template>
  <div class="batch-workflow">
    <NCard title="导入批次">
      <NSpace align="center">
        <NSelect :value="batch?.id ?? null" :options="batches" placeholder="继续已有批次" clearable
          :disabled="!!busy || culling" style="width: 280px" @update:value="selectBatch" />
        <NButton :disabled="!batch || !!busy || culling" @click="selectBatch(null)">新建批次</NButton>
      </NSpace>
      <NFormItem label="服务器活动目录" class="form-row">
        <NInput v-model:value="activity" :disabled="!!batch || !!busy" placeholder="例如 202611-桂林" />
      </NFormItem>
      <NSpace align="center">
        <NSelect v-model:value="role" :options="roles" style="width: 180px" />
        <NButton :disabled="!!busy || culling" @click="addSource">添加目录</NButton>
        <NButton type="primary" :loading="busy === '扫描来源'" :disabled="!activity.trim() || !sources.length || !!busy || culling" @click="scan">扫描来源</NButton>
      </NSpace>
      <ul v-if="sources.length" class="paths">
        <li v-for="(source, index) in sources" :key="`${source.role}/${source.path}`">
          <span>{{ roleLabels[source.role] }} · {{ source.path }}</span>
          <NButton text :disabled="!!busy || culling" @click="sources.splice(index, 1)">移除</NButton>
        </li>
      </ul>
      <fieldset v-if="hasIPadRetained || hasIPadStarting" class="ipad-options">
        <legend>如何使用 iPad 的筛片结果</legend>
        <div v-if="hasIPadRetained">
          <NCheckbox v-model:checked="reviewed" :disabled="!!busy || culling">
            把 iPad 留存目录中匹配到的照片标为留存
          </NCheckbox>
          <p>只粗筛过就留空，匹配到的照片仍可参与初筛。iPad 收藏照会标为收藏。</p>
        </div>
        <div v-if="hasIPadRetained && hasIPadStarting">
          <NCheckbox v-model:checked="complete" :disabled="!!busy || culling">
            根据完整导出找出待确认废片
          </NCheckbox>
          <p>确认这是完整的导出。属于 iPad 起始范围、且在留存和收藏中都找不到的照片会列为待确认废弃。</p>
        </div>
        <p v-else-if="hasIPadStarting">添加 iPad 留存目录后，即可对照导出核对废片。</p>
      </fieldset>
      <NAlert v-if="batch?.issues.length" type="warning" title="部分来源读取失败" class="form-row">
        <div v-for="(issue, index) in batch.issues" :key="index">{{ issue }}</div>
      </NAlert>
    </NCard>

    <template v-if="batch">
      <NCard title="上传待审 JPG">
        <NSpace align="center">
          <span>服务器已暂存 {{ stagedCount }} / {{ stageCandidates.length }} 张 JPG</span>
          <NButton type="primary" :disabled="!stageCandidates.length || !!busy || culling"
            :loading="busy === '上传 JPG 到服务器'" @click="stageJPGs">上传 JPG 到服务器</NButton>
        </NSpace>
        <p>先上传 JPG，再初筛或人工审阅。确认入库时补传所选照片的 NEF。</p>
        <div v-if="stageProgress && busy === '上传 JPG 到服务器'" aria-live="polite">
          <NProgress :percentage="Math.round(stageProgress.completed / Math.max(1, stageProgress.total) * 100)" processing />
          <p>{{ stageProgress.completed }}/{{ stageProgress.total }} · {{ stageProgress.path }}</p>
        </div>
      </NCard>
      <NCard title="批次审阅">
        <NSpace align="center">
          <span>{{ batch.entries.length }} 条 · {{ pendingCount }} 张待审</span>
          <NSelect v-model:value="scene" :options="scenes" style="width: 110px" />
          <NButton :disabled="!stagedPending.length || culling || !!busy" :loading="culling" @click="runCull">服务器 AutoCull 初筛</NButton>
          <NButton :disabled="!culling" @click="getImportBatchApp().CancelImportCull()">取消初筛</NButton>
          <NButton :disabled="!!busy || culling || !batch.entries.some((entry) => entry.score)" @click="perform('清除评分', async () => { if (batch) batch = await getImportBatchApp().ClearImportCull(batch.id) })">清除评分</NButton>
        </NSpace>
        <div v-if="progress" class="form-row" aria-live="polite">
          <NProgress :percentage="progressValue" :processing="culling" />
          <p>{{ progress.message }} · {{ progress.done }}/{{ progress.total }} · 失败 {{ progress.failed }}</p>
        </div>
        <NSpace align="center" class="form-row">
          <NSelect v-model:value="filter" :options="filters" style="width: 188px" aria-label="审阅范围" />
          <NButton :disabled="selected.filter(canPreview).length !== 2" @click="viewImages(selected)">并排比较</NButton>
          <NButton :disabled="!pendingBatch.length || !!busy" @click="keepPlan = pendingBatch.map((entry) => entry.id)">留存所选待审（{{ pendingBatch.length }}）</NButton>
          <NButton :disabled="!batch.undo?.length || !!busy" @click="perform('撤销', async () => { if (batch) batch = await getImportBatchApp().UndoImportBatch(batch.id) })">撤销</NButton>
        </NSpace>
        <NEmpty v-if="!shown.length" :description="`此范围暂无照片，待审 ${pendingCount} 张`" class="form-row" />
        <ul v-else class="entries">
          <li v-for="entry in shown" :key="entry.id" class="entry">
            <NCheckbox :checked="choice.includes(entry.id)" :aria-label="`选择 ${entry.jpg?.path ?? entry.nef?.path}`"
              @update:checked="(checked) => toggle(entry.id, checked)" />
            <div class="entry-info">
              <NButton v-if="entry.jpg" text :disabled="!canPreview(entry)" @click="viewImages([entry])">{{ entry.jpg.path }}</NButton>
              <div v-if="entry.nef">{{ entry.nef.path }}</div>
              <NAlert v-if="entry.stage_error" type="error">{{ entry.stage_error }}</NAlert>
              <div v-if="entry.reference_only">起始范围证据 · 仅处理已确认废弃的 NEF</div>
              <div v-if="entry.missing_from_export">完整导出缺席 · 待确认废弃</div>
              <div v-if="entry.conflict">审阅结果需要核对{{ entry.inherited ? ` · iPad ${decisions.find((item) => item.value === entry.inherited)?.label}` : '' }}</div>
              <div v-if="entry.score">{{ entry.score.rating }} 星 · {{ entry.score.tier }} · 排名 {{ entry.score.rank > 0 ? entry.score.rank : '—' }} · {{ entry.score.why }} <span v-if="entry.score.cluster"> · 连拍组 {{ entry.score.cluster }}</span></div>
              <div v-if="entry.upload?.verified">已核验 · {{ entry.upload.root }} / {{ entry.upload.target }}<span v-if="entry.upload.nef_target"> · {{ entry.upload.nef_target }}</span></div>
              <NAlert v-if="entry.upload?.error" type="error">{{ entry.upload.error }}</NAlert>
              <NSelect v-if="entry.pair === 'review'" :disabled="!!busy" placeholder="核对 NEF 配对"
                :options="[...(entry.reference_only ? [] : [{ label: '仅 JPG', value: '' }]), ...(entry.nef_candidates ?? []).map((file) => ({ label: file.path, value: file.path }))]"
                @update:value="(value) => resolvePair(entry, value)" />
              <NSpace v-if="entry.jpg" align="center">
                <NTag size="small">{{ entry.pair === 'review' ? '需核对' : entry.nef ? '已配对' : '仅 JPG' }}</NTag>
                <NTag size="small" :type="entry.decision === 'favorite' ? 'success' : 'default'">{{ decisionLabel(entry) }}<span v-if="entry.origin === 'ipad'"> · iPad</span></NTag>
                <NButton v-if="!entry.upload && !entry.reference_only" text @click="editShotAt(entry)">{{ entry.shot_at || '填写拍摄时间' }}</NButton>
              </NSpace>
              <div v-else>仅 NEF · 补齐 JPG 后再审阅</div>
            </div>
            <NSpace v-if="entry.jpg && !entry.historical && !entry.upload?.verified" class="decisions">
              <NButton v-for="item in decisions.filter((value) => !entry.reference_only || ['discarded', 'later', 'pending'].includes(value.value))"
                :key="item.value" size="small" :disabled="!!busy || (!isStaged(entry) && !entry.reference_only)"
                @click="decide([entry.id], item.value)">{{ item.label }} · {{ item.key }}</NButton>
            </NSpace>
          </li>
        </ul>
        <NPagination v-if="filtered.length > pageSize" v-model:page="page" :page-size="pageSize" :item-count="filtered.length" />
      </NCard>
      <NCard title="入库与本地回收">
        <NSpace>
          <NButton type="primary" :disabled="!!busy || culling" :loading="busy === '核对归档目标'" @click="previewUpload">预览入库</NButton>
          <NButton :disabled="!!busy || culling" @click="previewRecycle('imported')">回收已入库</NButton>
          <NButton :disabled="!!busy || culling" @click="previewRecycle('discarded')">回收废片</NButton>
          <NButton type="error" secondary :disabled="!!busy || culling" @click="previewRecycle('discarded', true)">永久删除废片</NButton>
        </NSpace>
        <p>待审及尚未核验的照片留在原处。</p>
        <div v-for="(group, index) in batch.recycling ?? []" :key="index" class="form-row">
          <NSpace align="center">
            <NTag>{{ ({ recycled: '已回收', retained: '原位保留', restored: '已恢复', pending: '归集中', sending: '待核对回收', uncertain: '待核对回收站', permanent: '永久删除结果' } as Record<string, string>)[group.status] ?? group.status }}</NTag>
            <span>{{ group.directory || (group.kind === 'permanent' ? '废片' : '原位置') }}</span>
            <NButton v-if="group.directory && group.status !== 'restored'" size="small" :disabled="!!busy" @click="restoreLocal(group.directory)">核对并恢复原路径</NButton>
          </NSpace>
          <div v-if="group.error">{{ group.error }}</div>
          <ul class="paths">
            <li v-for="file in group.files" :key="file.source">{{ file.source }} · {{ ({ recycled: '已回收', staged: '已归集', retained: '原位保留', restored: '已恢复', deleted: '已永久删除', pending: '待处理', deleting: '待核对删除' } as Record<string, string>)[file.status] ?? file.status }} {{ file.error }}<span v-if="file.restored_to && file.restored_to !== file.source"> · 恢复到 {{ file.restored_to }}</span></li>
          </ul>
        </div>
      </NCard>
    </template>

    <NModal :show="keepPlan.length > 0" preset="card" title="批量留存" class="batch-modal"
      @update:show="(show) => { if (!show && !busy) keepPlan = [] }">
      <p>将已选的 {{ keepPlan.length }} 张待审照片标为留存。</p>
      <NButton type="primary" :loading="busy === '保存审阅决定'" @click="bulkKeep">确认留存</NButton>
    </NModal>

    <NModal :show="!!uploadPlan" preset="card" title="确认入库" class="batch-modal" :mask-closable="!busy" @update:show="(show) => { if (!show && !busy) uploadPlan = undefined }">
      <ul class="paths">
        <li v-for="row in uploadPlan" :key="row.entry_id" class="plan">
          <div>{{ row.jpg }}<br v-if="row.nef" />{{ row.nef }}</div>
          <NAlert v-if="row.plan.error" type="error">{{ row.plan.error }}</NAlert>
          <div v-else>{{ row.plan.root }} / {{ row.plan.target }}{{ row.plan.jpg_ready ? ' · JPG 已归档' : row.plan.jpg_staged ? ' · 使用服务器暂存 JPG' : '' }}<br v-if="row.plan.nef_target" />{{ row.plan.nef_target }}</div>
        </li>
      </ul>
      <NProgress v-if="uploadProgress && busy === '上传原片'" :percentage="Math.round(uploadProgress.completed / uploadProgress.total * 100)" processing />
      <p v-if="uploadProgress && busy === '上传原片'" aria-live="polite">{{ uploadProgress.completed }}/{{ uploadProgress.total }} · {{ uploadProgress.path }}</p>
      <NButton type="primary" :loading="busy === '上传原片'" :disabled="!uploadPlan?.some((row) => !row.plan.error)" @click="upload">上传并核验</NButton>
    </NModal>

    <NModal :show="!!recycle" preset="card" :title="recycle?.permanent ? '确认永久删除废片' : '确认移入 Windows 回收站'"
      class="batch-modal" :mask-closable="!busy" @update:show="(show) => { if (!show && !busy) recycle = undefined }">
      <p v-if="recycle?.permanent">这些废片会永久删除，无法从回收站恢复。</p>
      <ul class="paths"><li v-for="path in recycle?.files" :key="path">{{ path }}</li></ul>
      <NButton :type="recycle?.permanent ? 'error' : 'primary'" :loading="busy === '处理本地文件'" @click="submitRecycle">
        {{ recycle?.permanent ? '永久删除废片' : '移入回收站' }}
      </NButton>
    </NModal>

    <NModal v-model:show="preview" preset="card" title="审阅原片" class="preview-modal">
      <NSpin :show="imageLoading"><div class="compare">
        <figure v-for="item in images" :key="item.path">
          <img v-if="item.data" :src="item.data" :alt="item.path" @error="item.data = ''" />
          <NEmpty v-else description="无法读取照片预览" />
          <figcaption>{{ item.path }}</figcaption>
        </figure>
      </div></NSpin>
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
.paths, .entries { margin: 8px 0 16px; padding: 0; list-style: none; overflow-wrap: anywhere; }
.paths li { padding: 4px 0; }
.paths li .n-button { margin-left: 8px; }
.entry { display: flex; flex-wrap: wrap; align-items: start; gap: 8px; padding: 12px 0; border-bottom: 1px solid var(--n-border-color); }
.entry-info { flex: 1; min-width: min(300px, 100%); display: grid; gap: 4px; }
.entry-info > .n-button { justify-content: start; white-space: normal; text-align: left; }
.decisions { margin-left: auto; }
.plan { display: grid; gap: 4px; }
.batch-modal { width: min(760px, 90vw); }
.batch-modal .paths { max-height: 55vh; overflow: auto; }
.preview-modal { width: min(1320px, 94vw); }
.compare { display: flex; gap: 16px; }
.compare figure { margin: 0; flex: 1; min-width: 0; }
.compare img { display: block; width: 100%; height: min(60vh, 620px); object-fit: contain; }
.compare figcaption { overflow-wrap: anywhere; }
</style>
