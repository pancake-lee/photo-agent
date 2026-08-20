<script setup lang="ts">
import { computed } from 'vue'
import { NGrid, NGi, NSpin, NEmpty, NAlert, NButton, NIcon } from 'naive-ui'
import { ChevronUpOutline } from '@vicons/ionicons5'
import PhotoCard from './PhotoCard.vue'
import PhotoThumbList from './PhotoThumbList.vue'
import type { PhotoListItem } from '../types/photo'

const props = defineProps<{
  photos: PhotoListItem[]
  loading: boolean
  error: string | null
  processingIds: Set<string>
  embeddedIds: Set<string>
  /** 当前展开的连拍组 id（空 = 全部收起） */
  expandedBurstGroup: string
  /** 展开组的成员照片 */
  burstMembers: PhotoListItem[]
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  deletePhoto: [photoId: string]
  toggleBurstGroup: [groupId: string]
  retry: []
}>()

/** 折叠模式下网格只渲染封面照片（burst_cover=true）与非组内照片 */
function visiblePhotos(): PhotoListItem[] {
  return props.photos.filter((p) => p.burst_group_id === '' || p.burst_cover)
}

/** 展开的组横条插在封面照片之后 */
function isExpandedGroupCover(photo: PhotoListItem): boolean {
  return (
    photo.burst_group_id !== '' &&
    photo.burst_cover &&
    props.expandedBurstGroup === photo.burst_group_id
  )
}

/** burstMembers 适配 PhotoThumbList 的 PhotoRef 形状（photo_id 取照片 id） */
const burstMemberRefs = computed(() =>
  props.burstMembers.map((p) => ({ photo_id: p.id, filename: p.filename })),
)
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
        :span="isExpandedGroupCover(photo) ? 4 : 1"
        :xs="isExpandedGroupCover(photo) ? 24 : 2"
        :s="isExpandedGroupCover(photo) ? 24 : 1"
        :m="isExpandedGroupCover(photo) ? 24 : 1"
        :l="isExpandedGroupCover(photo) ? 24 : 1"
      >
        <PhotoCard
          :photo="photo"
          :processing="processingIds.has(photo.id)"
          :is-embedded="embeddedIds.has(photo.id)"
          @view-detail="(id) => $emit('viewDetail', id)"
          @trigger-describe="(id) => $emit('triggerDescribe', id)"
          @trigger-embed="(id) => $emit('triggerEmbed', id)"
          @delete-photo="(id) => $emit('deletePhoto', id)"
          @toggle-burst-group="(gid) => $emit('toggleBurstGroup', gid)"
        />

        <!-- 展开的连拍组横条：组内全部成员缩略图 -->
        <div
          v-if="isExpandedGroupCover(photo)"
          class="burst-strip"
        >
          <div class="burst-strip-header" @click="$emit('toggleBurstGroup', photo.burst_group_id)">
            <NIcon size="14"><ChevronUpOutline /></NIcon>
            <span>连拍组 {{ burstMembers.length || photo.burst_count }} 张，点击收起</span>
          </div>
          <PhotoThumbList
            :photos="burstMemberRefs"
            :max-preview="0"
            empty-text="加载中..."
            @preview="(id) => $emit('viewDetail', id)"
          />
        </div>
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
.burst-strip {
  margin-top: 8px;
  padding: 8px 12px;
  border: 1px dashed var(--n-border-color);
  border-radius: 8px;
  background: var(--n-color-embedded);
}
.burst-strip-header {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--n-text-color-3);
  cursor: pointer;
  margin-bottom: 8px;
  user-select: none;
}
</style>
