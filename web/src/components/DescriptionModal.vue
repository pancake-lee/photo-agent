<script setup lang="ts">
import { NModal, NButton, NSpace, NDivider, NTag } from 'naive-ui'
import { formatDate } from '../utils/format'

const props = defineProps<{
  show: boolean
  filename: string
  description: string
  model: string
  processedAt: string
}>()

const emit = defineEmits<{
  close: []
  regenerate: []
}>()

function formatTime(t: string): string {
  if (!t) return '未知'
  try {
    return formatDate(t)
  } catch {
    return t
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`图像描述 - ${filename}`"
    style="max-width: 600px"
    @close="$emit('close')"
  >
    <div class="desc-meta">
      <NTag type="info" size="small">模型：{{ model || '未知' }}</NTag>
      <NTag size="small">生成时间：{{ formatTime(processedAt) }}</NTag>
    </div>

    <NDivider />

    <div class="desc-content">
      {{ description || '暂无描述' }}
    </div>

    <NDivider />

    <NSpace justify="end">
      <NButton type="primary" @click="$emit('regenerate')">
        重新生成
      </NButton>
      <NButton @click="$emit('close')">关闭</NButton>
    </NSpace>
  </NModal>
</template>

<style scoped>
.desc-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.desc-content {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: 14px;
  max-height: 400px;
  overflow-y: auto;
}
</style>
