<script setup lang="ts">
import { NGrid, NGi, NSpin, NEmpty, NAlert, NButton } from 'naive-ui'
import PhotoCard from './PhotoCard.vue'
import type { PhotoListItem, BurstViewLevel } from '../types/photo'

const props = defineProps<{
  photos: PhotoListItem[]
  loading: boolean
  error: string | null
  processingIds: Set<string>
  embeddedIds: Set<string>
  /** 连拍展示级别：all 全部展开 / fine 精细折叠 / coarse 模糊折叠 */
  viewLevel: BurstViewLevel
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  deletePhoto: [photoId: string]
  openBurstGroup: [groupId: string, coverId: string]
  retry: []
}>()

/** 折叠级别下网格只渲染封面照片（burst_cover=true）与非组内照片；全部展开时渲染全部 */
function visiblePhotos(): PhotoListItem[] {
  if (props.viewLevel === 'all') return props.photos
  return props.photos.filter((p) => p.burst_group_id === '' || p.burst_cover)
}
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
  <template v-else>
    <NGrid
      :cols="4"
      :x-gap="12"
      :y-gap="12"
      responsive="screen"
      item-responsive
    >
      <NGi
        v-for="photo in visiblePhotos()"
        :key="photo.id"
        :span="1"
        :xs="2"
        :s="1"
        :m="1"
        :l="1"
      >
        <PhotoCard
          :photo="photo"
          :view-level="viewLevel"
          :processing="processingIds.has(photo.id)"
          :is-embedded="embeddedIds.has(photo.id)"
          @view-detail="(id) => $emit('viewDetail', id)"
          @trigger-describe="(id) => $emit('triggerDescribe', id)"
          @trigger-embed="(id) => $emit('triggerEmbed', id)"
          @delete-photo="(id) => $emit('deletePhoto', id)"
          @open-burst-group="(gid, coverId) => $emit('openBurstGroup', gid, coverId)"
        />
      </NGi>
    </NGrid>
  </template>
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
