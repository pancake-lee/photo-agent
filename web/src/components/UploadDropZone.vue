<script setup lang="ts">
import { ref } from 'vue'
import { NIcon } from 'naive-ui'
import { CloudUploadOutline } from '@vicons/ionicons5'

const emit = defineEmits<{
  files: [files: FileList | File[]]
}>()

const dragging = ref(false)
const fileInput = ref<HTMLInputElement>()

function onDragOver(e: DragEvent) {
  e.preventDefault()
  dragging.value = true
}

function onDragLeave() {
  dragging.value = false
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  dragging.value = false
  if (e.dataTransfer?.files.length) {
    emit('files', e.dataTransfer.files)
  }
}

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) {
    emit('files', input.files)
    input.value = '' // 重置以允许重复选择同一文件
  }
}
</script>

<template>
  <div
    class="drop-zone"
    :class="{ dragging }"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
    @click="fileInput?.click()"
  >
    <NIcon size="48" color="var(--n-text-color-3)">
      <CloudUploadOutline />
    </NIcon>
    <p class="drop-text">拖拽图片到此处，或点击选择文件</p>
    <p class="drop-hint">支持 JPG / PNG / HEIC / TIFF</p>
    <input
      ref="fileInput"
      type="file"
      accept="image/*"
      multiple
      style="display: none"
      @change="onFileSelect"
    />
  </div>
</template>

<style scoped>
.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  border: 2px dashed var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition:
    border-color 0.2s,
    background 0.2s;
}
.drop-zone:hover,
.drop-zone.dragging {
  border-color: var(--n-color-primary);
  background: var(--n-color-primary-hover);
}
.drop-text {
  margin: 12px 0 4px;
  font-size: 14px;
  color: var(--n-text-color-2);
}
.drop-hint {
  margin: 0;
  font-size: 12px;
  color: var(--n-text-color-3);
}
</style>
