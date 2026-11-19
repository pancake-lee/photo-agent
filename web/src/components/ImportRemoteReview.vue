<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NEmpty, NModal, NPagination, NSelect, NSpace, NTag, useMessage } from 'naive-ui'
import { editImportReview, getImportReview, listImportReviews, reviewImageURL } from '../utils/importReview'
import type { ReviewBatch, ReviewChange, ReviewEntry, ReviewSummary } from '../utils/importReview'
import type { ImportDecision } from '../utils/importBatch'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const batches = ref<ReviewSummary[]>([])
const batch = ref<ReviewBatch>()
const busy = ref(false)
const error = ref('')
const filter = ref('all')
const page = ref(1)
const previewID = ref('')
const imageFailed = ref(false)
const originalReady = ref(false)
const undo = ref<ReviewChange[]>([])
const refreshedAt = ref('')
const pageSize = 36
const options = computed(() => batches.value.map((item) => ({
  value: item.batch_id, label: `${item.name} · ${item.count} 张${item.state === 'locked' ? ' · 已结束选片' : ''}`,
})))
const filters = [{ label: '全部留存', value: 'all' }, { label: '收藏', value: 'favorite' }, { label: '已标记删除', value: 'discarded' }]
const entries = computed(() => (batch.value?.entries ?? []).filter((entry) =>
  filter.value === 'all' ? entry.decision !== 'discarded' : entry.decision === filter.value)
  .sort((a, b) => (a.shot_at ?? '').localeCompare(b.shot_at ?? '')))
const shown = computed(() => entries.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const preview = computed(() => batch.value?.entries.find((entry) => entry.id === previewID.value))
const index = computed(() => entries.value.findIndex((entry) => entry.id === previewID.value))
const editable = computed(() => !!batch.value && batch.value.state === 'review' && !busy.value)
const favoriteCount = computed(() => batch.value?.entries.filter((entry) => entry.decision === 'favorite').length ?? 0)
const deletedCount = computed(() => batch.value?.entries.filter((entry) => entry.decision === 'discarded').length ?? 0)
watch(filter, () => { page.value = 1 })
watch(previewID, () => { imageFailed.value = false; originalReady.value = false })
watch(entries, (list, previous) => {
  page.value = Math.min(page.value, Math.max(1, Math.ceil(list.length / pageSize)))
  if (!previewID.value || list.some((entry) => entry.id === previewID.value)) return
  const oldIndex = previous.findIndex((entry) => entry.id === previewID.value)
  previewID.value = list[Math.min(Math.max(0, oldIndex), list.length - 1)]?.id ?? ''
})

async function run(operation: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await operation() } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    message.error(error.value)
  } finally { busy.value = false }
}
function accept(loaded: ReviewBatch) {
  batch.value = loaded
  refreshedAt.value = new Date().toLocaleTimeString()
}
function refresh() {
  return run(async () => {
    const id = batch.value?.batch_id ?? (typeof route.query.batch === 'string' ? route.query.batch : '')
    batches.value = await listImportReviews()
    if (id) accept(await getImportReview(id))
  })
}
function selectBatch(id: string) {
  return run(async () => {
    const loaded = await getImportReview(id)
    previewID.value = ''
    filter.value = 'all'
    page.value = 1
    undo.value = []
    accept(loaded)
    await router.replace({ query: { ...route.query, batch: id } })
  })
}
function decide(entry: ReviewEntry, decision: ImportDecision) {
  if (!editable.value) return
  return run(async () => {
    if (!batch.value) return
    const previous = [{ id: entry.id, decision: entry.decision }]
    const updated = await editImportReview(batch.value.batch_id, [{ id: entry.id, decision }])
    undo.value = previous
    accept(updated)
    message.success('已保存')
  })
}
function undoDecision() {
  if (!editable.value || !undo.value.length) return
  return run(async () => {
    if (!batch.value) return
    const updated = await editImportReview(batch.value.batch_id, undo.value)
    undo.value = []
    accept(updated)
    message.success('已撤销')
  })
}
function navigate(direction: -1 | 1) {
  const next = entries.value[index.value + direction]
  if (next) previewID.value = next.id
}
let touch: { x: number; y: number } | undefined
function touchStart(event: TouchEvent) {
  const point = event.touches[0]
  touch = point ? { x: point.clientX, y: point.clientY } : undefined
}
function touchEnd(event: TouchEvent) {
  const point = event.changedTouches[0]
  if (point && touch) {
    const dx = point.clientX - touch.x
    if (Math.abs(dx) >= 60 && Math.abs(dx) > Math.abs(point.clientY - touch.y) * 1.5) navigate(dx < 0 ? 1 : -1)
  }
  touch = undefined
}
function key(event: KeyboardEvent) {
  if (!preview.value || event.defaultPrevented || event.repeat || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return
  if (event.target instanceof HTMLElement && (event.target.isContentEditable || event.target.matches('input, textarea, select'))) return
  const entry = preview.value
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    navigate(event.key === 'ArrowLeft' ? -1 : 1)
  } else if (event.key.toLowerCase() === 'l' && editable.value) {
    event.preventDefault()
    void decide(entry, entry.decision === 'favorite' ? 'kept' : 'favorite')
  } else if (['d', 'Delete'].includes(event.key) && editable.value) {
    event.preventDefault()
    void decide(entry, 'discarded')
  } else if (event.key.toLowerCase() === 'z') {
    event.preventDefault()
    void undoDecision()
  } else if (event.key.toLowerCase() === 'r' && entry.decision === 'discarded') {
    event.preventDefault()
    void decide(entry, 'kept')
  }
}
onMounted(() => { void refresh(); window.addEventListener('keydown', key) })
onUnmounted(() => window.removeEventListener('keydown', key))
</script>

<template>
  <div class="remote-review">
    <NCard title="接续选片">
      <NSpace align="center" :size="8">
        <NSelect :value="batch?.batch_id" :options="options" :disabled="busy" placeholder="选择 PC 已开启的批次"
          aria-label="待选片批次" class="batch-select" @update:value="selectBatch" />
        <NButton :loading="busy" :disabled="busy" @click="refresh">刷新选片</NButton>
      </NSpace>
      <p class="hint">在 PC 准备好照片后点击「手机接续选片」。这里的删除只标记淘汰，入库与回收原片回到 PC 完成。</p>
      <NAlert v-if="error" type="error" class="review-message">{{ error }}</NAlert>
      <NEmpty v-if="!batch && !busy && !error" description="暂无选片批次，请先在 PC 开启手机选片" />
      <template v-if="batch">
        <NAlert v-if="batch.state !== 'review'" type="info" class="review-message">PC 已结束选片。可以浏览，返回 PC 的选片步骤后才能继续修改。</NAlert>
        <p aria-live="polite">{{ batch.entries.length }} 张 · {{ favoriteCount }} 张收藏 · {{ deletedCount }} 张标记删除</p>
        <NSpace align="center" :size="8">
          <NSelect v-model:value="filter" :options="filters" aria-label="选片范围" style="width: 156px" />
          <NButton :disabled="!editable || !undo.length" @click="undoDecision">撤销上一步</NButton>
        </NSpace>
        <p class="hint">已同步 {{ refreshedAt }} · 决定即时保存，刷新读取另一端改动，同一张以最后提交为准。</p>
        <NEmpty v-if="!shown.length" description="此范围暂无照片" />
        <ul v-else class="remote-grid">
          <li v-for="entry in shown" :key="entry.id">
            <button class="photo-open" :aria-label="`查看 ${entry.name}`" @click="previewID = entry.id">
              <img :src="reviewImageURL(batch.batch_id, entry, true)" :alt="entry.name" loading="lazy" />
              <span class="photo-name">{{ entry.name }}</span>
              <NTag v-if="entry.decision === 'favorite'" type="warning" size="small" class="photo-flag">已收藏</NTag>
              <NTag v-else-if="entry.decision === 'discarded'" type="error" size="small" class="photo-flag">标记删除</NTag>
            </button>
          </li>
        </ul>
        <NPagination v-if="entries.length > pageSize" v-model:page="page" :item-count="entries.length" :page-size="pageSize" :page-slot="5" class="pagination" />
      </template>
    </NCard>
    <NModal :show="!!preview" preset="card" :title="preview?.name" class="remote-modal"
      @update:show="(show) => { if (!show) previewID = '' }">
      <template v-if="preview && batch">
        <div class="remote-image" @touchstart.passive="touchStart" @touchend.passive="touchEnd">
          <img :key="`thumb-${preview.id}`" :src="reviewImageURL(batch.batch_id, preview, true)" :alt="preview.name" />
          <img v-if="!imageFailed" :key="`original-${preview.id}`" :src="reviewImageURL(batch.batch_id, preview)" alt=""
            class="original" :class="{ ready: originalReady }" @load="originalReady = true" @error="imageFailed = true" />
          <NButton v-else class="image-retry" @click="imageFailed = false">原图加载失败，重试</NButton>
        </div>
        <p class="position" aria-live="polite">{{ index + 1 }} / {{ entries.length }} · 左右滑动切换<span v-if="preview.decision === 'favorite'"> · 已收藏</span><span v-if="preview.decision === 'discarded'"> · 标记删除</span></p>
        <div class="remote-actions">
          <NButton :disabled="index <= 0" @click="navigate(-1)">上一张</NButton>
          <NButton :disabled="index >= entries.length - 1" @click="navigate(1)">下一张</NButton>
          <NButton :type="preview.decision === 'favorite' ? 'warning' : 'default'" :disabled="!editable"
            @click="decide(preview, preview.decision === 'favorite' ? 'kept' : 'favorite')">收藏 (L)</NButton>
          <NButton secondary type="error" :disabled="!editable || preview.decision === 'discarded'" @click="decide(preview, 'discarded')">标记删除 (D)</NButton>
          <NButton :disabled="!editable || preview.decision !== 'discarded'" @click="decide(preview, 'kept')">恢复留存 (R)</NButton>
          <NButton :disabled="!editable || !undo.length" @click="undoDecision">撤销 (Z)</NButton>
          <NButton :loading="busy" :disabled="busy" @click="refresh">刷新选片</NButton>
        </div>
        <p v-if="batch.state !== 'review'" class="hint">PC 已结束选片，当前只可浏览。</p>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.remote-review { max-width: 1400px; margin: 0 auto; }
.batch-select { width: min(360px, 68vw); }
.hint { color: var(--n-text-color-3); font-size: 13px; line-height: 1.6; }
.review-message { margin: 16px 0; }
.remote-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; padding: 0; list-style: none; }
.photo-open { position: relative; display: flex; flex-direction: column; width: 100%; padding: 0; border: 1px solid var(--n-border-color); border-radius: 8px; overflow: hidden; background: transparent; color: inherit; cursor: pointer; }
.photo-open:hover, .photo-open:focus-visible { border-color: var(--n-color-target); outline: 2px solid currentColor; }
.photo-open img { width: 100%; aspect-ratio: 4 / 3; object-fit: contain; background: #171717; }
.photo-name { padding: 8px; max-width: 100%; box-sizing: border-box; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.photo-flag { position: absolute; top: 8px; left: 8px; }
.pagination { justify-content: center; margin-top: 16px; }
.remote-modal { width: min(960px, 96vw); }
.remote-image { position: relative; height: min(56dvh, 640px); display: flex; align-items: center; justify-content: center; min-height: 160px; background: #171717; touch-action: pan-y pinch-zoom; }
.remote-image img { max-width: 100%; height: 100%; object-fit: contain; }
.remote-image .original { position: absolute; inset: 0; width: 100%; opacity: 0; }
.remote-image .original.ready { opacity: 1; }
.image-retry { position: absolute; bottom: 8px; }
.position { margin: 8px 0; text-align: center; font-size: 13px; }
.remote-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; padding-bottom: env(safe-area-inset-bottom, 0px); }
.remote-actions :deep(.n-button) { min-height: 44px; }
@media (max-width: 600px) {
  .remote-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .remote-image { height: 48dvh; }
  .remote-review :deep(.n-card__content) { padding-left: 12px; padding-right: 12px; }
}
</style>
