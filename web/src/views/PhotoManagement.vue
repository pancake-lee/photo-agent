<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NLayout, NLayoutContent, NLayoutHeader, useMessage } from 'naive-ui'
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

const message = useMessage()
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
const { status: embedStatus, startQueue: startEmbedQueue, stopQueue: stopEmbedQueue, enqueuePhoto: enqueueEmbedPhoto, onComplete: onEmbedComplete, embedProcessingIds, fetchEmbedProgress, stopEmbedProgressPolling, fetchStatus: fetchEmbedQueueStatus, startPolling: startEmbedPolling } = useEmbedQueue()
const { embeddedIds, embedStats, fetchEmbeddedIds, fetchEmbedStats } = useEmbedStatus()
const { status: burstStatus, rebuild: rebuildBurst, fetchStatus: fetchBurstStatus, stopPolling: stopBurstPolling } = useBurstGroups()
const showDescModal = ref(false)
const descPhoto = ref<PhotoDetailType | null>(null)
const showConflictModal = ref(false)
const conflictResolver = ref<((resolution: ConflictResolution) => void) | null>(null)
const detailDescribeProcessing = computed(() => !!selectedPhoto.value && describeProcessingIds.value.has(selectedPhoto.value.id))
const detailEmbedProcessing = computed(() => !!selectedPhoto.value && embedProcessingIds.value.has(selectedPhoto.value.id))

async function handleStartVlm() { try { const result = await startQueue(); message[result.total === 0 ? 'info' : 'success'](result.total === 0 ? '所有照片已有描述，无需处理' : `VLM 预处理已启动，共 ${result.total} 张`) } catch (e) { message.error(e instanceof Error ? e.message : '启动失败') } }
async function handleStopVlm() { await stopQueue(); message.info('VLM 预处理已中止'); relocateToStart(); fetchStats() }
async function handleTriggerDescribe(photoId: string) { try { await enqueuePhoto(photoId); await fetchDescribeProgress() } catch (e) { message.error(e instanceof Error ? e.message : 'VLM 处理失败') } }
async function handleStartEmbed() { try { const result = await startEmbedQueue(); message[result.total === 0 ? 'info' : 'success'](result.total === 0 ? '所有照片已有嵌入，无需处理' : `Embed 已启动，共 ${result.total} 张`) } catch (e) { message.error(e instanceof Error ? e.message : '启动失败') } }
async function handleStopEmbed() { await stopEmbedQueue(); message.info('Embed 已中止'); relocateToStart(); fetchStats(); fetchEmbedStats() }
async function handleTriggerEmbed(photoId: string) { try { await enqueueEmbedPhoto(photoId); await fetchEmbedProgress() } catch (e) { message.error(e instanceof Error ? e.message : '入队失败') } }
function handleViewDescription() { if (selectedPhoto.value) { descPhoto.value = selectedPhoto.value; showDescModal.value = true } }
function handleRegenerateDescription() { if (descPhoto.value) handleTriggerDescribe(descPhoto.value.id); showDescModal.value = false }
async function handleDeletePhoto(photoId: string) { try { await deletePhoto(photoId); message.success('图片已删除'); fetchStats() } catch (e) { message.error(e instanceof Error ? e.message : '删除失败') } }
async function handleRebuildBurst() { try { const status = await rebuildBurst(() => { message.success(`连拍分组完成，精细 ${burstStatus.value.group_count} 组 / 模糊 ${burstStatus.value.coarse_group_count} 组`); relocateToStart() }); message[status === 'already_running' ? 'info' : 'success'](status === 'already_running' ? '连拍分组已在进行中' : '连拍分组重算已启动') } catch (e) { message.error(e instanceof Error ? e.message : '启动失败') } }
function handleCycleViewLevel() { const order = ['all', 'fine', 'coarse'] as const; settings.burstViewLevel = order[(order.indexOf(settings.burstViewLevel) + 1) % order.length]; applyFilters() }
function handleOpenBurstGroup(groupId: string, coverId: string) { openBurstGroup(groupId, coverId) }
function handleBurstSetCover(photoId: string) { setBurstCover(burstModalGroup.value, photoId).then(() => message.success('已设为封面')).catch((e) => message.error(e instanceof Error ? e.message : '设为封面失败')) }
async function handleUploadStart() { showConflictModal.value = true; await startUpload(async () => new Promise<ConflictResolution>((resolve) => { conflictResolver.value = resolve; showConflictModal.value = true })); showConflictModal.value = false; closeUploadModal(); message.success('上传完成'); relocateToStart(); fetchSegments(); fetchStats() }
function handleConflictResolve(resolution: ConflictResolution) { conflictResolver.value?.(resolution); conflictResolver.value = null; showConflictModal.value = false }
function toggleSortOrder() { sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'; applyFilters() }
function handleSegmentModeChange(mode: SegmentMode) { settings.segmentMode = mode; fetchSegments() }

watch(showConflictModal, (visible) => { if (!visible && conflictResolver.value) { conflictResolver.value('skip'); conflictResolver.value = null } })
watch(photos, (list) => fetchEmbeddedIds(list.map((photo) => photo.id)))
watch(auxiliaryError, (text) => { if (text) message.error(text) })
watch(describeProcessingIds, (newIds, oldIds) => {
  for (const id of oldIds) {
    if (!newIds.has(id)) {
      refreshPhoto(id)
      message.success('VLM 描述已生成')
    }
  }
})
watch(embedProcessingIds, (newIds, oldIds) => {
  for (const id of oldIds) {
    if (!newIds.has(id)) {
      fetchEmbeddedIds(photos.value.map((p) => p.id))
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
        @apply-filters="applyFilters" @reset-filters="resetFilters" @cycle-view-level="handleCycleViewLevel" @change-segment-mode="handleSegmentModeChange" @toggle-sort-order="toggleSortOrder" @start-vlm="handleStartVlm" @stop-vlm="handleStopVlm" @start-embed="handleStartEmbed" @stop-embed="handleStopEmbed" @rebuild-burst="handleRebuildBurst" @upload="openUploadModal"
      />
    </NLayoutHeader>
    <NLayoutContent><div class="content-wrapper">
      <PhotoListBrowser
        :photos="photos" :loading="loading" :loading-down="loadingDown" :loading-up="loadingUp" :no-more-down="noMoreDown" :no-more-up="noMoreUp" :error="error" :processing-ids="describeProcessingIds" :embed-processing-ids="embedProcessingIds" :embedded-ids="embeddedIds" :vlm-batch-running="vlmStatus.running" :embed-batch-running="embedStatus.running" :view-level="settings.burstViewLevel" :segment-mode="settings.segmentMode" :segments="segments" :relocate-to="relocateTo" :load-down="loadDown" :load-up="loadUp"
        @view-detail="fetchPhotoDetail" @trigger-describe="handleTriggerDescribe" @trigger-embed="handleTriggerEmbed" @delete-photo="handleDeletePhoto" @open-burst-group="handleOpenBurstGroup" @retry="relocateToStart" @back-to-latest="resetFilters"
      />
    </div></NLayoutContent>
  </NLayout>
  <PhotoDetail :show="showDetail" :photo="selectedPhoto" :loading="detailLoading" :describe-processing="detailDescribeProcessing" :embed-processing="detailEmbedProcessing" :vlm-batch-running="vlmStatus.running" :embed-batch-running="embedStatus.running" @close="closeDetail" @trigger-describe="handleTriggerDescribe" @trigger-embed="handleTriggerEmbed" @view-description="handleViewDescription" />
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
</style>
