<script setup lang="ts">
import { NButton, NInput, NModal, NSpace } from 'naive-ui'
import { formatDate } from '../utils/format'
import PhotoThumbList from './PhotoThumbList.vue'
import type { GoldenPhotoRef, GoldenQuery } from '../types/goldenQuery'

defineProps<{
  show: boolean
  item: GoldenQuery | null
  saving: boolean
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
  preview: [uuid: string]
  remove: [photoId: string]
  add: []
  cancel: []
  save: []
}>()
</script>

<template>
  <NModal :show="show" preset="card" title="黄金用例详情" style="width: 640px; max-width: 90vw;" @update:show="emit('update:show', $event)">
    <div v-if="item" class="detail-body">
      <div class="detail-field">
        <span class="detail-label">查询文本</span>
        <NInput :value="query" placeholder="请输入查询文本" @update:value="emit('update:query', $event)" />
      </div>
      <div class="detail-field">
        <span class="detail-label">分类</span>
        <NInput :value="category" placeholder="可留空" @update:value="emit('update:category', $event)" />
      </div>
      <div class="detail-field">
        <span class="detail-label">备注</span>
        <NInput :value="notes" type="textarea" placeholder="可留空" @update:value="emit('update:notes', $event)" />
      </div>
      <div class="detail-field">
        <span class="detail-label">创建时间</span>
        <span class="detail-value">{{ item.created_at ? formatDate(item.created_at) : '—' }}</span>
      </div>
      <div class="detail-field">
        <span class="detail-label">关联照片 ({{ photos.length }})</span>
        <PhotoThumbList :photos="photos" editable auto-fit empty-text="暂无关联照片，请增加照片" @preview="emit('preview', $event)" @remove="emit('remove', $event)" @add="emit('add')" />
      </div>
    </div>
    <template #footer>
      <NSpace justify="end">
        <NButton size="small" :disabled="saving" @click="emit('cancel')">取消</NButton>
        <NButton size="small" type="primary" :loading="saving" @click="emit('save')">保存</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.detail-body, .detail-field { display: flex; flex-direction: column; }
.detail-body { gap: 16px; }
.detail-field { gap: 4px; }
.detail-label { font-size: 12px; font-weight: 600; color: var(--n-text-color-3); text-transform: uppercase; }
.detail-value { font-size: 14px; color: var(--n-text-color); }
</style>
