<script setup lang="ts">
import { NModal, NButton, NSpace } from 'naive-ui'
import UploadDropZone from './UploadDropZone.vue'
import FileList from './FileList.vue'
import type { UploadFile } from '../types/upload'

defineProps<{
  show: boolean
  files: UploadFile[]
  uploading: boolean
}>()

const emit = defineEmits<{
  close: []
  addFiles: [files: FileList | File[]]
  removeFile: [id: string]
  startUpload: []
}>()

const pendingCount = (files: UploadFile[]) =>
  files.filter(
    (f) => f.uploadStatus === 'pending' && f.compressStatus === 'done'
  ).length
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="上传图片"
    style="max-width: 560px"
    @close="$emit('close')"
  >
    <UploadDropZone @files="(f) => $emit('addFiles', f)" />

    <FileList
      :files="files"
      @remove="(id) => $emit('removeFile', id)"
    />

    <NSpace justify="end" style="margin-top: 20px">
      <NButton @click="$emit('close')">取消</NButton>
      <NButton
        type="primary"
        :loading="uploading"
        :disabled="files.length === 0 || uploading"
        @click="$emit('startUpload')"
      >
        开始上传 ({{ pendingCount(files) }})
      </NButton>
    </NSpace>
  </NModal>
</template>
