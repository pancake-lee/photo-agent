<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { NSpin, NEmpty, NAlert, NButton } from 'naive-ui'
import PhotoCard from './PhotoCard.vue'
import PhotoSegmentDivider from './PhotoSegmentDivider.vue'
import type { PhotoListItem, BurstViewLevel } from '../types/photo'
import { computeDividers, type SegmentMode } from '../utils/segment'

const props = defineProps<{
  photos: PhotoListItem[]
  loading: boolean
  /** 向下加载中（滚动到窗口尾部追加） */
  loadingDown: boolean
  /** 向上加载中（滚动到窗口头部前插） */
  loadingUp: boolean
  /** 窗口已到列表末尾 */
  noMoreDown: boolean
  /** 窗口已到列表开头 */
  noMoreUp: boolean
  error: string | null
  processingIds: Set<string>
  embedProcessingIds: Set<string>
  embeddedIds: Set<string>
  vlmBatchRunning: boolean
  embedBatchRunning: boolean
  /** 连拍展示级别：all 全部展开 / fine 精细折叠 / coarse 模糊折叠 */
  viewLevel: BurstViewLevel
  /** 分段浏览方式：day / month / activity，空串表示不分段 */
  segmentMode: SegmentMode | null
  /** 是否处于选择模式 */
  selectionMode: boolean
  /** 已选中的照片 id 集合 */
  selectedIds: Set<string>
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  deletePhoto: [photoId: string]
  openBurstGroup: [groupId: string, coverId: string]
  dividerEl: [key: string, el: HTMLElement | null]
  loadDown: []
  loadUp: []
  retry: []
  toggleSelect: [photoId: string]
}>()

// 滚动容器：由父级 PhotoManagement 通过 provide 注入（.grid-main 有界滚动容器）。
// 观察器以它为 root，保证 rootMargin 相对的是照片列表自身视口，而非浏览器视口。
const scrollRoot = inject<Ref<HTMLElement | null>>('photoGridScrollRoot', ref(null))

// 分割线 DOM 挂载/卸载上报（父级用于导航高亮跟随与锚点跳转）
function onDividerMounted(key: string, el: HTMLElement) {
  emit('dividerEl', key, el)
}
function onDividerUnmounted(key: string) {
  emit('dividerEl', key, null)
}

/** 折叠级别下网格只渲染封面照片（burst_cover=true）与非组内照片；全部展开时渲染全部 */
function visiblePhotos(): PhotoListItem[] {
  if (props.viewLevel === 'all') return props.photos
  return props.photos.filter((p) => p.burst_group_id === '' || p.burst_cover)
}

// ── 分段渲染 ──
// 流元素 = 照片或分割线（位于其分段首张照片之前）。
// 分割线基于实际渲染照片（连拍折叠后）计算，组折叠不影响分割线正确性。
type FlowItem =
  | { kind: 'photo'; itemKey: string; photo: PhotoListItem; photoIndex: number }
  | { kind: 'divider'; itemKey: string; segKey: string; label: string; subLabel?: string; count: number; photoIndex: number }

const flowItems = computed<FlowItem[]>(() => {
  const visible = visiblePhotos()
  if (!props.segmentMode) {
    return visible.map((photo, i) => ({ kind: 'photo', itemKey: photo.id, photo, photoIndex: i }))
  }
  const dividers = computeDividers(visible, props.segmentMode)
  const dividerByIndex = new Map<number, (typeof dividers)[number]>()
  for (const d of dividers) {
    // 同一分段键交错出现多个区间时，只保留首个区间的分割线
    if (!dividerByIndex.has(d.segIndex)) dividerByIndex.set(d.segIndex, d)
  }

  const items: FlowItem[] = []
  for (let i = 0; i < visible.length; i++) {
    const d = dividerByIndex.get(i)
    if (d) {
      items.push({
        kind: 'divider',
        itemKey: `d-${d.key}-${i}`,
        segKey: d.key,
        label: d.label,
        subLabel: d.subLabel,
        count: d.count,
        photoIndex: i,
      })
    }
    items.push({ kind: 'photo', itemKey: visible[i].id, photo: visible[i], photoIndex: i })
  }
  return items
})

// ── 双向滚动加载 ──
// 直接根据有界滚动容器的位置判断，避免 IntersectionObserver 在加载期间
// 丢失相交事件，或在哨兵持续可见时重复触发。
// 阈值放宽到 1200px（约 1.5 屏）：预留更大缓冲，让下一页在用户接近边界前
// 就完成加载，避免看到空缺后再补载引起的位移跳动。
const LOAD_THRESHOLD_PX = 1200
let observedScrollRoot: HTMLElement | null = null

function maybeLoad() {
  const root = scrollRoot.value
  if (!root || props.loading || props.loadingUp || props.loadingDown || props.error) return

  // 上下两端独立判定：窗口已到列表开头（noMoreUp）时不能提前 return，
  // 否则内容较短、scrollTop 始终小于阈值的情况下向下加载永远不会触发
  if (!props.noMoreUp && root.scrollTop <= LOAD_THRESHOLD_PX) {
    emit('loadUp')
    return
  }

  const distanceToBottom = root.scrollHeight - root.scrollTop - root.clientHeight
  if (!props.noMoreDown && distanceToBottom <= LOAD_THRESHOLD_PX) emit('loadDown')
}

function bindScrollRoot() {
  if (observedScrollRoot === scrollRoot.value) return
  observedScrollRoot?.removeEventListener('scroll', maybeLoad)
  observedScrollRoot = scrollRoot.value
  observedScrollRoot?.addEventListener('scroll', maybeLoad, { passive: true })
  maybeLoad()
}

watch(() => scrollRoot.value, bindScrollRoot, { flush: 'post' })

// 一页 100 张在连拍折叠下可能只渲染出十几张封面，视口填不满就再也不会产生
// 滚动事件。每次加载结束后主动复检一次，直到视口被填满或触达列表两端。
watch(
  () => [props.photos, props.loading, props.loadingDown, props.loadingUp],
  () => {
    if (props.loading || props.loadingDown || props.loadingUp) return
    nextTick(maybeLoad)
  },
  { flush: 'post' },
)

onMounted(bindScrollRoot)
onBeforeUnmount(() => observedScrollRoot?.removeEventListener('scroll', maybeLoad))
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

  <!-- 照片流 -->
  <div v-else class="photo-list">
    <!-- 顶部加载状态 -->
    <div class="load-sentinel-top">
      <NSpin v-if="loadingUp" size="small" />
    </div>

    <!-- 照片网格：CSS Grid，分割线跨全部列 -->
    <div class="photo-grid">
      <template v-for="item in flowItems" :key="item.itemKey">
        <PhotoSegmentDivider
          v-if="item.kind === 'divider'"
          :seg-key="item.segKey"
          :label="item.label"
          :sub-label="item.subLabel"
          :count="item.count"
          @mounted="onDividerMounted(item.segKey, $event)"
          @unmounted="onDividerUnmounted(item.segKey)"
        />
        <PhotoCard
          v-else
          :photo="item.photo"
          :view-level="viewLevel"
          :processing="processingIds.has(item.photo.id)"
          :embed-processing="embedProcessingIds.has(item.photo.id)"
          :is-embedded="embeddedIds.has(item.photo.id)"
          :vlm-batch-running="vlmBatchRunning"
          :embed-batch-running="embedBatchRunning"
          :selection-mode="selectionMode"
          :selected="selectedIds.has(item.photo.id)"
          @view-detail="(id) => $emit('viewDetail', id)"
          @trigger-describe="(id) => $emit('triggerDescribe', id)"
          @trigger-embed="(id) => $emit('triggerEmbed', id)"
          @delete-photo="(id) => $emit('deletePhoto', id)"
          @open-burst-group="(gid, coverId) => $emit('openBurstGroup', gid, coverId)"
          @toggle-select="(id) => $emit('toggleSelect', id)"
        />
      </template>
    </div>

    <!-- 底部加载状态 + 提示 -->
    <div v-show="!noMoreDown || loadingDown" class="load-more">
      <NSpin v-if="loadingDown" size="small" />
      <span v-else class="load-more-hint">滚动加载更多…</span>
    </div>
  </div>
</template>

<style scoped>
.grid-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}
.photo-list {
  padding-bottom: 8px;
}
.load-sentinel-top {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
}
.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.load-more {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 0;
  min-height: 48px;
}
.load-more-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
}
</style>
