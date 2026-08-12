<script setup lang="ts">
/**
 * PhotoPreviewModal — 照片预览弹窗
 *
 * 统一 ChatView / GoldenQueryManagement / ClusterView 中重复的 NModal + img 预览结构。
 */
import { NModal, NButton } from 'naive-ui'

const props = withDefaults(defineProps<{
  show: boolean
  imageUrl: string
  title?: string
  showDownload?: boolean
  downloadFilename?: string
}>(), {
  title: '照片预览',
  showDownload: false,
  downloadFilename: 'photo',
})

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

function handleDownload() {
  fetch(props.imageUrl)
    .then(res => res.blob())
    .then(blob => {
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = props.downloadFilename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objUrl)
    })
    .catch(() => {
      window.open(props.imageUrl, '_blank')
    })
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="title"
    style="width: 90vw; max-width: 1200px;"
    @update:show="emit('update:show', $event)"
  >
    <div class="preview-container">
      <img :src="imageUrl" class="preview-image" />
      <div v-if="showDownload" class="preview-actions">
        <NButton type="primary" @click="handleDownload">
          下载原图
        </NButton>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.preview-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 8px;
}
.preview-actions {
  display: flex;
  gap: 12px;
}
</style>
