<script setup lang="ts">
import { NButton, NInput, NModal, NSpace } from 'naive-ui'
import SelectedPhotoList, { type SelectedPhotoItem } from './SelectedPhotoList.vue'
import type { GoldenPhotoRef } from '../types/goldenQuery'

defineProps<{
  show: boolean
  creating: boolean
  query: string
  category: string
  notes: string
  photos: GoldenPhotoRef[]
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'update:query': [value: string]
  'update:category': [value: string]
  'update:notes': [value: string]
  'update:photos': [value: GoldenPhotoRef[]]
  preview: [uuid: string]
  pick: []
  create: []
}>()
</script>

<template>
  <NModal :show="show" preset="card" title="新建黄金用例" style="width: 760px; max-width: 95vw;" @update:show="emit('update:show', $event)">
    <div class="create-body">
      <div class="detail-field">
        <span class="detail-label">查询文本</span>
        <NInput :value="query" placeholder="例如：佛像和人的合照" @update:value="emit('update:query', $event)" />
      </div>
      <div class="create-row">
        <div class="detail-field create-row-item"><span class="detail-label">分类</span><NInput :value="category" placeholder="可留空" @update:value="emit('update:category', $event)" /></div>
        <div class="detail-field create-row-item"><span class="detail-label">备注</span><NInput :value="notes" placeholder="可留空" @update:value="emit('update:notes', $event)" /></div>
      </div>
      <div class="detail-field"><span class="detail-label">选择期望照片</span><NButton size="small" @click="emit('pick')">选择照片（进入图片管理选图）</NButton></div>
      <div v-if="photos.length" class="detail-field">
        <span class="detail-label">已选照片 ({{ photos.length }})</span>
        <span class="selected-photo-hint">连拍集合会把所有子图加入黄金用例；如需精选，请进入连拍组操作。</span>
        <SelectedPhotoList :items="photos as SelectedPhotoItem[]" @update:items="emit('update:photos', $event)" @preview="emit('preview', $event)" />
      </div>
    </div>
    <template #footer><NSpace justify="end"><NButton size="small" @click="emit('update:show', false)">取消</NButton><NButton size="small" type="primary" :loading="creating" @click="emit('create')">保存</NButton></NSpace></template>
  </NModal>
</template>

<style scoped>
.create-body, .detail-field { display: flex; flex-direction: column; }
.create-body { gap: 16px; max-height: 68vh; overflow-y: auto; }
.detail-field { gap: 4px; }
.detail-label, .selected-photo-hint { font-size: 12px; color: var(--n-text-color-3); }
.detail-label { font-weight: 600; text-transform: uppercase; }
.create-row { display: flex; gap: 16px; }
.create-row-item { flex: 1; }
</style>
