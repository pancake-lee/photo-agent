<script setup lang="ts">
import { ref, watch } from 'vue'
import draggable from 'vuedraggable'
import { NEmpty } from 'naive-ui'
import { photoApi } from '../backend-sdk-client'
import { getApiBase } from '../config'
import PhotoCard from './PhotoCard.vue'
import BurstGroupModal from './BurstGroupModal.vue'
import type { PhotoListItem } from '../types/photo'

export interface SelectedPhotoItem {
  photo_id: string
  filename: string
  uuid: string
  granularity?: 'photo' | 'fine' | 'coarse'
  burst_group_id?: string
  burst_count?: number
}
const props = withDefaults(defineProps<{ items: SelectedPhotoItem[]; sortable?: boolean }>(), { sortable: false })
const emit = defineEmits<{ 'update:items': [items: SelectedPhotoItem[]]; preview: [photoId: string] }>()
const groupIndex = ref(-1)
const groupLoading = ref(false)
const groupMembers = ref<{ id: string; thumbnail_url: string; filename: string }[]>([])
const groupId = ref('')
const groupCoverId = ref('')
const orderedItems = ref<SelectedPhotoItem[]>([])
watch(() => props.items, (items) => { orderedItems.value = [...items] }, { immediate: true })
function updateOrder() { emit('update:items', [...orderedItems.value]) }
function isGroup(item: SelectedPhotoItem) { return Boolean(item.burst_group_id && (item.burst_count || 0) > 1 && item.granularity !== 'photo') }
function cardPhoto(item: SelectedPhotoItem): PhotoListItem {
  return { id: item.uuid, filename: item.filename, file_path: '', timeline: '', tags: '', description: '', shot_at: null, width: 0, height: 0, brand: '', model: '', lens: '', focal_length: '', aperture: '', iso: 0, exposure_time: '', latitude: null, longitude: null, altitude: null, imported_at: '', has_description: false, thumbnail_url: item.uuid ? `${getApiBase()}/photos/${item.uuid}/image` : '', has_nef: false, burst_group_id: item.burst_group_id || '', burst_cover: isGroup(item), burst_count: item.burst_count || 0 }
}
function removeAt(index: number) { emit('update:items', props.items.filter((_, i) => i !== index)) }
async function openGroup(index: number) {
  const item = props.items[index]
  if (!item || !isGroup(item)) return
  groupIndex.value = index; groupId.value = item.burst_group_id || ''; groupCoverId.value = item.uuid; groupMembers.value = []; groupLoading.value = true
  try {
    const profile = item.granularity === 'coarse' ? 'coarse' : 'fine'
    const resp = await photoApi.photoServiceSearchPhotos(1, 100, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, 'shot_at', 'asc', groupId.value, profile)
    groupMembers.value = (resp.items || []).map((p) => ({ id: p.id || '', filename: p.filename || '', thumbnail_url: p.id ? `${getApiBase()}/photos/${p.id}/image` : '' }))
  } finally { groupLoading.value = false }
}
function handleCurate(ids: string[]) {
  if (groupIndex.value < 0) return
  const chosen = groupMembers.value.filter((m) => ids.includes(m.id))
  const next = [...props.items]
  next.splice(groupIndex.value, 1, ...chosen.map((m) => ({ photo_id: m.id, filename: m.filename, uuid: m.id, granularity: 'photo' as const })))
  emit('update:items', next); groupIndex.value = -1
}
function handleClick(item: SelectedPhotoItem, index: number) { if (isGroup(item)) openGroup(index); else emit('preview', item.uuid) }
</script>
<template>
  <div class="selected-photo-list">
    <NEmpty v-if="items.length === 0" description="暂无已选照片" />
    <draggable v-else-if="sortable" v-model="orderedItems" item-key="photo_id" class="selected-photo-grid" @end="updateOrder">
      <template #item="{ element: item, index }">
        <div :key="`${item.photo_id}-${index}`">
        <PhotoCard :photo="cardPhoto(item)" :view-level="isGroup(item) ? item.granularity === 'coarse' ? 'coarse' : 'fine' : 'all'" :show-status="false" :show-embed="false" :show-delete="false" :show-remove="true" :show-tooltip="false" @open-burst-group="openGroup(index)" @view-detail="handleClick(item, index)" @remove="removeAt(index)" />
      </div>
      </template>
    </draggable>
    <div v-else class="selected-photo-grid">
      <div v-for="(item, index) in items" :key="`${item.photo_id}-${index}`">
        <PhotoCard :photo="cardPhoto(item)" :view-level="isGroup(item) ? item.granularity === 'coarse' ? 'coarse' : 'fine' : 'all'" :show-status="false" :show-embed="false" :show-delete="false" :show-remove="true" :show-tooltip="false" @open-burst-group="openGroup(index)" @view-detail="handleClick(item, index)" @remove="removeAt(index)" />
      </div>
    </div>
  </div>
  <BurstGroupModal :show="groupIndex >= 0" :group-id="groupId" :members="groupMembers" :cover-id="groupCoverId" :loading="groupLoading" mode="curate" @close="groupIndex = -1" @view-detail="emit('preview', $event)" @curate="handleCurate" />
</template>
<style scoped>
.selected-photo-list { min-height: 96px; }
.selected-photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; }
</style>
