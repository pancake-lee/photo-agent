<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NLayout, NLayoutContent, NLayoutHeader, NModal, NButton, NEmpty, NSpin, NAlert, NSpace, useMessage } from 'naive-ui'
import PhotoDetail from '../components/PhotoDetail.vue'
import DescriptionModal from '../components/DescriptionModal.vue'
import UploadModal from '../components/UploadModal.vue'
import ConflictModal from '../components/ConflictModal.vue'
import BurstGroupModal from '../components/BurstGroupModal.vue'
import PhotoListBrowser from '../components/PhotoListBrowser.vue'
import PhotoManagementToolbar from '../components/PhotoManagementToolbar.vue'
import { usePhotos } from '../composables/usePhotos'
import { useUpload } from '../composables/useUpload'
import { useVlmQueue } from '../composables/useVlmQueue'
import { useEmbedQueue } from '../composables/useEmbedQueue'
import { useEmbedStatus } from '../composables/useEmbedStatus'
import { useBurstGroups } from '../composables/useBurstGroups'
import { settings } from '../stores/settings'
import type { PhotoDetail as PhotoDetailType } from '../types/photo'
import type { SegmentMode } from '../utils/segment'
import type { ConflictResolution } from '../types/upload'
import { getAgentBase, getApiBase } from '../config'

const message = useMessage()
const router = useRouter()
const {
  photos, total, loading, loadingDown, loadingUp, noMoreDown, noMoreUp, error,
  selectedPhoto, showDetail, detailLoading, stats, timelines, segments,
  filterTimeline, filterShotAtStart, filterShotAtEnd, sortOrder, searchFilename,
  burstModalGroup, burstModalMembers, burstModalCoverId, burstModalLoading,
  relocateTo, relocateToStart, loadDown, loadUp, fetchSegments, fetchStats,
  fetchTimelines, fetchPhotoDetail, closeDetail, applyFilters, resetFilters,
  deletePhoto, openBurstGroup, closeBurstGroup, setBurstCover, auxiliaryError,
  refreshPhoto,
} = usePhotos()
const { showUploadModal, files, uploading, currentConflict, addFiles, removeFile, startUpload, openUploadModal, closeUploadModal } = useUpload()
const { status: vlmStatus, startQueue, stopQueue, enqueuePhoto, onComplete, describeProcessingIds, fetchDescribeProgress, stopDescribePolling, fetchStatus: fetchVlmQueueStatus, startPolling: startVlmPolling } = useVlmQueue()
const { status: embedStatus, startQueue: startEmbedQueue, stopQueue: stopEmbedQueue, enqueuePhoto: enqueueEmbedPhoto, syncGroupCollections, onComplete: onEmbedComplete, embedProcessingIds, fetchEmbedProgress, stopEmbedProgressPolling, fetchStatus: fetchEmbedQueueStatus, startPolling: startEmbedPolling } = useEmbedQueue()
const { embeddedIds, embedStats, fetchEmbeddedIds, fetchEmbedStats } = useEmbedStatus()
const { status: burstStatus, rebuild: rebuildBurst, fetchStatus: fetchBurstStatus, stopPolling: stopBurstPolling } = useBurstGroups()
const showDescModal = ref(false)
const descPhoto = ref<PhotoDetailType | null>(null)
const showConflictModal = ref(false)
const conflictResolver = ref<((resolution: ConflictResolution) => void) | null>(null)
const detailDescribeProcessing = computed(() => !!selectedPhoto.value && describeProcessingIds.value.has(selectedPhoto.value.id))
const detailEmbedProcessing = computed(() => !!selectedPhoto.value && embedProcessingIds.value.has(selectedPhoto.value.id))
const detailValidateProcessing = ref(false)
// 详情抽屉上/下一张导航：以当前加载的照片窗口为列表
const photoNavList = computed(() => photos.value.map((p) => ({ id: p.id, label: p.filename })))

// ── 选择模式（路径 B：自选图片进入图文工坊）──
const selectionMode = ref(false)
type AuditItem = { id: string; filename: string; thumbnail_url: string; reason: string }
type AuditResult = { counts: Record<string, number>; items: Record<string, AuditItem[]>; message: string }
const batchKind = ref<'vlm' | 'embed'>('vlm')
const showBatchConfirm = ref(false)
const batchAuditLoading = ref(false)
const batchAudit = ref<AuditResult | null>(null)

async function openBatchConfirm(kind: 'vlm' | 'embed') {
  batchKind.value = kind
  showBatchConfirm.value = true
  batchAuditLoading.value = true
  batchAudit.value = null
  try {
    const response = await fetch(`${getAgentBase()}/embed/audit`)
    if (!response.ok) throw new Error('审计预览加载失败')
    batchAudit.value = await response.json()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '审计预览加载失败')
    showBatchConfirm.value = false
  } finally {
    batchAuditLoading.value = false
  }
}
async function refreshBatchAudit() { await openBatchConfirm(batchKind.value) }

const batchCandidates = computed(() => {
  if (!batchAudit.value) return []
  const keys = batchKind.value === 'vlm' ? ['vlm_missing', 'vlm_review'] : ['embedding_missing']
  return keys.flatMap((key) => batchAudit.value?.items[key] || [])
})
const batchCount = computed(() => batchCandidates.value.length)
const batchPreview = computed(() => batchCandidates.value.slice(0, 8))
const batchRemaining = computed(() => Math.max(0, batchCount.value - batchPreview.value.length))
async function confirmBatchRepair() {
  showBatchConfirm.value = false
  try {
    const result = batchKind.value === 'vlm' ? await startQueue(true) : await startEmbedQueue()
    const total = result.total ?? 0
    message[total ? 'success' : 'info'](total ? `已开始处理 ${total} 张照片` : '当前没有需要处理的照片')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}
const selectedIds = ref<Set<string>>(new Set())
const selectedCount = computed(() => selectedIds.value.size)
// 恰好选中 2 张时显示「区间选择」按钮
const showIntervalSelect = computed(() => selectedIds.value.size === 2)
// 当前窗口内按展示顺序（拍摄时间排序）可见的照片 id，与 PhotoGrid 的连拍折叠逻辑一致
const visiblePhotoIds = computed(() => {
  const list = settings.burstViewLevel === 'all'
    ? photos.value
    : photos.value.filter((p) => p.burst_group_id === '' || p.burst_cover)
  return list.map((p) => p.id)
})

function toggleSelectionMode() {
  if (selectionMode.value) {
    selectionMode.value = false
    selectedIds.value = new Set()
  } else {
    selectionMode.value = true
  }
}

function toggleSelect(photoId: string) {
  const next = new Set(selectedIds.value)
  if (next.has(photoId)) next.delete(photoId)
  else next.add(photoId)
  selectedIds.value = next
}

function selectIds(ids: string[]) {
  if (!ids.length) return
  const next = new Set(selectedIds.value)
  ids.forEach((id) => next.add(id))
  selectedIds.value = next
}

function selectAllVisible() {
  selectIds(visiblePhotoIds.value)
}

function clearSelection() {
  selectedIds.value = new Set()
}

// 区间选择：勾选两张已选照片之间（按拍摄时间排序）的所有照片
function intervalSelect() {
  const ids = visiblePhotoIds.value
  const positions = [...selectedIds.value]
    .map((id) => ids.indexOf(id))
    .filter((i) => i >= 0)
    .sort((a, b) => a - b)
  if (positions.length < 2) return
  selectIds(ids.slice(positions[0], positions[positions.length - 1] + 1))
}

function goToPostStudio() {
  if (selectedIds.value.size === 0) return
  // 按当前窗口顺序（拍摄时间排序）携带全部已选照片，窗口外残留的排到末尾
  const order = new Map<string, number>()
  photos.value.forEach((p, i) => order.set(p.id, i))
  const photoById = new Map(photos.value.map((p) => [p.id, p]))
  const ids = [...selectedIds.value].sort(
    (a, b) => (order.get(a) ?? Number.MAX_SAFE_INTEGER) - (order.get(b) ?? Number.MAX_SAFE_INTEGER),
  )
  // 折叠视图下，勾选连拍组封面视为「选中整组」，用 g: 前缀标记，图文工坊据此展开
  const isCollapsed = settings.burstViewLevel !== 'all'
  const tokens = ids.map((id) => {
    const p = photoById.get(id)
    if (p && isCollapsed && p.burst_cover && p.burst_group_id && p.burst_count > 1) {
      return `g:${p.burst_group_id}:${id}`
    }
    return id
  })
  router.push({ path: '/post-studio', query: { photo_ids: tokens.join(',') } })
}

async function handleStartVlm() { await openBatchConfirm('vlm') }
async function handleStopVlm() { await stopQueue(); message.info('VLM 预处理已中止'); relocateToStart(); fetchStats() }
async function handleTriggerDescribe(photoId: string) { try { await enqueuePhoto(photoId); await fetchDescribeProgress() } catch (e) { message.error(e instanceof Error ? e.message : 'VLM 处理失败') } }
async function handleValidateDescription(photoId: string) {
  detailValidateProcessing.value = true
  try {
    const response = await fetch(`${getApiBase()}/photos/${photoId}/ai-validate`, { method: 'POST' })
    if (!response.ok) { const body = await response.json(); throw new Error(body.error || '重新校验失败') }
    await refreshPhoto(photoId)
    message.success('AI 描述校验完成')
  } catch (e) { message.error(e instanceof Error ? e.message : '重新校验失败') } finally { detailValidateProcessing.value = false }
}
async function handleStartEmbed() { await openBatchConfirm('embed') }
async function handleStopEmbed() { await stopEmbedQueue(); message.info('Embed 已中止'); relocateToStart(); fetchStats(); fetchEmbedStats() }
async function handleTriggerEmbed(photoId: string) { try { await enqueueEmbedPhoto(photoId); await fetchEmbedProgress() } catch (e) { message.error(e instanceof Error ? e.message : '入队失败') } }
function handleViewDescription() { if (selectedPhoto.value) { descPhoto.value = selectedPhoto.value; showDescModal.value = true } }
function handleRegenerateDescription() { if (descPhoto.value) handleTriggerDescribe(descPhoto.value.id); showDescModal.value = false }
async function handleDeletePhoto(photoId: string) { try { await deletePhoto(photoId); message.success('图片已删除'); fetchStats() } catch (e) { message.error(e instanceof Error ? e.message : '删除失败') } }
async function handleRebuildBurst() { try { const status = await rebuildBurst(() => { message.success(`连拍分组完成，精细 ${burstStatus.value.group_count} 组 / 模糊 ${burstStatus.value.coarse_group_count} 组`); relocateToStart(); syncBurstVectors() }); message[status === 'already_running' ? 'info' : 'success'](status === 'already_running' ? '连拍分组已在进行中' : '连拍分组重算已启动') } catch (e) { message.error(e instanceof Error ? e.message : '启动失败') } }
// 分组变了组向量集合就过期了，重建完成后立即对齐（封面向量复用全量集合，不重跑 Embedding）
async function syncBurstVectors() { try { const counts = await syncGroupCollections(); message.success(`连拍组向量已同步，精细 ${counts.fine ?? 0} 组 / 模糊 ${counts.coarse ?? 0} 组`) } catch (e) { message.warning(e instanceof Error ? e.message : '连拍组向量同步失败') } }
function handleCycleViewLevel() { const order = ['all', 'fine', 'coarse'] as const; settings.burstViewLevel = order[(order.indexOf(settings.burstViewLevel) + 1) % order.length]; applyFilters() }
function handleOpenBurstGroup(groupId: string, coverId: string) { openBurstGroup(groupId, coverId) }
function handleBurstSetCover(photoId: string) { setBurstCover(burstModalGroup.value, photoId).then(() => message.success('已设为封面')).catch((e) => message.error(e instanceof Error ? e.message : '设为封面失败')) }
async function handleUploadStart() { showConflictModal.value = true; await startUpload(async () => new Promise<ConflictResolution>((resolve) => { conflictResolver.value = resolve; showConflictModal.value = true })); showConflictModal.value = false; closeUploadModal(); message.success('上传完成'); relocateToStart(); fetchSegments(); fetchStats() }
function handleConflictResolve(resolution: ConflictResolution) { conflictResolver.value?.(resolution); conflictResolver.value = null; showConflictModal.value = false }
function toggleSortOrder() { sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'; applyFilters() }
function handleSegmentModeChange(mode: SegmentMode) { settings.segmentMode = mode; fetchSegments() }

watch(showConflictModal, (visible) => { if (!visible && conflictResolver.value) { conflictResolver.value('skip'); conflictResolver.value = null } })
watch(photos, (list) => fetchEmbeddedIds(list.map((photo) => ({ id: photo.id, description: photo.description }))))
watch(auxiliaryError, (text) => { if (text) message.error(text) })
watch(describeProcessingIds, async (newIds, oldIds) => {
  for (const id of oldIds) {
    if (!newIds.has(id)) {
      if (selectedPhoto.value?.id === id) fetchPhotoDetail(id)
      await refreshPhoto(id)
      const photo = selectedPhoto.value?.id === id ? selectedPhoto.value : await fetch(`${getApiBase()}/photos/${id}`).then((r) => r.json()).then((r) => r.photo)
      if (photo?.vlmStatus === 'healthy' || photo?.vlm_status === 'healthy') {
        await enqueueEmbedPhoto(id)
      }
      message.success('VLM 描述处理完成，已自动接续 Embedding')
    }
  }
})
watch(embedProcessingIds, (newIds, oldIds) => {
  for (const id of oldIds) {
    if (!newIds.has(id)) {
      fetchEmbeddedIds(photos.value.map((photo) => ({ id: photo.id, description: photo.description })))
      fetchEmbedStats()
    }
  }
})
onComplete(() => { relocateToStart(); fetchStats() })
onEmbedComplete(() => { relocateToStart(); fetchStats(); fetchEmbedStats() })
onMounted(async () => {
  await applyFilters()
  fetchStats()
  fetchTimelines()
  fetchEmbedStats()
  fetchBurstStatus()
  fetchDescribeProgress()
  fetchEmbedProgress()
  fetchVlmQueueStatus().then(() => { if (vlmStatus.value.running) startVlmPolling() })
  fetchEmbedQueueStatus().then(() => { if (embedStatus.value.running) startEmbedPolling() })
})
onUnmounted(() => { stopBurstPolling(); stopDescribePolling(); stopEmbedProgressPolling() })
</script>

<template>
  <NLayout class="page-layout">
    <NLayoutHeader bordered>
      <PhotoManagementToolbar
        v-model:search-filename="searchFilename" v-model:filter-timeline="filterTimeline" v-model:filter-shot-at-start="filterShotAtStart" v-model:filter-shot-at-end="filterShotAtEnd"
        :total="total" :stats="stats" :embed-stats="embedStats" :timelines="timelines" :burst-view-level="settings.burstViewLevel" :segment-mode="settings.segmentMode" :sort-order="sortOrder"
        :vlm-running="vlmStatus.running" :vlm-completed="vlmStatus.completed" :vlm-total="vlmStatus.total" :embed-running="embedStatus.running" :embed-completed="embedStatus.completed" :embed-total="embedStatus.total" :burst-running="burstStatus.running" :burst-processed="burstStatus.processed" :burst-total="burstStatus.total"
        :selection-mode="selectionMode" :selected-count="selectedCount" :show-interval-select="showIntervalSelect"
        @apply-filters="applyFilters" @reset-filters="resetFilters" @cycle-view-level="handleCycleViewLevel" @change-segment-mode="handleSegmentModeChange" @toggle-sort-order="toggleSortOrder" @start-vlm="handleStartVlm" @stop-vlm="handleStopVlm" @start-embed="handleStartEmbed" @stop-embed="handleStopEmbed" @rebuild-burst="handleRebuildBurst" @upload="openUploadModal"
        @toggle-selection-mode="toggleSelectionMode" @select-all="selectAllVisible" @clear-selection="clearSelection" @interval-select="intervalSelect" @go-to-post-studio="goToPostStudio"
      />
    </NLayoutHeader>
    <NLayoutContent><div class="content-wrapper">
      <PhotoListBrowser
        :photos="photos" :loading="loading" :loading-down="loadingDown" :loading-up="loadingUp" :no-more-down="noMoreDown" :no-more-up="noMoreUp" :error="error" :processing-ids="describeProcessingIds" :embed-processing-ids="embedProcessingIds" :embedded-ids="embeddedIds" :vlm-batch-running="vlmStatus.running" :embed-batch-running="embedStatus.running" :view-level="settings.burstViewLevel" :segment-mode="settings.segmentMode" :segments="segments" :relocate-to="relocateTo" :load-down="loadDown" :load-up="loadUp"
        :selection-mode="selectionMode" :selected-ids="selectedIds"
        @view-detail="fetchPhotoDetail" @trigger-describe="handleTriggerDescribe" @trigger-embed="handleTriggerEmbed" @delete-photo="handleDeletePhoto" @open-burst-group="handleOpenBurstGroup" @retry="relocateToStart" @back-to-latest="resetFilters" @toggle-select="toggleSelect"
      />
    </div></NLayoutContent>
  </NLayout>
  <PhotoDetail :show="showDetail" :photo="selectedPhoto" :loading="detailLoading" :nav-list="photoNavList" :describe-processing="detailDescribeProcessing" :embed-processing="detailEmbedProcessing" :validate-processing="detailValidateProcessing" :vlm-batch-running="vlmStatus.running" :embed-batch-running="embedStatus.running" :show-vlm-actions="true" @close="closeDetail" @navigate="fetchPhotoDetail" @trigger-describe="handleTriggerDescribe" @validate-description="handleValidateDescription" @trigger-embed="handleTriggerEmbed" @view-description="handleViewDescription" />
  <NModal v-model:show="showBatchConfirm" preset="card" :title="batchKind === 'vlm' ? '批量 VLM 审查' : '批量 Embedding 审查'" style="width: 640px">
    <NSpin :show="batchAuditLoading">
      <template v-if="batchAudit">
        <NAlert type="info" :show-icon="false" style="margin-bottom: 16px">
          <template v-if="batchKind === 'vlm'">没有 AI 描述 {{ batchAudit.counts.vlm_missing || 0 }} 张，描述疑似异常 {{ batchAudit.counts.vlm_review || 0 }} 张。</template>
          <template v-else>描述可信，“没有向量”或“已过期向量”的照片 {{ batchAudit.counts.embedding_missing || 0 }} 张。</template>
          {{ batchKind === 'vlm' ? '确认后重跑 VLM，并自动接续 Embedding。' : '确认后只重建向量，不调用 VLM。' }}
        </NAlert>
        <NEmpty v-if="!batchCount" description="暂无需要处理的照片" />
        <div v-else class="batch-preview">
          <div v-for="item in batchPreview" :key="item.id" class="batch-preview-item">
            <img :src="item.thumbnail_url" :alt="item.filename" />
            <span>{{ item.filename }}</span>
          </div>
          <div v-if="batchRemaining" class="batch-remaining">还有 {{ batchRemaining }} 张文件</div>
        </div>
      </template>
    </NSpin>
    <NSpace justify="end" style="margin-top: 20px">
      <NButton v-if="batchKind === 'vlm'" :loading="batchAuditLoading" @click="refreshBatchAudit">重新审查</NButton>
      <NButton @click="showBatchConfirm = false">取消</NButton>
      <NButton type="primary" :disabled="!batchCount || batchAuditLoading" @click="confirmBatchRepair">确认处理</NButton>
    </NSpace>
  </NModal>
  <BurstGroupModal :show="burstModalGroup !== ''" :group-id="burstModalGroup" :members="burstModalMembers" :cover-id="burstModalCoverId" :loading="burstModalLoading" @close="closeBurstGroup" @view-detail="fetchPhotoDetail" @set-cover="handleBurstSetCover" />
  <DescriptionModal :show="showDescModal" :filename="descPhoto?.filename || ''" :description="descPhoto?.description || ''" :model="descPhoto?.description_model || ''" :processed-at="descPhoto?.description_time || ''" @close="showDescModal = false" @regenerate="handleRegenerateDescription" />
  <UploadModal :show="showUploadModal" :files="files" :uploading="uploading" @close="closeUploadModal" @add-files="addFiles" @remove-file="removeFile" @start-upload="handleUploadStart" />
  <ConflictModal :show="showConflictModal" :conflict="currentConflict?.conflict || null" :new-filename="currentConflict?.file.originalName || ''" :new-shot-at="currentConflict?.file.shotAt || ''" @close="showConflictModal = false" @resolve="handleConflictResolve" />
</template>

<style scoped>
.page-layout > :deep(.n-layout-scroll-container) { display: flex; flex-direction: column; }
.page-layout :deep(.n-layout-header) { flex-shrink: 0; }
.page-layout :deep(.n-layout-content) { flex: 1; min-height: 0; }
.content-wrapper { display: flex; flex-direction: column; height: 100%; box-sizing: border-box; padding: 20px 24px; overflow: hidden; }
.batch-preview { display: flex; flex-wrap: wrap; gap: 10px; }
.batch-preview-item { width: 72px; color: var(--n-text-color-2); font-size: 11px; overflow: hidden; }
.batch-preview-item img { display: block; width: 72px; height: 52px; object-fit: cover; border-radius: 4px; margin-bottom: 4px; }
.batch-preview-item span { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.batch-remaining { align-self: center; color: var(--n-text-color-3); font-size: 12px; }
</style>
