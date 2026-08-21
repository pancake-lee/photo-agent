<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, provide, ref } from 'vue'
import PhotoGrid from './PhotoGrid.vue'
import PhotoSegmentNav, { type NavItem } from './PhotoSegmentNav.vue'
import type { BurstViewLevel, PhotoListItem } from '../types/photo'
import type { SegmentMode } from '../utils/segment'
import type { PhotoSegmentNavItem } from '../composables/usePhotos'
import { localSegmentKeyOf } from '../utils/segment'

const props = defineProps<{
  photos: PhotoListItem[]
  loading: boolean
  loadingDown: boolean
  loadingUp: boolean
  noMoreDown: boolean
  noMoreUp: boolean
  error: string | null
  processingIds: Set<string>
  embeddedIds: Set<string>
  viewLevel: BurstViewLevel
  segmentMode: SegmentMode
  segments: PhotoSegmentNavItem[]
  relocateTo: (offset: number) => Promise<void>
  loadDown: () => Promise<number>
  loadUp: () => Promise<number>
}>()

const emit = defineEmits<{
  viewDetail: [photoId: string]
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  deletePhoto: [photoId: string]
  openBurstGroup: [groupId: string, coverId: string]
  retry: []
  backToLatest: []
}>()

const navItems = computed<NavItem[]>(() => props.segments.map(({ key, label, count }) => ({ key, label, count })))
const activeNavKey = ref('')
const dividerEls = new Map<string, HTMLElement>()
const gridScrollRef = ref<HTMLElement | null>(null)
const NAV_TOP_THRESHOLD_PX = 80

provide('photoGridScrollRoot', gridScrollRef)

function setDividerEl(key: string, el: HTMLElement | null) {
  if (el) dividerEls.set(key, el)
  else dividerEls.delete(key)
}

function updateActiveNav() {
  if (dividerEls.size === 0) return
  const rootTop = gridScrollRef.value?.getBoundingClientRect().top ?? 0
  let current = ''
  let currentTop = -Infinity
  let firstKey = ''
  let firstTop = Infinity
  for (const [key, el] of dividerEls) {
    const top = el.getBoundingClientRect().top - rootTop
    if (top <= NAV_TOP_THRESHOLD_PX && top > currentTop) {
      current = key
      currentTop = top
    }
    if (top < firstTop) {
      firstKey = key
      firstTop = top
    }
  }
  activeNavKey.value = props.segmentMode === 'activity' ? (current || firstKey) : (current || firstKey).slice(0, 7)
}

function findSegmentFirstPhotoEl(key: string): HTMLElement | null {
  const root = gridScrollRef.value
  if (!root) return null
  const photosById = new Map(props.photos.map((photo) => [photo.id, photo]))
  for (const el of root.querySelectorAll<HTMLElement>('[data-photo-id]')) {
    const photo = photosById.get(el.dataset.photoId ?? '')
    if (!photo) continue
    const photoKey = localSegmentKeyOf(photo, props.segmentMode)
    if (photoKey === key || (props.segmentMode !== 'activity' && photoKey.startsWith(key))) return el
  }
  return null
}

async function handleNavJump(key: string) {
  const segment = props.segments.find((item) => item.key === key)
  if (!segment) return
  await props.relocateTo(segment.offset)
  await nextTick()
  await nextTick()
  const root = gridScrollRef.value
  const anchor = findSegmentFirstPhotoEl(key)
  if (root) root.scrollTop = anchor ? anchor.offsetTop - NAV_TOP_THRESHOLD_PX : 0
  updateActiveNav()
}

function contentOffsetOf(el: HTMLElement, root: HTMLElement): number {
  return el.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop
}

async function handleLoadUp() {
  const root = gridScrollRef.value
  const anchor = root?.querySelector<HTMLElement>('[data-photo-id]')
  if (!root || !anchor || props.loading || props.loadingUp || props.loadingDown) return
  const before = contentOffsetOf(anchor, root)
  if (!await props.loadUp()) return
  await nextTick()
  root.scrollTop += contentOffsetOf(anchor, root) - before
}

async function handleLoadDown() {
  const root = gridScrollRef.value
  const photoEls = root?.querySelectorAll<HTMLElement>('[data-photo-id]')
  const anchor = photoEls?.length ? photoEls[photoEls.length - 1] : null
  if (!root || !anchor || props.loading || props.loadingUp || props.loadingDown) return
  const before = contentOffsetOf(anchor, root)
  if (!await props.loadDown()) return
  await nextTick()
  root.scrollTop += contentOffsetOf(anchor, root) - before
}

onMounted(() => gridScrollRef.value?.addEventListener('scroll', updateActiveNav, { passive: true }))
onUnmounted(() => gridScrollRef.value?.removeEventListener('scroll', updateActiveNav))
</script>

<template>
  <div class="grid-with-nav">
    <div ref="gridScrollRef" class="grid-main">
      <PhotoGrid
        :photos="photos" :loading="loading" :loading-down="loadingDown" :loading-up="loadingUp"
        :no-more-down="noMoreDown" :no-more-up="noMoreUp" :error="error"
        :processing-ids="processingIds" :embedded-ids="embeddedIds" :view-level="viewLevel" :segment-mode="segmentMode"
        @view-detail="$emit('viewDetail', $event)" @trigger-describe="$emit('triggerDescribe', $event)"
        @trigger-embed="$emit('triggerEmbed', $event)" @delete-photo="$emit('deletePhoto', $event)"
        @open-burst-group="(groupId, coverId) => $emit('openBurstGroup', groupId, coverId)"
        @divider-el="setDividerEl" @load-down="handleLoadDown" @load-up="handleLoadUp" @retry="$emit('retry')"
      />
    </div>
    <PhotoSegmentNav :items="navItems" :active-key="activeNavKey" @jump="handleNavJump" @back-to-latest="$emit('backToLatest')" />
  </div>
</template>

<style scoped>
.grid-with-nav { display: flex; align-items: stretch; flex: 1; min-height: 0; gap: 16px; }
.grid-main { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; overflow-anchor: none; }
</style>
