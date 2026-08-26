<script setup lang="ts">
/**
 * PhotoPickOverlay — 全屏选图覆盖层
 *
 * 复用图片管理的完整浏览交互（PhotoListBrowser + usePhotos：三档连拍折叠、
 * 双向滚动、分段导航、搜索筛选），但顶栏改写为「选择照片」场景：
 * 隐藏 VLM/Embed/上传/连拍重算/图文工坊等管理操作，只保留
 * 搜索 / 筛选 / 展示级别 / 分段 / 排序 + 已选计数 + 完成选择 / 取消。
 *
 * 覆盖在视图内容区上（左侧菜单栏露出、可正常点击切换页面，
 * 切走即视为放弃选图），选完把结果写回 photoPickSession 由发起方读取。
 * 见 docs/design/2026-08-26-1-photo-pick-overlay.md。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { NBadge, NButton, NDatePicker, NIcon, NInput, NPopover, NSelect, NSpace, NTooltip } from 'naive-ui'
import { CheckmarkOutline, CloseOutline, InformationCircleOutline, SearchOutline } from '@vicons/ionicons5'
import PhotoListBrowser from './PhotoListBrowser.vue'
import { usePhotos } from '../composables/usePhotos'
import { settings } from '../stores/settings'
import type { BurstViewLevel } from '../types/photo'
import type { SegmentMode } from '../utils/segment'
import { completePickSession, type PickedPhoto } from '../utils/photoPickSession'

const props = defineProps<{
  show: boolean
  /** 预填充的已选照片（打开覆盖层前已选中的照片完整信息） */
  preselected: PickedPhoto[]
}>()

const emit = defineEmits<{
  /** 完成选择：选中照片完整信息 */
  confirm: [photos: PickedPhoto[]]
  /** 取消：选择结果丢弃 */
  cancel: []
}>()

const {
  photos, loading, loadingDown, loadingUp, noMoreDown, noMoreUp, error,
  segments, timelines,
  filterTimeline, filterShotAtStart, filterShotAtEnd, sortOrder, searchFilename,
  relocateTo, relocateToStart, loadDown, loadUp, fetchSegments, fetchTimelines,
  applyFilters, resetFilters,
} = usePhotos()

// ── 选择状态 ──
// selectedIds 存照片 uuid（PhotoCard 的勾选以 uuid 为键），窗口外旧已选单独保留
const selectedIds = ref<Set<string>>(new Set())
// 窗口外/未加载的旧已选（预填充进来的，PhotoListBrowser 看不到，完成时原样带回）
const offlinePicked = ref<PickedPhoto[]>([])
const selectedCount = computed(() => selectedIds.value.size + offlinePicked.value.length)

const visiblePhotoIds = computed(() => {
  const list = settings.burstViewLevel === 'all'
    ? photos.value
    : photos.value.filter((p) => p.burst_group_id === '' || p.burst_cover)
  return list.map((p) => p.id)
})

function toggleSelect(photoId: string) {
  const next = new Set(selectedIds.value)
  if (next.has(photoId)) next.delete(photoId)
  else next.add(photoId)
  selectedIds.value = next
}

function selectIds(ids: string[]) {
  if (!ids.length) return
  const next = new Set(selectedIds.value)
  ids.forEach((id) => next.add(id))
  selectedIds.value = next
}

function selectAllVisible() {
  selectIds(visiblePhotoIds.value)
}

function clearSelection() {
  selectedIds.value = new Set()
  offlinePicked.value = []
}

// 恰好选中 2 张时显示「区间选择」按钮
const showIntervalSelect = computed(() => selectedIds.value.size === 2)

// 区间选择：勾选两张已选照片之间（按拍摄时间排序）的所有照片
function intervalSelect() {
  const ids = visiblePhotoIds.value
  const positions = [...selectedIds.value]
    .map((id) => ids.indexOf(id))
    .filter((i) => i >= 0)
    .sort((a, b) => a - b)
  if (positions.length < 2) return
  selectIds(ids.slice(positions[0], positions[positions.length - 1] + 1))
}

// ── 打开 / 关闭 ──

function initFromPreselected() {
  const byPhotoId = new Map(photos.value.map((p) => [p.id, p]))
  const ids = new Set<string>()
  const offline: PickedPhoto[] = []
  for (const picked of props.preselected) {
    const inWindow = byPhotoId.get(picked.uuid) || photos.value.find((p) => p.filename.replace(/\.[^.]+$/, '') === picked.photo_id)
    if (inWindow) ids.add(inWindow.id)
    else offline.push(picked)
  }
  selectedIds.value = ids
  offlinePicked.value = offline
}

let inited = false
onMounted(() => {
  // 与图片管理一致的首屏加载；已在图片管理页加载过时 usePhotos 单例会复用状态
  if (photos.value.length === 0) {
    applyFilters()
    fetchTimelines()
  }
})

/** 打开覆盖层后照片窗口就绪时做一次预填充。
 *  监听 show + photos 双条件并 immediate：先访问过图片管理时 photos 已加载、
 *  打开覆盖层那一刻 watch(photos) 不会再触发，必须由 show 的变化兜住；
 *  关闭时重置 inited，保证下次打开按新的 preselected 重新预填充。 */
watch(
  () => [props.show, photos.value] as const,
  ([show, list]) => {
    if (!show) {
      inited = false
      return
    }
    if (!inited && list.length > 0) {
      initFromPreselected()
      inited = true
    }
  },
  { immediate: true },
)

function stripExt(name: string): string {
  return name.replace(/\.[^.]+$/, '')
}

function handleConfirm() {
  const picked: PickedPhoto[] = []
  // 窗口内已勾选：按当前窗口顺序（拍摄时间排序）解析完整信息
  const order = new Map(photos.value.map((p, i) => [p.id, i]))
  const ids = [...selectedIds.value].sort(
    (a, b) => (order.get(a) ?? Number.MAX_SAFE_INTEGER) - (order.get(b) ?? Number.MAX_SAFE_INTEGER),
  )
  const pickedIds = new Set<string>()
  for (const id of ids) {
    const p = photos.value.find((photo) => photo.id === id)
    if (!p) continue
    const photoId = stripExt(p.filename)
    if (!pickedIds.has(photoId)) {
      pickedIds.add(photoId)
      picked.push({ photo_id: photoId, filename: photoId, uuid: p.id })
    }
  }
  // 窗口外旧已选追加在末尾（去重：可能已被滚动加载进窗口并勾选）
  for (const old of offlinePicked.value) {
    if (!pickedIds.has(old.photo_id)) {
      pickedIds.add(old.photo_id)
      picked.push({ ...old })
    }
  }
  completePickSession(picked)
  emit('confirm', picked)
}

function handleCancel() {
  emit('cancel')
}

// ── 顶栏工具（沿用图片管理的筛选能力，去掉管理操作） ──

const segmentModeOptions = [
  { label: '按天', value: 'day' },
  { label: '按月', value: 'month' },
  { label: '按活动', value: 'activity' },
]
const viewLevelLabels: Record<BurstViewLevel, string> = {
  all: '全部展开',
  fine: '精细连拍',
  coarse: '模糊连拍',
}

const activeFilterCount = computed(() => {
  let count = 0
  if (searchFilename.value) count++
  if (filterTimeline.value) count++
  if (filterShotAtStart.value || filterShotAtEnd.value) count++
  return count
})

function updateDateStart(value: number | null) {
  filterShotAtStart.value = value ? new Date(value).toISOString() : ''
}

function updateDateEnd(value: number | null) {
  if (!value) {
    filterShotAtEnd.value = ''
    return
  }
  const date = new Date(value)
  date.setHours(23, 59, 59, 999)
  filterShotAtEnd.value = date.toISOString()
}

function handleSegmentModeChange(mode: SegmentMode) {
  settings.segmentMode = mode
  fetchSegments()
}

// 展示级别切换：与图片管理 handleCycleViewLevel 一致，all→fine→coarse 循环
function handleCycleViewLevel() {
  const order = ['all', 'fine', 'coarse'] as const
  settings.burstViewLevel = order[(order.indexOf(settings.burstViewLevel) + 1) % order.length]
  applyFilters()
}

// 时间线选项：usePhotos 全局状态，onMounted 时拉取
const timelineOptionsFromPhotos = computed(() => timelines.value.map((n) => ({ label: n, value: n })))

// 选择模式下 PhotoCard 的状态标记全部置空（不展示 VLM/Embed 处理态）
const emptySet = new Set<string>()

// ── 覆盖层定位：露出左侧菜单（SideMenu 固定 220px 宽，无折叠）──
// 菜单保持可点：切换页面时本组件随路由卸载，选图会话留在 sessionStorage，
// 回到黄金用例页 onMounted 检测残留会话可恢复
const SIDER_WIDTH = 220
const siderWidth = ref(SIDER_WIDTH)
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="pick-overlay" :style="{ left: `${siderWidth}px` }">
      <div class="pick-header">
        <div class="pick-header-left">
          <h3 class="pick-title">选择照片</h3>
          <span class="pick-count">共 {{ selectedCount }} 张</span>
          <NTooltip trigger="hover" placement="top">
            <template #trigger>
              <NButton size="small" @click="handleCycleViewLevel">
                展示：{{ viewLevelLabels[settings.burstViewLevel] }}
              </NButton>
            </template>
            点击切换连拍展示级别（全部展开 / 精细折叠 / 模糊折叠）
          </NTooltip>
          <NSelect
            :value="settings.segmentMode"
            :options="segmentModeOptions"
            size="small"
            style="width: 96px"
            @update:value="handleSegmentModeChange"
          />
          <NButton size="small" @click="() => { sortOrder = sortOrder === 'asc' ? 'desc' : 'asc'; applyFilters() }">
            {{ sortOrder === 'asc' ? '↑ 升序' : '↓ 降序' }}
          </NButton>
          <NPopover trigger="click" placement="bottom-start" :to="false" style="width: 360px">
            <template #trigger>
              <NButton size="small">
                <template #icon>
                  <NBadge :value="activeFilterCount" :offset="[-2, 2]" :show="activeFilterCount > 0">
                    <NIcon><InformationCircleOutline /></NIcon>
                  </NBadge>
                </template>
                筛选
              </NButton>
            </template>
            <div class="filter-panel">
              <div class="filter-group">
                <div class="filter-group-title">搜索</div>
                <NInput v-model:value="searchFilename" placeholder="搜索文件名" size="small" clearable @keyup.enter="applyFilters">
                  <template #prefix><NIcon><SearchOutline /></NIcon></template>
                </NInput>
              </div>
              <div class="filter-group">
                <div class="filter-group-title">筛选</div>
                <div class="filter-group-row">
                  <span class="filter-label">拍摄日期</span>
                  <NDatePicker type="date" clearable placeholder="起始日期" size="small" style="width: 132px" @update:value="updateDateStart" />
                  <span class="filter-label">至</span>
                  <NDatePicker type="date" clearable placeholder="结束日期" size="small" style="width: 132px" @update:value="updateDateEnd" />
                </div>
                <div class="filter-group-row">
                  <span class="filter-label">活动</span>
                  <NSelect v-model:value="filterTimeline" :options="timelineOptionsFromPhotos" placeholder="全部活动" clearable size="small" style="flex: 1" @update:value="applyFilters" />
                </div>
              </div>
              <div class="filter-panel-footer">
                <NButton size="tiny" quaternary @click="resetFilters">重置筛选</NButton>
              </div>
            </div>
          </NPopover>
        </div>
        <NSpace :wrap="false">
          <NButton size="small" @click="selectAllVisible">全选</NButton>
          <NButton size="small" :disabled="selectedCount === 0" @click="clearSelection">清空</NButton>
          <NButton v-if="showIntervalSelect" size="small" @click="intervalSelect">区间选择</NButton>
          <NButton size="small" type="primary" :disabled="selectedCount === 0" @click="handleConfirm">
            <template #icon><NIcon><CheckmarkOutline /></NIcon></template>
            完成选择
          </NButton>
          <NButton size="small" quaternary @click="handleCancel">
            <template #icon><NIcon><CloseOutline /></NIcon></template>
            取消
          </NButton>
        </NSpace>
      </div>
      <div class="pick-body">
        <PhotoListBrowser
          :photos="photos" :loading="loading" :loading-down="loadingDown" :loading-up="loadingUp"
          :no-more-down="noMoreDown" :no-more-up="noMoreUp" :error="error"
          :processing-ids="emptySet" :embed-processing-ids="emptySet" :embedded-ids="emptySet"
          :vlm-batch-running="false" :embed-batch-running="false"
          :view-level="settings.burstViewLevel" :segment-mode="settings.segmentMode" :segments="segments"
          :relocate-to="relocateTo" :load-down="loadDown" :load-up="loadUp"
          :selection-mode="true" :selected-ids="selectedIds"
          @view-detail="() => {}" @trigger-describe="() => {}" @trigger-embed="() => {}"
          @delete-photo="() => {}"
          @open-burst-group="() => {}" @retry="relocateToStart" @back-to-latest="resetFilters"
          @toggle-select="toggleSelect"
        />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.pick-overlay {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  background: var(--n-color, #101014);
  border-left: 1px solid rgba(255, 255, 255, 0.09);
  box-shadow: -12px 0 24px rgba(0, 0, 0, 0.35);
}
.pick-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 24px;
  height: 56px;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.09);
}
.pick-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.pick-title {
  margin: 0;
  font-size: 16px;
  white-space: nowrap;
}
.pick-count {
  font-size: 13px;
  color: var(--n-text-color-3, rgba(255, 255, 255, 0.52));
  white-space: nowrap;
}
.pick-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 24px;
  box-sizing: border-box;
}
.filter-panel,
.filter-group {
  display: flex;
  flex-direction: column;
}
.filter-panel {
  gap: 16px;
  padding: 4px 0;
}
.filter-group {
  gap: 8px;
}
.filter-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-3, rgba(255, 255, 255, 0.52));
}
.filter-group-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-label {
  font-size: 13px;
  color: var(--n-text-color-3, rgba(255, 255, 255, 0.52));
  white-space: nowrap;
}
.filter-panel-footer {
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--n-border-color, rgba(255, 255, 255, 0.09));
  padding-top: 8px;
}
</style>
