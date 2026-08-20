<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NGrid, NGi, NSpin, NEmpty, NAlert, NButton } from 'naive-ui'
import PhotoCard from './PhotoCard.vue'
import PhotoSegmentDivider from './PhotoSegmentDivider.vue'
import type { PhotoListItem, BurstViewLevel } from '../types/photo'
import { computeDividers, type SegmentMode } from '../utils/segment'

const props = defineProps<{
  photos: PhotoListItem[]
  loading: boolean
  loadingMore: boolean
  noMore: boolean
  error: string | null
  processingIds: Set<string>
  embeddedIds: Set<string>
  /** 连拍展示级别：all 全部展开 / fine 精细折叠 / coarse 模糊折叠 */
  viewLevel: BurstViewLevel
  /** 分段浏览方式：day / month / activity，空串表示不分段 */
  segmentMode: SegmentMode | null
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  deletePhoto: [photoId: string]
  openBurstGroup: [groupId: string, coverId: string]
  dividerEl: [key: string, el: unknown]
  loadMore: []
  retry: []
}>()

// 分割线 DOM 挂载/卸载上报（父级用于导航高亮跟随与锚点跳转）
function onDividerMounted(key: string, el: unknown) {
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
  | { kind: 'photo'; photo: PhotoListItem; photoIndex: number }
  | { kind: 'divider'; key: string; label: string; subLabel?: string; count: number; photoIndex: number }

const flowItems = computed<FlowItem[]>(() => {
  const visible = visiblePhotos()
  if (!props.segmentMode) {
    return visible.map((photo, i) => ({ kind: 'photo', photo, photoIndex: i }) as FlowItem)
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
      items.push({ kind: 'divider', key: d.key, label: d.label, subLabel: d.subLabel, count: d.count, photoIndex: i })
    }
    items.push({ kind: 'photo', photo: visible[i], photoIndex: i })
  }
  return items
})

// ── 触底加载 ──
// 监听哨兵元素进入视口（根 = 浏览器视口），触发追加下一页。
// 哨兵随照片网格渲染（列表为空/出错时不渲染），观察时机跟随 DOM 挂载。
const loadMoreSentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

function ensureObserver() {
  if (!observer) {
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          if (!props.loading && !props.loadingMore && !props.noMore && !props.error) {
            emit('loadMore')
          }
        }
      },
      { rootMargin: '600px 0px' }, // 提前 600px 预加载
    )
  }
}

watch(loadMoreSentinel, (el, oldEl) => {
  ensureObserver()
  if (oldEl) observer?.unobserve(oldEl)
  if (el) observer?.observe(el)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})
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
      <template v-for="item in flowItems" :key="item.kind === 'photo' ? item.photo.id : `d-${item.key}-${item.photoIndex}`">
        <PhotoSegmentDivider
          v-if="item.kind === 'divider'"
          :seg-key="item.key"
          :label="item.label"
          :sub-label="item.subLabel"
          :count="item.count"
          @vue:mounted="onDividerMounted(item.key, $event.el)"
          @vue:unmounted="onDividerUnmounted(item.key)"
        />
        <NGi
          v-else
          :span="1"
          :xs="2"
          :s="1"
          :m="1"
          :l="1"
        >
          <PhotoCard
            :photo="item.photo"
            :view-level="viewLevel"
            :processing="processingIds.has(item.photo.id)"
            :is-embedded="embeddedIds.has(item.photo.id)"
            @view-detail="(id) => $emit('viewDetail', id)"
            @trigger-describe="(id) => $emit('triggerDescribe', id)"
            @trigger-embed="(id) => $emit('triggerEmbed', id)"
            @delete-photo="(id) => $emit('deletePhoto', id)"
            @open-burst-group="(gid, coverId) => $emit('openBurstGroup', gid, coverId)"
          />
        </NGi>
      </template>
    </NGrid>

    <!-- 触底加载哨兵 + 状态提示 -->
    <div v-show="!noMore || loadingMore" class="load-more" ref="loadMoreSentinel">
      <NSpin v-if="loadingMore" size="small" />
      <span v-else class="load-more-hint">滚动加载更多…</span>
    </div>
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
