<script setup lang="ts">
import { NIcon, NTag, NButton } from 'naive-ui'
import { CloseOutline, CheckmarkCircle, AlertCircle } from '@vicons/ionicons5'
import type { UploadFile } from '../types/upload'

defineProps<{
  files: UploadFile[]
}>()

const emit = defineEmits<{
  remove: [id: string]
}>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function compressLabel(file: UploadFile): string {
  switch (file.compressStatus) {
    case 'pending':
      return '等待压缩'
    case 'compressing':
      return '压缩中...'
    case 'done':
      if (file.compressedSize && file.originalSize) {
        return `${formatSize(file.originalSize)} → ${formatSize(file.compressedSize)}`
      }
      return '已就绪'
    case 'error':
      return '压缩失败'
    default:
      return ''
  }
}

function compressTagType(
  status: UploadFile['compressStatus']
): 'default' | 'info' | 'success' | 'warning' | 'error' {
  switch (status) {
    case 'pending':
      return 'default'
    case 'compressing':
      return 'info'
    case 'done':
      return 'success'
    case 'error':
      return 'error'
    default:
      return 'default'
  }
}
</script>

<template>
  <div v-if="files.length > 0" class="file-list">
    <h4>已添加的文件</h4>
    <div
      v-for="file in files"
      :key="file.id"
      class="file-item"
    >
      <div class="file-icon">📷</div>
      <div class="file-info">
        <div class="file-name">{{ file.originalName }}</div>
        <div class="file-tags">
          <NTag
            :type="compressTagType(file.compressStatus)"
            size="small"
          >
            <template #icon>
              <NIcon v-if="file.compressStatus === 'done'">
                <CheckmarkCircle />
              </NIcon>
              <NIcon v-else-if="file.compressStatus === 'error'">
                <AlertCircle />
              </NIcon>
            </template>
            {{ compressLabel(file) }}
          </NTag>
        </div>
      </div>
      <NButton
        text
        size="tiny"
        @click="$emit('remove', file.id)"
      >
        <template #icon>
          <NIcon><CloseOutline /></NIcon>
        </template>
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.file-list {
  margin-top: 16px;
}
.file-list h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--n-text-color-2);
}
.file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--n-color-embedded);
  margin-bottom: 6px;
}
.file-icon {
  font-size: 20px;
  flex-shrink: 0;
}
.file-info {
  flex: 1;
  min-width: 0;
}
.file-name {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 4px;
}
.file-tags {
  display: flex;
  gap: 4px;
}
</style>
