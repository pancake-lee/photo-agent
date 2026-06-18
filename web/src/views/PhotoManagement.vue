<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
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
  useMessage,
} from 'naive-ui'
import { PlayOutline, CloudUploadOutline } from '@vicons/ionicons5'

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
  fetchPhotos,
  fetchPhotoDetail,
  closeDetail,
  setPage,
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
  // 刷新列表（扫尾结果可能已写入）
  fetchPhotos()
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
}

function handleConflictResolve(resolution: ConflictResolution) {
  if (conflictResolver.value) {
    conflictResolver.value(resolution)
    conflictResolver.value = null
  }
  showConflictModal.value = false
}

// ── 初始化 ──
onMounted(() => {
  fetchPhotos()
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
          <!-- 统计摘要 -->
          <div class="stats-bar">
            <span>共 {{ total }} 张</span>
            <span class="stats-sep">|</span>
            <span>
              含描述
              {{ photos.filter((p) => p.has_description).length }} 张
            </span>
            <span class="stats-sep">|</span>
            <span>
              待处理
              {{ photos.filter((p) => !p.has_description).length }} 张
            </span>
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
  margin-bottom: 16px;
}
.stats-sep {
  margin: 0 8px;
  color: var(--n-divider-color);
}
.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}
</style>
