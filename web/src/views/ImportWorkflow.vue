<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NLayoutContent,
  NLayoutHeader,
  NSteps,
  NStep,
  NCard,
  NSpin,
  NEmpty,
  NModal,
  useMessage,
} from 'naive-ui'
import { wailsApi, wailsError, isWails, onSyncProgress } from '../utils/wails'
import type {
  ConflictCheck,
  CreateStagingResult,
  DirFileList,
  ImportAnalysis,
  JpgRef,
  MigrateResult,
  StagingScan,
  StorageInfo,
  SyncProgress,
  SyncResult,
} from '../utils/wails'
import { settings } from '../stores/settings'
import ImportWorkflowStep1 from '../components/ImportWorkflowStep1.vue'
import ImportWorkflowStep2 from '../components/ImportWorkflowStep2.vue'
import ImportWorkflowStep3 from '../components/ImportWorkflowStep3.vue'
import type { CleanupAdviceRow, DirRow } from '../types/importWorkflow'

const message = useMessage()

// ── 当前步骤（1 新建活动 / 2 分析报告 / 3 上传同步） ──

const step = ref<1 | 2 | 3>(1)

// ── 步骤 1：新建活动 ──

function currentYearMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}

const yearMonth = ref(currentYearMonth())
const activityName = ref('')

// 记录中转目录路径，下次打开自动回填
const STAGING_PATH_KEY = 'import.stagingPath'
const stagingPath = ref(localStorage.getItem(STAGING_PATH_KEY) ?? '')
const stagingCreated = ref(false)
const createResult = ref<CreateStagingResult | null>(null)
const stagingScan = ref<StagingScan | null>(null)
const creating = ref(false)
const refreshing = ref(false)

watch(stagingPath, (v) => {
  localStorage.setItem(STAGING_PATH_KEY, v)
})

// ── 步骤 2：分析报告 ──

const analysis = ref<ImportAnalysis | null>(null)
const analyzing = ref(false)
const migrateResult = ref<MigrateResult | null>(null)
const migrating = ref(false)

// ── 步骤 3：上传同步 ──

const serverUrl = ref(settings.backendUrl)
const storageInfo = ref<StorageInfo | null>(null)
const fetchingInfo = ref(false)
const syncResult = ref<SyncResult | null>(null)
const syncing = ref(false)
const conflictCheck = ref<ConflictCheck | null>(null)
const checkingConflicts = ref(false)
const showSyncConfirm = ref(false)
const syncProgress = ref<SyncProgress | null>(null)

/** 上传进度百分比（0-100），用于进度条。 */
const progressPercent = computed(() => {
  const p = syncProgress.value
  if (!p || p.total <= 0) return 0
  return Math.min(100, Math.round((p.completed / p.total) * 100))
})

/** 是否存在重名文件，用于二次确认时展示「跳过/覆盖」还是「直接上传」。 */
const hasConflicts = computed(() => (conflictCheck.value?.existing.length ?? 0) > 0)

/** 本次归档的 like/ 是否全部同步成功（无失败且至少有一个文件已传/已跳过）。 */
const likeAllSynced = computed(() => {
  const r = syncResult.value
  if (!r) return false
  return r.failed === 0
})

/** 收尾建议行：上传完成后按目录给出可删/需确认的文本建议（程序不删任何文件）。 */
const cleanupAdviceRows = computed<CleanupAdviceRow[]>(() => {
  const r = syncResult.value
  if (!r) return []
  const folder = folderName.value
  return [
    {
      dir: `like/${folder}/`,
      ok: likeAllSynced.value,
      tip: likeAllSynced.value
        ? '已全部同步到服务器，可安全删除'
        : `有 ${r.failed} 个文件未上传成功，请先点击「开始同步」重试后再删除`,
    },
    {
      dir: `nef/${folder}/`,
      ok: likeAllSynced.value,
      tip: likeAllSynced.value
        ? '收藏的 NEF 已迁移到 like 并同步，可安全删除（留存/废弃的 NEF 未上传服务器，删除前请自行确认）'
        : 'like 目录尚有文件未同步完成，暂缓删除',
    },
    {
      dir: `full/${folder}/`,
      ok: false,
      tip: '留存照片（未收藏）不会上传服务器，确认设备中仍保留这些照片后再删除',
    },
  ]
})

// ── 派生状态 ──

/** 归档目录名：YYYYMM-活动名（有活动）或 YYYYMM（随手拍）。 */
const folderName = computed(() => {
  const ym = yearMonth.value.trim()
  const act = activityName.value.trim()
  return act ? `${ym}-${act}` : ym
})

const uploadJpgCount = computed(() => analysis.value?.like_jpg_count ?? 0)
const uploadNefCount = computed(() => analysis.value?.migrated_count ?? 0)

/** 是否可进入上传步骤：无需迁移（keep 为 0）或已完成迁移。 */
const canProceedToUpload = computed(() => {
  if (!analysis.value) return false
  if (analysis.value.favorite_count === 0) return true
  return !!migrateResult.value
})

const folderExistsOnServer = computed(() => {
  if (!storageInfo.value) return false
  const f = folderName.value
  return storageInfo.value.months.includes(f) || storageInfo.value.activities.includes(f)
})

/** 中转目录逐行状态：创建状态 + 文件数 + 最新文件时间。 */
const dirRows = computed<DirRow[]>(() => {
  const dirs = createResult.value?.dirs ?? []
  const scan = stagingScan.value
  const scanMap: Record<string, DirFileList | undefined> = {
    full: scan?.full,
    like: scan?.like,
    nef: scan?.nef,
  }
  return dirs.map((d) => {
    const stateText =
      d.status === 'created' ? '已创建' : d.status === 'existed' ? '已存在' : '创建失败'
    const list = scanMap[d.name]
    return {
      name: d.name,
      state: d.status,
      stateText,
      count: list?.count ?? 0,
      latest: latestDate(list),
    }
  })
})

// ── 格式化工具 ──

function formatDate(s?: string): string {
  if (!s) return '—'
  return s.slice(0, 10)
}

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function formatDateTime(sec: number): string {
  const d = new Date(sec * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function latestDate(list?: DirFileList): string {
  if (!list?.files?.length) return '—'
  let max = 0
  for (const f of list.files) {
    const d = f.shot_time || f.mod_time
    if (d > max) max = d
  }
  return max ? formatDateTime(max) : '—'
}

// ── 步骤 1 操作 ──

/** 弹出系统目录选择器，选择中转目录。 */
async function handleChooseDir() {
  try {
    const dir = await wailsApi.chooseDirectory()
    if (dir) stagingPath.value = dir
  } catch (e) {
    message.error(wailsError(e))
  }
}

/** 扫描中转目录，刷新文件数与最新时间。silent 时不弹错误提示。 */
async function loadScan(silent = false) {
  refreshing.value = true
  try {
    stagingScan.value = await wailsApi.scanStaging(stagingPath.value.trim(), folderName.value)
  } catch (e) {
    stagingScan.value = null
    if (!silent) message.error(wailsError(e))
  } finally {
    refreshing.value = false
  }
}

async function handleCreate() {
  if (!stagingPath.value.trim()) {
    message.warning('请填写中转目录路径')
    return
  }
  if (!/^\d{6}$/.test(yearMonth.value.trim())) {
    message.warning('日期格式应为 YYYYMM，如 202608')
    return
  }
  creating.value = true
  try {
    createResult.value = await wailsApi.createStagingDirs(stagingPath.value.trim(), folderName.value)
    stagingCreated.value = true
    await loadScan(true)
    message.success('中转目录已创建')
  } catch (e) {
    message.error(wailsError(e))
  } finally {
    creating.value = false
  }
}

// ── 步骤 2 操作 ──

async function enterStep2() {
  step.value = 2
  await handleAnalyze()
}

async function handleAnalyze() {
  analyzing.value = true
  migrateResult.value = null
  try {
    analysis.value = await wailsApi.analyzeStaging(stagingPath.value.trim(), folderName.value)
  } catch (e) {
    message.error(wailsError(e))
  } finally {
    analyzing.value = false
  }
}

async function handleMigrate() {
  if (!analysis.value) return
  const keepNames = analysis.value.favorite_list.map((d) => d.name)
  migrating.value = true
  try {
    migrateResult.value = await wailsApi.migrateKeptNef(
      stagingPath.value.trim(),
      folderName.value,
      keepNames
    )
    message.success(`已迁移 ${migrateResult.value.migrated_count} 个 NEF 到 like 目录`)
    // 迁移后重新分析，刷新 favorite/migrated 计数，避免报告仍显示待迁移
    analysis.value = await wailsApi.analyzeStaging(stagingPath.value.trim(), folderName.value)
  } catch (e) {
    message.error(wailsError(e))
  } finally {
    migrating.value = false
  }
}

// ── 步骤 3 操作 ──

async function handleFetchInfo() {
  if (!serverUrl.value.trim()) {
    message.warning('请填写服务器地址')
    return
  }
  fetchingInfo.value = true
  try {
    storageInfo.value = await wailsApi.getStorageInfo(serverUrl.value.trim())
  } catch (e) {
    message.error(wailsError(e))
  } finally {
    fetchingInfo.value = false
  }
}

async function handleSync() {
  if (!serverUrl.value.trim()) {
    message.warning('请填写服务器地址')
    return
  }
  const _staging = stagingPath.value.trim()
  const _folder = folderName.value
  const _server = serverUrl.value.trim()
  checkingConflicts.value = true
  try {
    wailsApi.log(`handleSync: 检查重名 staging=${_staging} folder=${_folder} server=${_server}`)
    conflictCheck.value = await wailsApi.checkConflicts(_staging, _folder, _server)
    showSyncConfirm.value = true
  } catch (e) {
    wailsApi.log(`handleSync: 检查重名失败 ${wailsError(e)}`)
    message.error(wailsError(e))
  } finally {
    checkingConflicts.value = false
  }
}

/** 二次确认后执行同步：skip 跳过重名文件，overwrite 覆盖服务端现有文件。 */
async function confirmSync(resolution: 'skip' | 'overwrite') {
  showSyncConfirm.value = false
  const _staging = stagingPath.value.trim()
  const _folder = folderName.value
  const _server = serverUrl.value.trim()
  syncing.value = true
  syncResult.value = null
  syncProgress.value = null
  try {
    wailsApi.log(`confirmSync: 开始同步 resolution=${resolution}`)
    syncResult.value = await wailsApi.syncToServer(_staging, _folder, _server, resolution)
    wailsApi.log(`confirmSync: 同步完成 total=${syncResult.value?.total}`)
    if (syncResult.value.failed > 0) {
      message.warning(`同步完成，${syncResult.value.failed} 个文件失败，可再次点击「开始同步」重试`)
    } else {
      message.success('同步完成')
    }
    // 同步后刷新服务器状态（总文件数/上次同步时间），失败不阻塞结果展示
    try {
      storageInfo.value = await wailsApi.getStorageInfo(_server)
    } catch {
      // 保留同步前状态即可，用户可手动点「连接并验证」重新获取
    }
  } catch (e) {
    wailsApi.log(`confirmSync: 同步失败 ${wailsError(e)}`)
    message.error(wailsError(e))
  } finally {
    syncing.value = false
  }
}

// ── 图片预览 ──

const previewVisible = ref(false)
const previewLoading = ref(false)
const preview = ref<{ name: string; src: string } | null>(null)

/** 打开预览弹窗，读取本地图片并以 base64 展示。 */
async function openPreview(item: JpgRef) {
  previewVisible.value = true
  previewLoading.value = true
  preview.value = null
  try {
    const b64 = await wailsApi.previewImage(item.path)
    preview.value = { name: item.name, src: `data:image/jpeg;base64,${b64}` }
  } catch (e) {
    message.error(wailsError(e))
    previewVisible.value = false
  } finally {
    previewLoading.value = false
  }
}

// ── 判断 ──

function hasWarnings(a: ImportAnalysis): boolean {
  return (
    a.outliers.length > 0 ||
    a.missing_nef.length > 0 ||
    a.no_date.length > 0
  )
}

// ── 上传进度事件订阅 ──

let offProgress: (() => void) | null = null
onMounted(() => {
  offProgress = onSyncProgress((p) => {
    syncProgress.value = p
  })
})
onUnmounted(() => {
  offProgress?.()
})
</script>

<template>
  <NLayoutContent>
    <NLayoutHeader bordered>
      <div class="page-header">
        <h2 class="page-title">导入工作流</h2>
      </div>
    </NLayoutHeader>

    <NLayoutContent class="page-body">
      <!-- 非 Wails 环境提示 -->
      <NCard v-if="!isWails()" title="无法使用导入工作流" size="small" class="guard-card">
        <p class="guard-note">
          导入工作流依赖客户端本地文件操作，请在 Wails 桌面应用中打开此页面。
          当前处于浏览器环境，无法扫描本地中转目录。
        </p>
      </NCard>

      <div v-else class="workflow-container">
        <NSteps :current="step" class="steps">
          <NStep title="新建活动" description="创建中转目录并引导导出" />
          <NStep title="分析报告" description="比对文件并确认保留" />
          <NStep title="上传同步" description="上传到服务器" />
        </NSteps>

        <ImportWorkflowStep1
          v-if="step === 1"
          v-model:year-month="yearMonth"
          v-model:activity-name="activityName"
          v-model:staging-path="stagingPath"
          :staging-created="stagingCreated"
          :folder-name="folderName"
          :dir-rows="dirRows"
          :creating="creating"
          :refreshing="refreshing"
          :on-choose-dir="handleChooseDir"
          :on-create="handleCreate"
          :on-refresh="() => loadScan(false)"
          :on-back="() => { stagingCreated = false }"
          :on-next="enterStep2"
        />

        <ImportWorkflowStep2
          v-else-if="step === 2"
          :analysis="analysis"
          :analyzing="analyzing"
          :migrating="migrating"
          :migrate-result="migrateResult"
          :can-proceed="canProceedToUpload"
          :format-date="formatDate"
          :has-warnings="hasWarnings"
          :on-preview="openPreview"
          :on-back="() => { step = 1 }"
          :on-analyze="handleAnalyze"
          :on-migrate="handleMigrate"
          :on-next="() => { step = 3 }"
        />

        <ImportWorkflowStep3
          v-else
          v-model:server-url="serverUrl"
          v-model:show-confirm="showSyncConfirm"
          :storage-info="storageInfo"
          :fetching-info="fetchingInfo"
          :syncing="syncing"
          :checking-conflicts="checkingConflicts"
          :sync-progress="syncProgress"
          :progress-percent="progressPercent"
          :sync-result="syncResult"
          :folder-name="folderName"
          :folder-exists="folderExistsOnServer"
          :upload-jpg-count="uploadJpgCount"
          :upload-nef-count="uploadNefCount"
          :cleanup-advice-rows="cleanupAdviceRows"
          :conflict-check="conflictCheck"
          :has-conflicts="hasConflicts"
          :format-date="formatDate"
          :format-elapsed="formatElapsed"
          :on-fetch-info="handleFetchInfo"
          :on-back="() => { step = 2 }"
          :on-sync="handleSync"
          :on-confirm="confirmSync"
        />
      </div>

      <NModal
        v-model:show="previewVisible"
        preset="card"
        :title="preview?.name ?? '图片预览'"
        style="width: min(80vw, 1000px)"
      >
        <div class="preview-body">
          <NSpin :show="previewLoading">
            <img v-if="preview" :src="preview.src" class="preview-img" alt="" />
            <NEmpty v-else-if="!previewLoading" description="无法加载图片" size="small" />
          </NSpin>
        </div>
      </NModal>
    </NLayoutContent>
  </NLayoutContent>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  padding: 16px 24px;
}
.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.page-body {
  padding: 24px;
}
.guard-card {
  max-width: 640px;
}
.guard-note {
  margin: 0;
  color: var(--n-text-color-3);
  font-size: 13px;
  line-height: 1.6;
}
.workflow-container {
  max-width: 860px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.steps {
  margin-bottom: 8px;
}
.step-card {
  width: 100%;
}
.stats {
  margin-bottom: 16px;
}
.storage-info {
  margin-top: 16px;
}
.warnings {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.warn-item {
  margin-top: 8px;
}
.lists {
  margin-top: 8px;
}
.file-list {
  max-height: 240px;
  overflow-y: auto;
}
.file-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 4px;
  border-bottom: 1px solid var(--n-border-color);
  font-size: 13px;
}
.file-row:last-child {
  border-bottom: none;
}
.file-name {
  color: var(--n-text-color);
}
.file-date {
  color: var(--n-text-color-3);
  font-size: 12px;
}
.file-row.clickable {
  cursor: pointer;
}
.file-row.clickable:hover {
  background: var(--n-color-embedded);
}
.collapse-hint {
  margin: 0 0 8px;
  color: var(--n-text-color-3);
  font-size: 12px;
}
.preview-body {
  display: flex;
  justify-content: center;
}
.preview-img {
  display: block;
  max-width: 100%;
  max-height: 70vh;
}
.step-actions {
  margin-top: 20px;
}
.guide-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.guide-intro {
  margin: 0;
  font-size: 14px;
}
.guide-list {
  margin: 0;
  padding-left: 20px;
  color: var(--n-text-color-2);
  font-size: 14px;
  line-height: 1.9;
}
.guide-list code {
  background: var(--n-color-embedded);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.dir-status {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
}
.dir-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--n-color-embedded);
  font-size: 13px;
}
.dir-name {
  font-weight: 600;
  color: var(--n-text-color);
}
.dir-state {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}
.state-created {
  color: var(--n-success-color);
  background: var(--n-success-color-suppl);
}
.state-existed {
  color: var(--n-info-color);
  background: var(--n-info-color-suppl);
}
.state-failed {
  color: var(--n-error-color);
  background: var(--n-error-color-suppl);
}
.dir-meta {
  color: var(--n-text-color-3);
  font-size: 12px;
}
.guide-alert {
  margin-top: 8px;
}
.migrate-result,
.sync-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.sync-progress {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
}
.sync-progress-text {
  margin: 0;
  color: var(--n-text-color-3);
  font-size: 13px;
}
.cleanup-title {
  margin-top: 4px;
}
.cleanup-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cleanup-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  background: var(--n-color-embedded);
  font-size: 13px;
}
.cleanup-row .dir-name {
  font-weight: 600;
  white-space: nowrap;
}
.cleanup-tip {
  color: var(--n-text-color-3);
}
.tip-ok {
  color: var(--n-success-color);
}
.tip-warn {
  color: var(--n-warning-color);
}
</style>
