<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  NBadge,
  NButton,
  NDatePicker,
  NIcon,
  NInput,
  NPopover,
  NSelect,
  NSpace,
  NTag,
  NTooltip,
} from 'naive-ui'
import {
  CheckboxOutline,
  CloudUploadOutline,
  CloseOutline,
  GridOutline,
  ImagesOutline,
  InformationCircleOutline,
  LayersOutline,
  PlayOutline,
  SearchOutline,
} from '@vicons/ionicons5'
import type { BurstViewLevel, EmbedStats, PhotoStats } from '../types/photo'
import type { SegmentMode } from '../utils/segment'

const props = defineProps<{
  total: number
  stats: PhotoStats | null
  embedStats: EmbedStats | null
  timelines: string[]
  burstViewLevel: BurstViewLevel
  segmentMode: SegmentMode
  sortOrder: string
  vlmRunning: boolean
  vlmCompleted: number
  vlmTotal: number
  embedRunning: boolean
  embedCompleted: number
  embedTotal: number
  burstRunning: boolean
  burstProcessed: number
  burstTotal: number
  selectionMode: boolean
  selectedCount: number
  showIntervalSelect: boolean
}>()

const searchFilename = defineModel<string>('searchFilename', { required: true })
const filterTimeline = defineModel<string>('filterTimeline', { required: true })
const filterShotAtStart = defineModel<string>('filterShotAtStart', { required: true })
const filterShotAtEnd = defineModel<string>('filterShotAtEnd', { required: true })

const emit = defineEmits<{
  applyFilters: []
  resetFilters: []
  cycleViewLevel: []
  changeSegmentMode: [mode: SegmentMode]
  toggleSortOrder: []
  startVlm: []
  stopVlm: []
  startEmbed: []
  stopEmbed: []
  rebuildBurst: []
  upload: []
  toggleSelectionMode: []
  selectAll: []
  clearSelection: []
  intervalSelect: []
  goToPostStudio: []
}>()

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
const timelineOptions = computed(() => [
  ...props.timelines.map((timeline) => ({ label: timeline, value: timeline })),
  { label: '未分类', value: 'none' },
])
const activeFilterCount = computed(() => {
  let count = 0
  if (searchFilename.value) count++
  if (filterTimeline.value) count++
  if (filterShotAtStart.value || filterShotAtEnd.value) count++
  return count
})
const pendingEmbedCount = computed(() =>
  Math.max(0, (props.stats?.with_description ?? 0) - (props.embedStats?.with_embedding ?? 0)),
)

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

const COLLAPSE_THRESHOLD = 1000
const toolbarRef = ref<HTMLElement | null>(null)
const collapsed = ref(false)
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (!toolbarRef.value) return
  resizeObserver = new ResizeObserver((entries) => {
    collapsed.value = entries[0].contentRect.width < COLLAPSE_THRESHOLD
  })
  resizeObserver.observe(toolbarRef.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div ref="toolbarRef" class="toolbar">
    <div class="toolbar-left">
      <h3 class="toolbar-title">图片管理</h3>
      <!-- 内联模式：宽度充足 -->
      <div v-show="!collapsed" class="toolbar-inline">
        <span class="total-count">共 {{ stats?.total ?? total }} 张</span>
        <NTooltip trigger="hover" placement="top">
          <template #trigger>
            <NButton size="small" @click="$emit('cycleViewLevel')">
              展示：{{ viewLevelLabels[burstViewLevel] }}
            </NButton>
          </template>
          点击切换连拍展示级别（全部展开 / 精细折叠 / 模糊折叠）
        </NTooltip>
        <NSelect :value="segmentMode" :options="segmentModeOptions" size="small" style="width: 96px" @update:value="$emit('changeSegmentMode', $event as SegmentMode)" />
        <NButton size="small" @click="$emit('toggleSortOrder')">
          {{ sortOrder === 'asc' ? '↑ 升序' : '↓ 降序' }}
        </NButton>
        <NPopover trigger="click" placement="bottom-start" :to="false" style="width: 360px">
          <template #trigger>
            <NButton size="small" class="filter-trigger">
              <template #icon>
                <NBadge :value="activeFilterCount" :offset="[-2, 2]" :show="activeFilterCount > 0">
                  <NIcon><InformationCircleOutline /></NIcon>
                </NBadge>
              </template>
              更多
            </NButton>
          </template>
          <div class="filter-panel">
            <div class="filter-group">
              <div class="filter-group-title">搜索</div>
              <NInput v-model:value="searchFilename" placeholder="搜索文件名" size="small" clearable @keyup.enter="$emit('applyFilters')">
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
                <NSelect v-model:value="filterTimeline" :options="timelineOptions" placeholder="全部活动" clearable size="small" style="flex: 1" @update:value="$emit('applyFilters')" />
              </div>
            </div>
            <div class="filter-group">
              <div class="filter-group-title">统计</div>
              <div class="stats-summary">
                <span>数据完整 {{ embedStats?.with_embedding ?? '...' }} 张</span><span class="stats-sep">|</span>
                <span>VLM待处理 {{ stats?.without_description ?? '...' }} 张</span><span class="stats-sep">|</span>
                <span>Embed待处理 {{ pendingEmbedCount }} 张</span>
              </div>
            </div>
            <div class="filter-panel-footer"><NButton size="tiny" quaternary @click="$emit('resetFilters')">重置筛选</NButton></div>
          </div>
        </NPopover>
      </div>

      <!-- 折叠模式：宽度不足 -->
      <div v-show="collapsed" class="toolbar-collapsed">
        <NPopover trigger="click" placement="bottom-start" :to="false" style="width: 360px">
          <template #trigger>
            <NButton size="small">
              <template #icon>
                <NBadge :value="activeFilterCount" :offset="[-2, 2]" :show="activeFilterCount > 0">
                  <NIcon><InformationCircleOutline /></NIcon>
                </NBadge>
              </template>
              更多
            </NButton>
          </template>
          <div class="filter-panel">
            <div class="filter-group">
              <div class="filter-group-title">视图</div>
              <div class="collapsed-controls">
                <span class="total-count">共 {{ stats?.total ?? total }} 张</span>
                <NTooltip trigger="hover" placement="top">
                  <template #trigger>
                    <NButton size="small" @click="$emit('cycleViewLevel')">
                      {{ viewLevelLabels[burstViewLevel] }}
                    </NButton>
                  </template>
                  点击切换连拍展示级别
                </NTooltip>
                <NSelect :value="segmentMode" :options="segmentModeOptions" size="small" style="width: 96px" @update:value="$emit('changeSegmentMode', $event as SegmentMode)" />
                <NButton size="small" @click="$emit('toggleSortOrder')">
                  {{ sortOrder === 'asc' ? '↑ 升序' : '↓ 降序' }}
                </NButton>
              </div>
            </div>
            <div class="filter-group">
              <div class="filter-group-title">搜索</div>
              <NInput v-model:value="searchFilename" placeholder="搜索文件名" size="small" clearable @keyup.enter="$emit('applyFilters')">
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
                <NSelect v-model:value="filterTimeline" :options="timelineOptions" placeholder="全部活动" clearable size="small" style="flex: 1" @update:value="$emit('applyFilters')" />
              </div>
            </div>
            <div class="filter-group">
              <div class="filter-group-title">统计</div>
              <div class="stats-summary">
                <span>数据完整 {{ embedStats?.with_embedding ?? '...' }} 张</span><span class="stats-sep">|</span>
                <span>VLM待处理 {{ stats?.without_description ?? '...' }} 张</span><span class="stats-sep">|</span>
                <span>Embed待处理 {{ pendingEmbedCount }} 张</span>
              </div>
            </div>
            <div class="filter-panel-footer"><NButton size="tiny" quaternary @click="$emit('resetFilters')">重置筛选</NButton></div>
          </div>
        </NPopover>
      </div>
    </div>
    <NSpace v-if="selectionMode" :wrap="false">
      <span class="selection-count">已选 {{ selectedCount }} 张</span>
      <NButton @click="$emit('selectAll')">全选</NButton>
      <NButton :disabled="selectedCount === 0" @click="$emit('clearSelection')">取消全选</NButton>
      <NButton v-if="showIntervalSelect" @click="$emit('intervalSelect')">区间选择</NButton>
      <NButton type="primary" :disabled="selectedCount === 0" @click="$emit('goToPostStudio')"><template #icon><NIcon><ImagesOutline /></NIcon></template>图文工坊</NButton>
      <NButton @click="$emit('toggleSelectionMode')"><template #icon><NIcon><CloseOutline /></NIcon></template>退出选择</NButton>
    </NSpace>
    <NSpace v-else :wrap="false">
      <NTooltip v-if="vlmRunning" trigger="hover"><template #trigger><NTag type="info" size="large" class="progress-tag" :style="{ cursor: 'pointer' }" @click="$emit('stopVlm')">{{ vlmCompleted }}/{{ vlmTotal }}</NTag></template>点击中止处理</NTooltip>
      <NButton v-else type="primary" @click="$emit('startVlm')"><template #icon><NIcon><PlayOutline /></NIcon></template>VLM</NButton>
      <NTooltip v-if="embedRunning" trigger="hover"><template #trigger><NTag type="warning" size="large" class="progress-tag" :style="{ cursor: 'pointer' }" @click="$emit('stopEmbed')">Embed {{ embedCompleted }}/{{ embedTotal }}</NTag></template>点击中止处理</NTooltip>
      <NButton v-else type="warning" @click="$emit('startEmbed')"><template #icon><NIcon><LayersOutline /></NIcon></template>Embed</NButton>
      <NTooltip v-if="burstRunning" trigger="hover"><template #trigger><NTag type="info" size="large" class="progress-tag" :style="{ cursor: 'pointer' }">连拍 {{ burstProcessed }}/{{ burstTotal }}</NTag></template>正在重算连拍分组</NTooltip>
      <NButton v-else @click="$emit('rebuildBurst')"><template #icon><NIcon><GridOutline /></NIcon></template>连拍分组</NButton>
      <NButton @click="$emit('upload')"><template #icon><NIcon><CloudUploadOutline /></NIcon></template>上传图片</NButton>
      <NButton @click="$emit('toggleSelectionMode')"><template #icon><NIcon><CheckboxOutline /></NIcon></template>选择模式</NButton>
    </NSpace>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; justify-content: space-between; padding: 0 24px; height: 56px; }
.toolbar-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.toolbar-title { margin: 0; font-size: 16px; white-space: nowrap; }
.toolbar-inline { display: flex; align-items: center; gap: 12px; }
.toolbar-collapsed { display: flex; align-items: center; }
.total-count, .filter-label { font-size: 13px; color: var(--n-text-color-3); white-space: nowrap; }
.selection-count { font-size: 13px; color: var(--n-text-color-2); white-space: nowrap; }
.filter-trigger { flex-shrink: 0; }
.filter-panel, .filter-group { display: flex; flex-direction: column; }
.filter-panel { gap: 16px; padding: 4px 0; }
.filter-group { gap: 8px; }
.filter-group-title { font-size: 12px; font-weight: 600; color: var(--n-text-color-3); }
.filter-group-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-panel-footer { display: flex; justify-content: flex-end; border-top: 1px solid var(--n-border-color); padding-top: 8px; }
.stats-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 0; font-size: 13px; color: var(--n-text-color-3); }
.stats-sep { margin: 0 8px; color: var(--n-divider-color); }
.progress-tag { font-size: 14px; padding: 4px 16px; }
.collapsed-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
