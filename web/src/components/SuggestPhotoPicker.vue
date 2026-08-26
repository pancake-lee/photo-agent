<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NSpace } from 'naive-ui'
import { ShuffleOutline } from '@vicons/ionicons5'
import PhotoPickOverlay from './PhotoPickOverlay.vue'
import { createPickSession, clearPickSession, type PickedPhoto } from '../utils/photoPickSession'

export interface SuggestPickedPhoto {
  photo_id: string
  description?: string
  uuid?: string
  filename?: string
  granularity?: 'photo' | 'fine' | 'coarse'
  burst_group_id?: string
  burst_count?: number
}
const props = withDefaults(defineProps<{
  selectedIds: SuggestPickedPhoto[]
  source: string
  randomSample?: () => Promise<SuggestPickedPhoto[] | null>
}>(), {})
const emit = defineEmits<{
  'update:selectedIds': [value: SuggestPickedPhoto[]]
  open: []
  close: []
}>()
const visible = ref(false)
const count = computed(() => props.selectedIds.length)
function open() {
  createPickSession({ source: props.source, selected: props.selectedIds.map((p) => ({
    photo_id: p.photo_id,
    filename: p.filename || p.photo_id,
    uuid: p.uuid || p.photo_id,
    granularity: p.granularity,
    burst_group_id: p.burst_group_id,
    burst_count: p.burst_count,
  })) })
  visible.value = true
  emit('open')
}
function confirm(photos: PickedPhoto[]) {
  emit('update:selectedIds', photos.map((p) => ({
    photo_id: p.uuid || p.photo_id,
    description: '',
    uuid: p.uuid,
    filename: p.filename,
    granularity: p.granularity,
    burst_group_id: p.burst_group_id,
    burst_count: p.burst_count,
  })))
  clearPickSession(); visible.value = false; emit('close')
}
function cancel() { clearPickSession(); visible.value = false; emit('close') }
async function randomize() {
  const result = await props.randomSample?.()
  if (result) emit('update:selectedIds', result)
}
</script>
<template>
  <NSpace align="center">
    <NButton type="primary" secondary @click="open">选择照片</NButton>
    <NButton v-if="randomSample" @click="randomize">
      <template #icon><NIcon><ShuffleOutline /></NIcon></template>随机选取
    </NButton>
    <span class="count">已选 {{ count }} 张</span>
  </NSpace>
  <PhotoPickOverlay :show="visible" :preselected="selectedIds.map((p) => ({ photo_id: p.photo_id, filename: p.filename || p.photo_id, uuid: p.uuid || p.photo_id }))" @confirm="confirm" @cancel="cancel" />
</template>
<style scoped>.count { color: var(--n-text-color-3); font-size: 13px; }</style>
