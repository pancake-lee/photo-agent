<script setup lang="ts">
import { NCard, NButton, NIcon, NSpin, NTooltip, NPopconfirm } from 'naive-ui'
import {
  CheckmarkCircle,
  AddCircleOutline,
  TrashOutline,
  LayersOutline,
} from '@vicons/ionicons5'
import type { PhotoListItem } from '../types/photo'
import { formatDate } from '../utils/format'

const props = defineProps<{
  photo: PhotoListItem
  processing?: boolean
  isEmbedded?: boolean
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  deletePhoto: [photoId: string]
}>()

function handleStatusClick() {
  if (props.processing) return
  if (props.photo.has_description) {
    emit('viewDetail', props.photo.id)
  } else {
    emit('triggerDescribe', props.photo.id)
  }
}

function handleEmbedClick() {
  if (props.processing) return
  if (props.isEmbedded) return
  if (props.photo.has_description) {
    emit('triggerEmbed', props.photo.id)
  }
}

function formatExifTooltip(): string {
  const p = props.photo
  const parts: string[] = []
  if (p.shot_at) parts.push(`拍摄: ${formatDate(p.shot_at)}`)
  if (p.brand && p.model) parts.push(`${p.brand} ${p.model}`)
  else if (p.model) parts.push(p.model)
  if (p.lens) parts.push(`镜头: ${p.lens}`)
  if (p.iso) parts.push(`ISO ${p.iso}`)
  if (p.aperture) parts.push(p.aperture)
  if (p.focal_length) parts.push(p.focal_length)
  return parts.join('\n') || '暂无 EXIF 信息'
}
</script>

<template>
  <NTooltip trigger="hover">
    <template #trigger>
      <NCard
        :bordered="true"
        size="small"
        class="photo-card"
        hoverable
        @click="$emit('viewDetail', photo.id)"
      >
        <template #cover>
          <div class="photo-thumb">
            <img
              :src="photo.thumbnail_url"
              :alt="photo.filename"
              loading="lazy"
            />
            <div class="photo-status">
              <NSpin v-if="processing" size="small" />
              <NButton
                v-else-if="photo.has_description"
                size="tiny"
                circle
                type="success"
                @click.stop="handleStatusClick"
              >
                <template #icon>
                  <NIcon><CheckmarkCircle /></NIcon>
                </template>
              </NButton>
              <NButton
                v-else
                size="tiny"
                circle
                dashed
                @click.stop="handleStatusClick"
              >
                <template #icon>
                  <NIcon><AddCircleOutline /></NIcon>
                </template>
              </NButton>
            </div>
            <!-- Embed 状态图标（左下角） -->
            <div class="photo-embed-status">
              <NButton
                v-if="isEmbedded"
                size="tiny"
                circle
                type="info"
                @click.stop
              >
                <template #icon>
                  <NIcon><LayersOutline /></NIcon>
                </template>
              </NButton>
              <NButton
                v-else-if="photo.has_description"
                size="tiny"
                circle
                dashed
                type="info"
                @click.stop="handleEmbedClick"
              >
                <template #icon>
                  <NIcon><LayersOutline /></NIcon>
                </template>
              </NButton>
              <NButton
                v-else
                size="tiny"
                circle
                disabled
              >
                <template #icon>
                  <NIcon><LayersOutline /></NIcon>
                </template>
              </NButton>
            </div>
            <div class="photo-delete">
              <NPopconfirm
                @positive-click="$emit('deletePhoto', photo.id)"
              >
                <template #trigger>
                  <NButton
                    size="tiny"
                    circle
                    type="error"
                    @click.stop
                  >
                    <template #icon>
                      <NIcon><TrashOutline /></NIcon>
                    </template>
                  </NButton>
                </template>
                确定删除该图片？（原图文件和数据库记录将被永久删除）
              </NPopconfirm>
            </div>
          </div>
        </template>
        <div class="photo-name">{{ photo.filename }}</div>
      </NCard>
    </template>
    <pre class="exif-tooltip">{{ formatExifTooltip() }}</pre>
  </NTooltip>
</template>

<style scoped>
.photo-card {
  cursor: pointer;
  transition: transform 0.15s;
}
.photo-card:hover {
  transform: translateY(-2px);
}
.photo-thumb {
  position: relative;
  aspect-ratio: 1;
  overflow: hidden;
  background: var(--n-color-embedded);
}
.photo-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.photo-status {
  position: absolute;
  bottom: 6px;
  right: 6px;
}
.photo-embed-status {
  position: absolute;
  bottom: 6px;
  left: 6px;
}
.photo-delete {
  position: absolute;
  top: 4px;
  right: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}
.photo-card:hover .photo-delete {
  opacity: 1;
}
.photo-name {
  font-size: 12px;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
  padding: 4px 0;
}
.exif-tooltip {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-line;
}
</style>
