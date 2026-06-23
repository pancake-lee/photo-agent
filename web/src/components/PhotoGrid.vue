<script setup lang="ts">
import { NGrid, NGi, NSpin, NEmpty, NAlert, NButton } from 'naive-ui'
import PhotoCard from './PhotoCard.vue'
import type { PhotoListItem } from '../types/photo'

defineProps<{
  photos: PhotoListItem[]
  loading: boolean
  error: string | null
  processingIds: Set<string>
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  deletePhoto: [photoId: string]
  retry: []
}>()
</script>

<template>
  <!-- 加载中 -->
  <div v-if="loading" class="grid-state">
    <NSpin size="large" />
  </div>

  <!-- 错误 -->
  <div v-else-if="error" class="grid-state">
    <NAlert type="error" :title="error" />
    <NButton style="margin-top: 12px" @click="$emit('retry')">重试</NButton>
  </div>

  <!-- 空状态 -->
  <div v-else-if="photos.length === 0" class="grid-state">
    <NEmpty description="还没有照片，点击上方按钮开始" />
  </div>

  <!-- 照片网格 -->
  <NGrid
    v-else
    :cols="4"
    :x-gap="12"
    :y-gap="12"
    responsive="screen"
    item-responsive
  >
    <NGi
      v-for="photo in photos"
      :key="photo.id"
      :span="1"
      :xs="2"
      :s="1"
      :m="1"
      :l="1"
    >
      <PhotoCard
        :photo="photo"
        :processing="processingIds.has(photo.id)"
        @view-detail="(id) => $emit('viewDetail', id)"
        @trigger-describe="(id) => $emit('triggerDescribe', id)"
        @delete-photo="(id) => $emit('deletePhoto', id)"
      />
    </NGi>
  </NGrid>
</template>

<style scoped>
.grid-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}
</style>
