<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import {
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NButton,
  NSpace,
  NTag,
  NPagination,
  NTooltip,
  NIcon,
  NDatePicker,
  NSelect,
  NInput,
  useMessage,
} from 'naive-ui'
import { PlayOutline, CloudUploadOutline, SearchOutline, LayersOutline, GridOutline, AlbumsOutline } from '@vicons/ionicons5'

import PhotoGrid from '../components/PhotoGrid.vue'
import PhotoDetail from '../components/PhotoDetail.vue'
import DescriptionModal from '../components/DescriptionModal.vue'
import UploadModal from '../components/UploadModal.vue'
import ConflictModal from '../components/ConflictModal.vue'
import BurstGroupModal from '../components/BurstGroupModal.vue'

import { usePhotos } from '../composables/usePhotos'
import { useUpload } from '../composables/useUpload'
import { useVlmQueue } from '../composables/useVlmQueue'
import { useEmbedQueue } from '../composables/useEmbedQueue'
import { useEmbedStatus } from '../composables/useEmbedStatus'
import { useBurstGroups } from '../composables/useBurstGroups'
import { settings } from '../stores/settings'
import type { PhotoDetail as PhotoDetailType, BurstViewLevel } from '../types/photo'
import type { ConflictResolution } from '../types/upload'

const message = useMessage()

// ── 照片列表 ──
const {
  photos,
  total,
  page,
  loading,
  error,
  totalPages,
  selectedPhoto,
  showDetail,
  detailLoading,
  stats,
  timelines,
  filterTimeline,
  filterShotAtStart,
  filterShotAtEnd,
  sortBy,
  sortOrder,
  searchFilename,
  burstModalGroup,
  burstModalMembers,
  burstModalCoverId,
  burstModalLoading,
  fetchPhotos,
  fetchStats,
  fetchTimelines,
  fetchPhotoDetail,
  closeDetail,
  setPage,
  applyFilters,
  resetFilters,
  deletePhoto,
  openBurstGroup,
  closeBurstGroup,
  setBurstCover,
} = usePhotos()

// ── 上传 ──
const {
  showUploadModal,
  files,
  uploading,
  currentConflict,
  addFiles,
  removeFile,
  startUpload,
  openUploadModal,
  closeUploadModal,
} = useUpload()

// ── VLM 队列 ──
const {
  status: vlmStatus,
  startQueue,
  stopQueue,
  enqueuePhoto,
  onComplete,
} = useVlmQueue()

// ── Embed 队列 ──
const {
  status: embedStatus,
  startQueue: startEmbedQueue,
  stopQueue: stopEmbedQueue,
  enqueuePhoto: enqueueEmbedPhoto,
  onComplete: onEmbedComplete,
} = useEmbedQueue()

// ── Embed 状态查询 ──
const {
  embeddedIds,
  embedStats,
  fetchEmbeddedIds,
  fetchEmbedStats,
} = useEmbedStatus()

// ── 连拍分组 ──
const {
  status: burstStatus,
  rebuild: rebuildBurst,
  fetchStatus: fetchBurstStatus,
  stopPolling: stopBurstPolling,
} = useBurstGroups()

// ── 处理中的照片 ID ──
const processingIds = ref<Set<string>>(new Set())

// ── 描述弹窗 ──
const showDescModal = ref(false)
const descPhoto = ref<PhotoDetailType | null>(null)

// ── 冲突弹窗 ──
const showConflictModal = ref(false)
const conflictResolver = ref<((r: ConflictResolution) => void) | null>(null)

// ── 计算属性 ──
const vlmCompleted = computed(() => vlmStatus.value.completed)
const vlmTotal = computed(() => vlmStatus.value.total)
const vlmRunning = computed(() => vlmStatus.value.running)
const embedRunning = computed(() => embedStatus.value.running)
const embedCompleted = computed(() => embedStatus.value.completed)
const embedTotal = computed(() => embedStatus.value.total)
const burstRunning = computed(() => burstStatus.value.running)
const burstProcessed = computed(() => burstStatus.value.processed)
const burstTotal = computed(() => burstStatus.value.total)

// 待 Embed 数量 = 有描述的 - 已嵌入的（避免负数）
const pendingEmbedCount = computed(() => {
  const withDesc = stats.value?.with_description ?? 0
  const withEmb = embedStats.value?.with_embedding ?? 0
  return Math.max(0, withDesc - withEmb)
})

// 排序选项
const sortOptions = [
  { label: '拍摄时间', value: 'shot_at' },
  { label: '文件名', value: 'filename' },
  { label: '导入时间', value: 'imported_at' },
]

// 时间线选项
const timelineOptions = computed(() =>
  timelines.value.map((t) => ({ label: t, value: t }))
)

// ── 方法 ──

async function handleStartVlm() {
  try {
    const result = await startQueue()
    if (result.total === 0) {
      message.info('所有照片已有描述，无需处理')
    } else {
      message.success(`VLM 预处理已启动，共 ${result.total} 张`)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

async function handleStopVlm() {
  await stopQueue()
  message.info('VLM 预处理已中止')
  // 刷新列表和统计
  fetchPhotos()
  fetchStats()
}

async function handleTriggerDescribe(photoId: string) {
  processingIds.value = new Set([...processingIds.value, photoId])
  try {
    await enqueuePhoto(photoId)
    message.success('已加入 VLM 处理队列')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '入队失败')
    processingIds.value.delete(photoId)
  }
}

async function handleStartEmbed() {
  try {
    const result = await startEmbedQueue()
    if (result.total === 0) {
      message.info('所有照片已有嵌入，无需处理')
    } else {
      message.success(`Embed 已启动，共 ${result.total} 张`)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

async function handleStopEmbed() {
  await stopEmbedQueue()
  message.info('Embed 已中止')
  fetchPhotos()
  fetchStats()
  fetchEmbedStats()
}

async function handleTriggerEmbed(photoId: string) {
  try {
    await enqueueEmbedPhoto(photoId)
    message.success('已加入 Embed 处理队列')
    // embed 完成后通过 onEmbedComplete → fetchEmbeddedIds 刷新图标状态
  } catch (e) {
    message.error(e instanceof Error ? e.message : '入队失败')
  }
}

function handleViewDescription() {
  if (selectedPhoto.value) {
    descPhoto.value = selectedPhoto.value
    showDescModal.value = true
  }
}

function handleRegenerateDescription() {
  if (descPhoto.value) {
    handleTriggerDescribe(descPhoto.value.id)
  }
  showDescModal.value = false
}

async function handleDeletePhoto(photoId: string) {
  try {
    await deletePhoto(photoId)
    message.success('图片已删除')
    fetchStats()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '删除失败')
  }
}

// ── 连拍分组重算 ──
async function handleRebuildBurst() {
  try {
    const st = await rebuildBurst(() => {
      message.success(
        `连拍分组完成，精细 ${burstStatus.value.group_count} 组 / 模糊 ${burstStatus.value.coarse_group_count} 组`,
      )
      fetchPhotos()
    })
    if (st === 'already_running') {
      message.info('连拍分组已在进行中')
    } else {
      message.success('连拍分组重算已启动')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

// ── 连拍展示级别循环切换 ──
const viewLevelOrder: BurstViewLevel[] = ['all', 'fine', 'coarse']
const viewLevelLabels: Record<BurstViewLevel, string> = {
  all: '全部展开',
  fine: '精细连拍',
  coarse: '模糊连拍',
}

function handleCycleViewLevel() {
  const idx = viewLevelOrder.indexOf(settings.burstViewLevel)
  settings.burstViewLevel = viewLevelOrder[(idx + 1) % viewLevelOrder.length]
  applyFilters()
}

// ── 连拍组弹窗 ──
function handleOpenBurstGroup(groupId: string, coverId: string) {
  openBurstGroup(groupId, coverId)
}

function handleBurstSetCover(photoId: string) {
  setBurstCover(burstModalGroup.value, photoId)
    .then(() => message.success('已设为封面'))
    .catch((e) => message.error(e instanceof Error ? e.message : '设为封面失败'))
}

async function handleUploadStart() {
  // 定义冲突处理回调
  showConflictModal.value = true

  await startUpload(async (_item) => {
    // 返回 Promise，等待用户选择
    return new Promise<ConflictResolution>((resolve) => {
      conflictResolver.value = resolve
      showConflictModal.value = true
    })
  })

  showConflictModal.value = false
  closeUploadModal()
  message.success('上传完成')
  fetchPhotos()
  fetchStats()
}

function handleConflictResolve(resolution: ConflictResolution) {
  if (conflictResolver.value) {
    conflictResolver.value(resolution)
    conflictResolver.value = null
  }
  showConflictModal.value = false
}

// 冲突弹窗关闭但未选择时，默认 skip，避免上传循环永久阻塞
watch(showConflictModal, (v) => {
  if (!v && conflictResolver.value) {
    conflictResolver.value('skip')
    conflictResolver.value = null
  }
})

// 日期变化处理（NaiveUI DatePicker v-model 返回时间戳或 null）
function handleDateStart(v: number | null) {
  if (v) {
    const d = new Date(v)
    filterShotAtStart.value = d.toISOString()
  } else {
    filterShotAtStart.value = ''
  }
}

function handleDateEnd(v: number | null) {
  if (v) {
    // 结束日期设为当天 23:59:59
    const d = new Date(v)
    d.setHours(23, 59, 59, 999)
    filterShotAtEnd.value = d.toISOString()
  } else {
    filterShotAtEnd.value = ''
  }
}

// 切换排序方向
function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  applyFilters()
}

// ── VLM 完成回调：自动刷新列表和统计 ──
onComplete(() => {
  fetchPhotos()
  fetchStats()
})

// ── Embed 完成回调 ──
onEmbedComplete(() => {
  fetchPhotos()
  fetchStats()
  fetchEmbedStats()
})

// ── 照片列表变化时自动同步 Embed 状态 ──
watch(photos, (newPhotos) => {
  const ids = newPhotos.map((p) => p.id)
  fetchEmbeddedIds(ids)
})

// ── 初始化 ──
onMounted(async () => {
  await fetchPhotos()
  fetchStats()
  fetchTimelines()
  fetchEmbedStats()
  fetchBurstStatus()
})

onUnmounted(() => {
  stopBurstPolling()
})
</script>

<template>
  <NLayout>
    <!-- 顶部工具栏 -->
    <NLayoutHeader bordered>
        <div class="toolbar">
          <h3 class="toolbar-title">图片管理</h3>

          <NSpace>
            <!-- VLM 全局控制 -->
            <template v-if="vlmRunning">
              <NTooltip trigger="hover">
                <template #trigger>
                  <NTag
                    type="info"
                    size="large"
                    class="progress-tag"
                    :style="{ cursor: 'pointer' }"
                    @click="handleStopVlm"
                  >
                    {{ vlmCompleted }}/{{ vlmTotal }}
                  </NTag>
                </template>
                点击中止处理
              </NTooltip>
            </template>

            <NButton
              v-if="!vlmRunning"
              type="primary"
              @click="handleStartVlm"
            >
              <template #icon>
                <NIcon><PlayOutline /></NIcon>
              </template>
              开始自动VLM预处理
            </NButton>

            <!-- Embed 全局控制 -->
            <template v-if="embedRunning">
              <NTooltip trigger="hover">
                <template #trigger>
                  <NTag
                    type="warning"
                    size="large"
                    class="progress-tag"
                    :style="{ cursor: 'pointer' }"
                    @click="handleStopEmbed"
                  >
                    Embed {{ embedCompleted }}/{{ embedTotal }}
                  </NTag>
                </template>
                点击中止处理
              </NTooltip>
            </template>

            <NButton
              v-if="!embedRunning"
              type="warning"
              @click="handleStartEmbed"
            >
              <template #icon>
                <NIcon><LayersOutline /></NIcon>
              </template>
              开始批量Embed
            </NButton>

            <!-- 连拍分组重算 -->
            <template v-if="burstRunning">
              <NTooltip trigger="hover">
                <template #trigger>
                  <NTag
                    type="info"
                    size="large"
                    class="progress-tag"
                    :style="{ cursor: 'pointer' }"
                  >
                    连拍 {{ burstProcessed }}/{{ burstTotal }}
                  </NTag>
                </template>
                正在重算连拍分组
              </NTooltip>
            </template>
            <NButton v-else @click="handleRebuildBurst">
              <template #icon>
                <NIcon><GridOutline /></NIcon>
              </template>
              连拍分组
            </NButton>

            <!-- 上传按钮 -->
            <NButton @click="openUploadModal">
              <template #icon>
                <NIcon><CloudUploadOutline /></NIcon>
              </template>
              上传图片
            </NButton>
          </NSpace>
        </div>
      </NLayoutHeader>

      <!-- 主内容区 -->
      <NLayoutContent>
        <div class="content-wrapper">
          <!-- 统计摘要 + 排序搜索 -->
          <div class="stats-bar">
            <div class="stats-summary">
              <span>共 {{ stats?.total ?? total }} 张</span>
              <span class="stats-sep">|</span>
              <span>
                数据完整
                {{ embedStats?.with_embedding ?? '...' }} 张
              </span>
              <span class="stats-sep">|</span>
              <span>
                VLM待处理
                {{ stats?.without_description ?? '...' }} 张
              </span>
              <span class="stats-sep">|</span>
              <span>
                Embed待处理
                {{ pendingEmbedCount }} 张
              </span>
            </div>

            <div class="stats-actions">
              <NSpace align="center">
                <!-- 连拍展示级别循环切换 -->
                <NTooltip trigger="hover">
                  <template #trigger>
                    <NButton
                      size="small"
                      @click="handleCycleViewLevel"
                    >
                      <template #icon>
                        <NIcon><AlbumsOutline /></NIcon>
                      </template>
                      展示：{{ viewLevelLabels[settings.burstViewLevel] }}
                    </NButton>
                  </template>
                  点击切换连拍展示级别（全部展开 / 精细折叠 / 模糊折叠）
                </NTooltip>

                <!-- 排序 -->
                <span class="filter-label">排序</span>
                <NSelect
                  v-model:value="sortBy"
                  :options="sortOptions"
                  size="small"
                  style="width: 100px"
                />
                <NButton size="small" @click="toggleSortOrder">
                  {{ sortOrder === 'asc' ? '↑ 升序' : '↓ 降序' }}
                </NButton>

                <!-- 文件名搜索 -->
                <NInput
                  v-model:value="searchFilename"
                  placeholder="搜索文件名"
                  size="small"
                  clearable
                  style="width: 180px"
                  @keyup.enter="applyFilters"
                >
                  <template #prefix>
                    <NIcon><SearchOutline /></NIcon>
                  </template>
                </NInput>
              </NSpace>
            </div>
          </div>

          <!-- 筛选栏 -->
          <div class="filter-bar">
            <NSpace align="center" :wrap="true">
              <!-- 拍摄日期范围 -->
              <span class="filter-label">拍摄日期</span>
              <NDatePicker
                type="date"
                clearable
                placeholder="起始日期"
                style="width: 140px"
                @update:value="handleDateStart"
              />
              <span>至</span>
              <NDatePicker
                type="date"
                clearable
                placeholder="结束日期"
                style="width: 140px"
                @update:value="handleDateEnd"
              />

              <!-- 活动筛选 -->
              <span class="filter-label">活动</span>
              <NSelect
                v-model:value="filterTimeline"
                :options="timelineOptions"
                placeholder="全部活动"
                clearable
                style="width: 160px"
              />

              <!-- 操作按钮 -->
              <NButton type="primary" size="small" @click="applyFilters">
                筛选
              </NButton>
              <NButton size="small" @click="resetFilters">
                重置
              </NButton>
            </NSpace>
          </div>

          <!-- 照片网格 -->
          <PhotoGrid
            :photos="photos"
            :loading="loading"
            :error="error"
            :processing-ids="processingIds"
            :embedded-ids="embeddedIds"
            :view-level="settings.burstViewLevel"
            @view-detail="fetchPhotoDetail"
            @trigger-describe="handleTriggerDescribe"
            @trigger-embed="handleTriggerEmbed"
            @delete-photo="handleDeletePhoto"
            @open-burst-group="handleOpenBurstGroup"
            @retry="fetchPhotos"
          />

          <!-- 分页 -->
          <div v-if="totalPages > 1" class="pagination-wrapper">
            <NPagination
              :page="page"
              :page-count="totalPages"
              @update:page="setPage"
            />
          </div>
        </div>
      </NLayoutContent>
  </NLayout>

  <!-- 照片详情抽屉 -->
  <PhotoDetail
    :show="showDetail"
    :photo="selectedPhoto"
    :loading="detailLoading"
    @close="closeDetail"
    @trigger-describe="handleTriggerDescribe"
    @trigger-embed="handleTriggerEmbed"
    @view-description="handleViewDescription"
  />

  <!-- 连拍组弹窗 -->
  <BurstGroupModal
    :show="burstModalGroup !== ''"
    :group-id="burstModalGroup"
    :members="burstModalMembers"
    :cover-id="burstModalCoverId"
    :loading="burstModalLoading"
    @close="closeBurstGroup"
    @view-detail="fetchPhotoDetail"
    @set-cover="handleBurstSetCover"
  />

  <!-- 描述内容弹窗 -->
  <DescriptionModal
    :show="showDescModal"
    :filename="descPhoto?.filename || ''"
    :description="descPhoto?.description || ''"
    :model="descPhoto?.description_model || ''"
    :processed-at="descPhoto?.description_time || ''"
    @close="showDescModal = false"
    @regenerate="handleRegenerateDescription"
  />

  <!-- 上传弹窗 -->
  <UploadModal
    :show="showUploadModal"
    :files="files"
    :uploading="uploading"
    @close="closeUploadModal"
    @add-files="addFiles"
    @remove-file="removeFile"
    @start-upload="handleUploadStart"
  />

  <!-- 冲突弹窗 -->
  <ConflictModal
    :show="showConflictModal"
    :conflict="currentConflict?.conflict || null"
    :new-filename="currentConflict?.file.originalName || ''"
    :new-shot-at="currentConflict?.file.shotAt || ''"
    @close="showConflictModal = false"
    @resolve="handleConflictResolve"
  />
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.toolbar-title {
  margin: 0;
  font-size: 16px;
}
.progress-tag {
  font-size: 14px;
  padding: 4px 16px;
}
.content-wrapper {
  padding: 20px 24px;
}
.stats-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--n-text-color-3);
  margin-bottom: 12px;
}
.stats-summary {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.stats-sep {
  margin: 0 8px;
  color: var(--n-divider-color);
}
.filter-bar {
  margin-bottom: 16px;
  padding: 10px 14px;
  background: var(--n-color-embedded);
  border-radius: 8px;
  border: 1px solid var(--n-border-color);
}
.filter-label {
  font-size: 13px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}
</style>
