<script setup lang="ts">
/**
 * PhotoThumbList — 照片缩略预览列表
 *
 * 统一 GoldenQueryManagement / ClusterView 中重复的照片缩略图渲染逻辑。
 * 默认展示前 maxPreview 张缩略图，超出部分以文件名标签展示。
 * maxPreview 设为 0 表示展开全部。
 *
 * autoFit 模式：开启后通过 ResizeObserver 动态计算容器一行能容纳多少张缩略图，
 * 自动调整实际展示数量。maxPreview 仅作为测量前的初始兜底值。
 */
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { NButton, NIcon } from 'naive-ui'
import { AddOutline, CloseOutline, DownloadOutline, ImageOutline } from '@vicons/ionicons5'
import { getApiBase } from '../config'

// ── 通用照片引用类型 ──
// 与 EvalPhotoItem / ClusterPhoto 兼容：优先使用 uuid，回退到 photo_id
interface PhotoRef {
  photo_id: string
  filename: string
  uuid?: string
  burst_group_id?: string
  burst_count?: number
}

const props = withDefaults(defineProps<{
  photos: PhotoRef[]
  maxPreview?: number
  /** 开启后自动测量容器宽度，计算一行能容纳的缩略图数量 */
  autoFit?: boolean
  editable?: boolean
  emptyText?: string
}>(), {
  maxPreview: 3,
  autoFit: false,
  editable: false,
  emptyText: '无照片',
})

const emit = defineEmits<{
  preview: [uuid: string]
  openGroup: [photo: PhotoRef]
  remove: [photoId: string]
  add: []
}>()

function imageUrl(uuid: string): string {
  return uuid ? `${getApiBase()}/photos/${uuid}/image` : ''
}

/** 获取照片的 UUID（优先 uuid 字段，回退 photo_id） */
function getUuid(p: PhotoRef): string {
  return p.uuid || p.photo_id
}

function downloadOriginal(p: PhotoRef) {
  const uuid = getUuid(p)
  if (!uuid) return
  const anchor = document.createElement('a')
  anchor.href = `${getApiBase()}/photos/${uuid}/image?size=original&download=1`
  anchor.download = p.filename || uuid
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
}

function handlePreview(p: PhotoRef) {
  if (p.burst_group_id) {
    emit('openGroup', p)
    return
  }
  const uuid = getUuid(p)
  if (uuid) emit('preview', uuid)
}

// ── autoFit：动态计算一行能容纳的缩略图数量 ──
const containerRef = ref<HTMLElement>()
const fittedCount = ref(props.maxPreview)

const THUMB_WIDTH = 64
const THUMB_GAP = 8

let observer: ResizeObserver | null = null

function recalcFit() {
  if (!containerRef.value) return
  const w = containerRef.value.clientWidth
  const capacity = Math.max(1, Math.floor((w + THUMB_GAP) / (THUMB_WIDTH + THUMB_GAP)))
  fittedCount.value = Math.min(capacity, props.photos.length)
}

onMounted(() => {
  if (!props.autoFit) return
  if (containerRef.value) {
    observer = new ResizeObserver(recalcFit)
    observer.observe(containerRef.value)
    recalcFit()
  }
})

onUnmounted(() => {
  observer?.disconnect()
})

watch(() => props.photos.length, () => {
  if (props.autoFit) recalcFit()
})

const effectiveMax = computed(() => {
  if (props.maxPreview === 0) return 0 // 展开全部
  if (props.autoFit) return fittedCount.value
  return props.maxPreview
})

const previewPhotos = computed(() => {
  if (effectiveMax.value === 0) return props.photos
  return props.photos.slice(0, effectiveMax.value)
})

const restPhotos = computed(() => {
  if (effectiveMax.value === 0) return []
  return props.photos.slice(effectiveMax.value)
})
</script>

<template>
  <div v-if="!photos || photos.length === 0" class="photo-thumb-empty-state">
    <span class="photo-thumb-empty">{{ emptyText }}</span>
    <NButton v-if="editable" size="tiny" secondary @click="emit('add')">
      <template #icon><NIcon><AddOutline /></NIcon></template>
      增加照片
    </NButton>
  </div>
  <div v-else ref="containerRef" class="photo-thumb-list">
    <div v-if="editable" class="photo-thumb-toolbar">
      <NButton size="tiny" secondary @click="emit('add')">
        <template #icon><NIcon><AddOutline /></NIcon></template>
        增加照片
      </NButton>
    </div>
    <!-- 缩略图行 -->
    <div
      v-if="previewPhotos.length"
      class="photo-thumb-row"
      :class="{ 'photo-thumb-row-expanded': maxPreview === 0 }"
      :style="{ '--photo-thumb-columns': previewPhotos.length }"
    >
      <span
        v-for="p in previewPhotos"
        :key="p.photo_id"
        class="photo-thumb-wrap"
        :style="{ cursor: getUuid(p) ? 'pointer' : 'default' }"
        :title="p.filename"
        @click="handlePreview(p)"
      >
        <img
          v-if="getUuid(p)"
          class="photo-thumb"
          :src="imageUrl(getUuid(p))"
        />
        <NIcon v-else size="24"><ImageOutline /></NIcon>
        <NButton
          v-if="getUuid(p)"
          class="photo-download-button"
          quaternary
          circle
          size="tiny"
          title="下载原图"
          @click.stop="downloadOriginal(p)"
        >
          <template #icon><NIcon><DownloadOutline /></NIcon></template>
        </NButton>
        <NButton
          v-if="editable"
          class="photo-remove-button"
          quaternary
          circle
          size="tiny"
          title="删除照片"
          @click.stop="emit('remove', p.photo_id)"
        >
          <template #icon><NIcon><CloseOutline /></NIcon></template>
        </NButton>
      </span>
    </div>
    <!-- 文件名标签行（超过 maxPreview 的部分） -->
    <div v-if="restPhotos.length" class="photo-name-row">
      <span
        v-for="p in restPhotos"
        :key="p.photo_id"
        class="photo-name-item"
        :class="{ 'photo-name-clickable': !!getUuid(p) }"
      >
        <span @click="handlePreview(p)">{{ p.filename }}</span>
        <NButton
          v-if="editable"
          quaternary
          circle
          size="tiny"
          title="删除照片"
          @click.stop="emit('remove', p.photo_id)"
        >
          <template #icon><NIcon><CloseOutline /></NIcon></template>
        </NButton>
      </span>
    </div>
  </div>
</template>

<style scoped>
.photo-thumb-empty {
  color: var(--n-text-color-3);
  font-size: 13px;
}
.photo-thumb-empty-state {
  display: flex;
  align-items: center;
  gap: 8px;
}
.photo-thumb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.photo-thumb-toolbar {
  display: flex;
  justify-content: flex-end;
}
.photo-thumb-row {
  display: grid;
  grid-template-columns: repeat(var(--photo-thumb-columns), 64px);
  gap: 8px;
  align-items: center;
  justify-content: start;
}
.photo-thumb-row-expanded {
  display: flex;
  flex-wrap: nowrap;
  overflow-x: auto;
}
.photo-name-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.photo-thumb-wrap {
  position: relative;
  display: inline-block;
  min-width: 0;
}
.photo-remove-button {
  position: absolute;
  top: 4px;
  right: 4px;
  background: var(--n-color-modal);
}
.photo-download-button {
  position: absolute;
  top: 4px;
  right: 4px;
  color: var(--n-text-color-1);
  background: var(--n-color-modal);
  opacity: 0;
  transition: opacity 0.15s ease-out;
}
.photo-thumb-wrap:hover .photo-download-button,
.photo-download-button:focus-visible {
  opacity: 1;
}
.photo-thumb-wrap:has(.photo-remove-button) .photo-download-button {
  right: 32px;
}
.photo-thumb-row-expanded .photo-thumb-wrap {
  flex: 0 0 64px;
}
.photo-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--n-border-color);
  transition: transform 0.15s;
}
.photo-thumb:hover {
  transform: scale(1.08);
}
.photo-name-item {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--n-color-target);
  border-radius: 3px;
  background: var(--n-color-embedded);
}
.photo-name-tag:hover {
  text-decoration: underline;
}
.photo-name-clickable {
  cursor: pointer;
}
</style>
