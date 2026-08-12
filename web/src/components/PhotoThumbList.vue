<script setup lang="ts">
/**
 * PhotoThumbList — 照片缩略图列表组件
 *
 * 统一 GoldenQueryManagement / ClusterView 中重复的照片缩略图渲染逻辑。
 * 默认展示前 maxPreview 张缩略图，超出部分以文件名标签展示。
 * maxPreview 设为 0 表示展开全部。
 *
 * autoFit 模式：开启后通过 ResizeObserver 动态计算容器一行能容纳多少张缩略图，
 * 自动调整实际展示数量。maxPreview 仅作为测量前的初始兜底值。
 */
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { NIcon } from 'naive-ui'
import { ImageOutline } from '@vicons/ionicons5'
import { getApiBase } from '../config'

// ── 通用照片引用类型 ──
// 与 EvalPhotoItem / ClusterPhoto 兼容：优先使用 uuid，回退到 photo_id
interface PhotoRef {
  photo_id: string
  filename: string
  uuid?: string
}

const props = withDefaults(defineProps<{
  photos: PhotoRef[]
  maxPreview?: number
  /** 开启后自动测量容器宽度，计算一行能容纳的缩略图数量 */
  autoFit?: boolean
  emptyText?: string
}>(), {
  maxPreview: 3,
  autoFit: false,
  emptyText: '无照片',
})

const emit = defineEmits<{
  preview: [uuid: string]
}>()

function imageUrl(uuid: string): string {
  return uuid ? `${getApiBase()}/photos/${uuid}/image` : ''
}

/** 获取照片的 UUID（优先 uuid 字段，回退 photo_id） */
function getUuid(p: PhotoRef): string {
  return p.uuid || p.photo_id
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
  fittedCount.value = Math.max(1, Math.floor((w + THUMB_GAP) / (THUMB_WIDTH + THUMB_GAP)) - 1)
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
  <span
    v-if="!photos || photos.length === 0"
    class="photo-thumb-empty"
  >{{ emptyText }}</span>
  <div v-else ref="containerRef" class="photo-thumb-list">
    <!-- 缩略图行 -->
    <div v-if="previewPhotos.length" class="photo-thumb-row">
      <span
        v-for="p in previewPhotos"
        :key="p.photo_id"
        class="photo-thumb-wrap"
        :style="{ cursor: getUuid(p) ? 'pointer' : 'default' }"
        :title="p.filename"
        @click="getUuid(p) && emit('preview', getUuid(p))"
      >
        <img
          v-if="getUuid(p)"
          class="photo-thumb"
          :src="imageUrl(getUuid(p))"
        />
        <NIcon v-else size="24"><ImageOutline /></NIcon>
      </span>
    </div>
    <!-- 文件名标签行（超过 maxPreview 的部分） -->
    <div v-if="restPhotos.length" class="photo-name-row">
      <span
        v-for="p in restPhotos"
        :key="p.photo_id"
        class="photo-name-tag"
        :class="{ 'photo-name-clickable': !!getUuid(p) }"
        @click="getUuid(p) && emit('preview', getUuid(p))"
      >{{ p.filename }}</span>
    </div>
  </div>
</template>

<style scoped>
.photo-thumb-empty {
  color: var(--n-text-color-3);
  font-size: 13px;
}
.photo-thumb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.photo-thumb-row {
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  align-items: center;
  overflow-x: auto;
}
.photo-name-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.photo-thumb-wrap {
  display: inline-block;
  flex-shrink: 0;
}
.photo-thumb {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--n-border-color);
  transition: transform 0.15s;
}
.photo-thumb:hover {
  transform: scale(1.08);
}
.photo-name-tag {
  display: inline-block;
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
