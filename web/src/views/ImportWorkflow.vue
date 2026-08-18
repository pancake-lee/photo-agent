<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NLayoutContent,
  NLayoutHeader,
  NSteps,
  NStep,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NButton,
  NSpace,
  NAlert,
  NDescriptions,
  NDescriptionsItem,
  NCollapse,
  NCollapseItem,
  NSpin,
  NEmpty,
  NModal,
  NProgress,
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
interface DirRow {
  name: string
  state: 'created' | 'existed' | 'failed'
  stateText: string
  count: number
  latest: string
}

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
    message.success('同步完成')
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

        <!-- ═══ 步骤 1：新建活动 ═══ -->
        <NCard v-if="step === 1" title="新建拍摄活动" size="small" class="step-card">
          <template v-if="!stagingCreated">
            <NForm label-placement="top" :show-feedback="false">
              <NFormItem label="日期（YYYYMM）">
                <NInput
                  v-model:value="yearMonth"
                  placeholder="202608"
                  style="max-width: 240px"
                />
              </NFormItem>
              <NFormItem label="活动名称（可选，留空表示随手拍）">
                <NInput
                  v-model:value="activityName"
                  placeholder="如：山西旅游"
                  style="max-width: 360px"
                />
              </NFormItem>
              <NFormItem label="中转目录路径（full/like/nef 所在位置）">
                <NSpace align="center">
                  <NInput
                    v-model:value="stagingPath"
                    placeholder="如：D:\\照片中转\\"
                    style="width: 420px"
                  />
                  <NButton @click="handleChooseDir">选择文件夹</NButton>
                </NSpace>
              </NFormItem>
              <NFormItem>
                <NButton type="primary" :loading="creating" @click="handleCreate">
                  确认，创建中转目录
                </NButton>
              </NFormItem>
            </NForm>
          </template>

          <template v-else>
            <div class="guide-block">
              <p class="guide-intro">中转目录已就绪，请把文件放入对应文件夹（可用任意应用、任意方式）：</p>
              <ul class="guide-list">
                <li>全部照片（JPG）放入 <code>full/</code> 文件夹</li>
                <li>个人收藏的照片（JPG）放入 <code>like/</code> 文件夹</li>
                <li>本次拍摄对应的 NEF 原始文件放入 <code>nef/</code> 文件夹</li>
              </ul>

              <div class="dir-status">
                <div v-for="d in dirRows" :key="d.name" class="dir-row">
                  <span class="dir-name">{{ d.name }}/{{ folderName }}/</span>
                  <span class="dir-state" :class="`state-${d.state}`">{{ d.stateText }}</span>
                  <span class="dir-meta">{{ d.count }} 个文件</span>
                  <span class="dir-meta">日期：{{ d.latest }}</span>
                </div>
              </div>

              <NAlert type="info" :bordered="false" class="guide-alert">
                归档目录将命名为 <b>{{ folderName }}</b>。
              </NAlert>
            </div>

            <NSpace justify="end" class="step-actions">
              <NButton :loading="refreshing" @click="loadScan(false)">刷新状态</NButton>
              <NButton @click="stagingCreated = false">上一步</NButton>
              <NButton type="primary" @click="enterStep2">我已准备好，进入下一步</NButton>
            </NSpace>
          </template>
        </NCard>

        <!-- ═══ 步骤 2：分析报告 ═══ -->
        <NCard v-else-if="step === 2" title="分析报告" size="small" class="step-card">
          <NSpin :show="analyzing">
            <template v-if="analysis">
              <NDescriptions bordered :column="3" size="small" class="stats">
                <NDescriptionsItem label="full 中 JPG 总数">
                  {{ analysis.full_jpg_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="收藏 JPG 总数（like）">
                  {{ analysis.like_jpg_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="nef 中 NEF 总数">
                  {{ analysis.nef_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="收藏照片的 NEF（将迁移）">
                  {{ analysis.favorite_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="已迁移 NEF（已在 like）">
                  {{ analysis.migrated_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="跳过留存照片的 NEF">
                  {{ analysis.retained_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="跳过废弃照片的 NEF">
                  {{ analysis.discarded_count }}
                </NDescriptionsItem>
                <NDescriptionsItem label="时间范围">
                  {{ formatDate(analysis.time_range.min) }} 至 {{ formatDate(analysis.time_range.max) }}
                </NDescriptionsItem>
              </NDescriptions>

              <div v-if="hasWarnings(analysis)" class="warnings">
                <NAlert
                  v-if="analysis.outliers.length"
                  type="warning"
                  :bordered="false"
                  class="warn-item"
                >
                  发现 {{ analysis.outliers.length }} 个文件日期偏离主要范围，请确认是否混入其他活动：
                  {{ analysis.outliers.map((o) => `${o.name}（${formatDate(o.shot_at)}）`).join('、') }}
                </NAlert>
                <NCollapse v-if="analysis.missing_nef.length" class="lists">
                  <NCollapseItem
                    :title="`${analysis.missing_nef.length} 个 JPG 缺少对应 NEF（点击展开查看）`"
                    name="missing"
                  >
                    <p class="collapse-hint">
                      以下 JPG 在 full/like 中没有对应 NEF，请检查 NEF 是否完整复制。点击文件名预览图片。
                    </p>
                    <div class="file-list">
                      <div
                        v-for="f in analysis.missing_nef"
                        :key="f.path"
                        class="file-row clickable"
                        @click="openPreview(f)"
                      >
                        <span class="file-name">{{ f.name }}</span>
                        <span class="file-date">{{ f.dir }}/</span>
                      </div>
                    </div>
                  </NCollapseItem>
                </NCollapse>

                <NCollapse v-if="analysis.no_date.length" class="lists">
                  <NCollapseItem
                    :title="`${analysis.no_date.length} 个文件无法读取拍摄时间（点击展开查看）`"
                    name="nodate"
                  >
                    <p class="collapse-hint">以下文件无法读取拍摄时间，点击文件名预览图片。</p>
                    <div class="file-list">
                      <div
                        v-for="f in analysis.no_date"
                        :key="f.path"
                        class="file-row clickable"
                        @click="openPreview(f)"
                      >
                        <span class="file-name">{{ f.name }}</span>
                        <span class="file-date">{{ f.dir }}/</span>
                      </div>
                    </div>
                  </NCollapseItem>
                </NCollapse>
              </div>

              <div v-if="migrateResult" class="migrate-result">
                <NAlert type="success" :bordered="false">
                  已迁移 {{ migrateResult.migrated_count }} 个 NEF 到 like 目录
                  <template v-if="migrateResult.failed.length">
                    ，{{ migrateResult.failed.length }} 个失败。
                  </template>
                </NAlert>
                <NAlert type="info" :bordered="false" class="warn-item">
                  仅复制、未删除任何文件。nef/ 目录中的文件请自行确认后清理。
                </NAlert>
              </div>
            </template>

            <NEmpty v-else-if="!analyzing" description="尚未分析，请点击下方按钮" size="small" />
          </NSpin>

          <NSpace justify="end" class="step-actions">
            <NButton @click="step = 1">上一步</NButton>
            <NButton :loading="analyzing" @click="handleAnalyze">重新分析</NButton>
            <NButton
              type="primary"
              :loading="migrating"
              :disabled="!analysis || analysis.favorite_count === 0"
              @click="handleMigrate"
            >
              确认执行，迁移收藏 NEF
            </NButton>
            <NButton type="primary" :disabled="!canProceedToUpload" @click="step = 3">
              进入下一步（上传）
            </NButton>
          </NSpace>
        </NCard>

        <!-- ═══ 步骤 3：上传同步 ═══ -->
        <NCard v-else title="上传同步" size="small" class="step-card">
          <NForm label-placement="top" :show-feedback="false">
            <NFormItem label="服务器地址">
              <NSpace align="center">
                <NInput
                  v-model:value="serverUrl"
                  placeholder="http://192.168.1.100:10004"
                  style="width: 360px"
                />
                <NButton :loading="fetchingInfo" @click="handleFetchInfo">连接并验证</NButton>
              </NSpace>
            </NFormItem>
          </NForm>

          <template v-if="storageInfo">
            <NDescriptions bordered :column="2" size="small" class="stats storage-info">
              <NDescriptionsItem label="存储根路径">{{ storageInfo.root }}</NDescriptionsItem>
              <NDescriptionsItem label="总文件数">
                {{ storageInfo.jpg_count }} 张 JPG，{{ storageInfo.nef_count }} 张 NEF
              </NDescriptionsItem>
              <NDescriptionsItem label="已有月份文件夹">
                {{ storageInfo.months.join('、') || '—' }}
              </NDescriptionsItem>
              <NDescriptionsItem label="已有活动文件夹">
                {{ storageInfo.activities.join('、') || '—' }}
              </NDescriptionsItem>
              <NDescriptionsItem label="上次同步时间">
                {{ storageInfo.last_sync ? formatDate(storageInfo.last_sync) : '—' }}
              </NDescriptionsItem>
            </NDescriptions>

            <NAlert
              v-if="storageInfo.warning"
              type="warning"
              :bordered="false"
              class="warn-item"
            >
              {{ storageInfo.warning }}
            </NAlert>

            <NAlert
              :type="folderExistsOnServer ? 'warning' : 'info'"
              :bordered="false"
              class="warn-item"
            >
              <template v-if="folderExistsOnServer">
                目录 <b>{{ folderName }}</b> 已存在，本次将追加到该目录。
              </template>
              <template v-else>
                本次将新增目录 <b>{{ folderName }}</b>（{{ uploadJpgCount }} 张 JPG，{{ uploadNefCount }} 张 NEF）。
              </template>
            </NAlert>
          </template>

          <div v-if="syncing" class="sync-progress">
            <NProgress
              type="line"
              :percentage="progressPercent"
              :height="8"
              :border-radius="4"
            />
            <p class="sync-progress-text">
              已完成 {{ syncProgress?.completed ?? 0 }} / {{ syncProgress?.total ?? '—' }} 个文件
            </p>
          </div>

          <div v-if="syncResult" class="sync-result">
            <NDescriptions bordered :column="4" size="small" class="stats">
              <NDescriptionsItem label="上传成功">{{ syncResult.succeeded }}</NDescriptionsItem>
              <NDescriptionsItem v-if="syncResult.skipped > 0" label="跳过">{{ syncResult.skipped }}</NDescriptionsItem>
              <NDescriptionsItem label="失败">{{ syncResult.failed }}</NDescriptionsItem>
              <NDescriptionsItem label="耗时">{{ formatElapsed(syncResult.elapsed_ms) }}</NDescriptionsItem>
            </NDescriptions>

            <NCollapse v-if="syncResult.failed > 0" class="lists">
              <NCollapseItem title="失败详情" name="failed">
                <div class="file-list">
                  <div v-for="f in syncResult.files.filter((x) => x.status !== 'stored' && x.status !== 'skipped')" :key="f.name" class="file-row">
                    <span class="file-name">{{ f.name }}</span>
                    <span class="file-date">{{ f.error }}</span>
                  </div>
                </div>
              </NCollapseItem>
            </NCollapse>
          </div>

          <NSpace justify="end" class="step-actions">
            <NButton @click="step = 2">上一步</NButton>
            <NButton
              type="primary"
              :loading="syncing || checkingConflicts"
              :disabled="!storageInfo"
              @click="handleSync"
            >
              开始同步
            </NButton>
          </NSpace>
        </NCard>
      </div>

      <!-- 同步二次确认：展示重名汇总，选择跳过或覆盖 -->
      <NModal
        v-model:show="showSyncConfirm"
        preset="card"
        title="同步确认"
        style="width: min(90vw, 520px)"
      >
        <template v-if="conflictCheck">
          <NDescriptions bordered :column="1" size="small" class="stats conflict-summary">
            <NDescriptionsItem label="待同步文件总数">{{ conflictCheck.total }}</NDescriptionsItem>
            <NDescriptionsItem label="服务端已存在（重名）">
              {{ conflictCheck.existing.length }}
            </NDescriptionsItem>
            <NDescriptionsItem label="新文件">{{ conflictCheck.new.length }}</NDescriptionsItem>
          </NDescriptions>

          <NAlert
            v-if="hasConflicts"
            type="warning"
            :bordered="false"
            class="warn-item"
          >
            有 {{ conflictCheck.existing.length }} 个文件与服务端重名，请选择处理方式。
          </NAlert>
          <NAlert v-else type="info" :bordered="false" class="warn-item">
            没有重名文件，将全部上传。
          </NAlert>
        </template>

        <template #footer>
          <NSpace justify="end">
            <NButton @click="showSyncConfirm = false">取消</NButton>
            <NButton v-if="hasConflicts" @click="confirmSync('skip')">跳过已存在文件</NButton>
            <NButton v-if="hasConflicts" type="warning" @click="confirmSync('overwrite')">
              覆盖服务器现有文件
            </NButton>
            <NButton v-if="!hasConflicts" type="primary" @click="confirmSync('skip')">
              开始上传
            </NButton>
          </NSpace>
        </template>
      </NModal>

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
</style>
