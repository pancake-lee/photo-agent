<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
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
import { PlayOutline, CloudUploadOutline, SearchOutline } from '@vicons/ionicons5'

import SideMenu from '../components/SideMenu.vue'
import PhotoGrid from '../components/PhotoGrid.vue'
import PhotoDetail from '../components/PhotoDetail.vue'
import DescriptionModal from '../components/DescriptionModal.vue'
import UploadModal from '../components/UploadModal.vue'
import ConflictModal from '../components/ConflictModal.vue'

import { usePhotos } from '../composables/usePhotos'
import { useUpload } from '../composables/useUpload'
import { useVlmQueue } from '../composables/useVlmQueue'
import type { PhotoDetail as PhotoDetailType } from '../types/photo'
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
  fetchPhotos,
  fetchStats,
  fetchTimelines,
  fetchPhotoDetail,
  closeDetail,
  setPage,
  applyFilters,
  resetFilters,
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

// ── 初始化 ──
onMounted(() => {
  fetchPhotos()
  fetchStats()
  fetchTimelines()
})
</script>

<template>
  <NLayout has-sider position="absolute">
    <!-- 左侧边栏 -->
    <SideMenu />

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
          <!-- 统计摘要（全库汇总） -->
          <div class="stats-bar">
            <span>共 {{ stats?.total ?? total }} 张</span>
            <span class="stats-sep">|</span>
            <span>
              含描述
              {{ stats?.with_description ?? '...' }} 张
            </span>
            <span class="stats-sep">|</span>
            <span>
              待处理
              {{ stats?.without_description ?? '...' }} 张
            </span>
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

              <!-- 排序 -->
              <span class="filter-label">排序</span>
              <NSelect
                v-model:value="sortBy"
                :options="sortOptions"
                style="width: 110px"
              />
              <NButton size="small" @click="toggleSortOrder">
                {{ sortOrder === 'asc' ? '↑ 升序' : '↓ 降序' }}
              </NButton>

              <!-- 文件名搜索 -->
              <NInput
                v-model:value="searchFilename"
                placeholder="搜索文件名（如 9421）"
                clearable
                style="width: 180px"
                @keyup.enter="applyFilters"
              >
                <template #prefix>
                  <NIcon><SearchOutline /></NIcon>
                </template>
              </NInput>

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
            @view-detail="fetchPhotoDetail"
            @trigger-describe="handleTriggerDescribe"
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
  </NLayout>

  <!-- 照片详情抽屉 -->
  <PhotoDetail
    :show="showDetail"
    :photo="selectedPhoto"
    :loading="detailLoading"
    @close="closeDetail"
    @trigger-describe="handleTriggerDescribe"
    @view-description="handleViewDescription"
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
  font-size: 13px;
  color: var(--n-text-color-3);
  margin-bottom: 12px;
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
