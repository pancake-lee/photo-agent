<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted, provide } from 'vue'
import {
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NButton,
  NSpace,
  NTag,
  NTooltip,
  NIcon,
  NDatePicker,
  NSelect,
  NInput,
  NPopover,
  NBadge,
  useMessage,
} from 'naive-ui'
import {
  PlayOutline,
  CloudUploadOutline,
  SearchOutline,
  LayersOutline,
  GridOutline,
  InformationCircleOutline,
} from '@vicons/ionicons5'

import PhotoGrid from '../components/PhotoGrid.vue'
import PhotoDetail from '../components/PhotoDetail.vue'
import DescriptionModal from '../components/DescriptionModal.vue'
import UploadModal from '../components/UploadModal.vue'
import ConflictModal from '../components/ConflictModal.vue'
import BurstGroupModal from '../components/BurstGroupModal.vue'
import PhotoSegmentNav, { type NavItem } from '../components/PhotoSegmentNav.vue'

import { usePhotos } from '../composables/usePhotos'
import { useUpload } from '../composables/useUpload'
import { useVlmQueue } from '../composables/useVlmQueue'
import { useEmbedQueue } from '../composables/useEmbedQueue'
import { useEmbedStatus } from '../composables/useEmbedStatus'
import { useBurstGroups } from '../composables/useBurstGroups'
import { settings } from '../stores/settings'
import type { PhotoDetail as PhotoDetailType, BurstViewLevel } from '../types/photo'
import type { SegmentMode } from '../utils/segment'
import type { ConflictResolution } from '../types/upload'

const message = useMessage()

// ── 照片列表 ──
const {
  photos,
  total,
  loading,
  loadingDown,
  loadingUp,
  noMoreDown,
  noMoreUp,
  error,
  selectedPhoto,
  showDetail,
  detailLoading,
  stats,
  timelines,
  segments,
  filterTimeline,
  filterShotAtStart,
  filterShotAtEnd,
  sortOrder,
  searchFilename,
  burstModalGroup,
  burstModalMembers,
  burstModalCoverId,
  burstModalLoading,
  relocateTo,
  relocateToStart,
  loadDown,
  loadUp,
  fetchSegments,
  fetchStats,
  fetchTimelines,
  fetchPhotoDetail,
  closeDetail,
  applyFilters,
  resetFilters,
  deletePhoto,
  openBurstGroup,
  closeBurstGroup,
  setBurstCover,
} = usePhotos()

// ── 上传 ──
const {
  showUploadModal,
  files,
  uploading,
  currentConflict,
  addFiles,
  removeFile,
  startUpload,
  openUploadModal,
  closeUploadModal,
} = useUpload()

// ── VLM 队列 ──
const {
  status: vlmStatus,
  startQueue,
  stopQueue,
  enqueuePhoto,
  onComplete,
} = useVlmQueue()

// ── Embed 队列 ──
const {
  status: embedStatus,
  startQueue: startEmbedQueue,
  stopQueue: stopEmbedQueue,
  enqueuePhoto: enqueueEmbedPhoto,
  onComplete: onEmbedComplete,
} = useEmbedQueue()

// ── Embed 状态查询 ──
const {
  embeddedIds,
  embedStats,
  fetchEmbeddedIds,
  fetchEmbedStats,
} = useEmbedStatus()

// ── 连拍分组 ──
const {
  status: burstStatus,
  rebuild: rebuildBurst,
  fetchStatus: fetchBurstStatus,
  stopPolling: stopBurstPolling,
} = useBurstGroups()

// ── 处理中的照片 ID ──
const processingIds = ref<Set<string>>(new Set())

// ── 描述弹窗 ──
const showDescModal = ref(false)
const descPhoto = ref<PhotoDetailType | null>(null)

// ── 冲突弹窗 ──
const showConflictModal = ref(false)
const conflictResolver = ref<((r: ConflictResolution) => void) | null>(null)

// ── 计算属性 ──
const vlmCompleted = computed(() => vlmStatus.value.completed)
const vlmTotal = computed(() => vlmStatus.value.total)
const vlmRunning = computed(() => vlmStatus.value.running)
const embedRunning = computed(() => embedStatus.value.running)
const embedCompleted = computed(() => embedStatus.value.completed)
const embedTotal = computed(() => embedStatus.value.total)
const burstRunning = computed(() => burstStatus.value.running)
const burstProcessed = computed(() => burstStatus.value.processed)
const burstTotal = computed(() => burstStatus.value.total)

// 待 Embed 数量 = 有描述的 - 已嵌入的（避免负数）
const pendingEmbedCount = computed(() => {
  const withDesc = stats.value?.with_description ?? 0
  const withEmb = embedStats.value?.with_embedding ?? 0
  return Math.max(0, withDesc - withEmb)
})

// 时间线选项（含「未分类」散图项，sentinel 值由后端翻译）
const timelineOptions = computed(() => [
  ...timelines.value.map((t) => ({ label: t, value: t })),
  { label: '未分类', value: 'none' },
])

// 「更多」触发器角标：已设非默认值的筛选项计数（搜索 / 日期 / 活动均在「更多」内）
const activeFilterCount = computed(() => {
  let n = 0
  if (searchFilename.value) n++
  if (filterTimeline.value) n++
  if (filterShotAtStart.value || filterShotAtEnd.value) n++
  return n
})

// ── 分段浏览 ──

// 分段方式选项
const segmentModeOptions = [
  { label: '按天', value: 'day' },
  { label: '按月', value: 'month' },
  { label: '按活动', value: 'activity' },
]

// 右侧导航列表：直接使用后端 ListPhotoSegments 返回的分段（含 count 与 offset）
const navItems = computed<NavItem[]>(() =>
  segments.value.map((s) => ({ key: s.key, label: s.label, count: s.count })),
)

// 当前滚动位置所处段落的导航键（取视口内最后一条已越过顶部的分割线）
const activeNavKey = ref('')

// 各分割线的 DOM 引用（key = 分段键，交错时同一键覆盖）
const dividerEls = new Map<string, HTMLElement>()

function setDividerEl(key: string, el: unknown) {
  if (el instanceof HTMLElement) dividerEls.set(key, el)
  else dividerEls.delete(key)
}

// 照片列表自身的有界滚动容器（.grid-main），既是 PhotoGrid 内 IntersectionObserver 的 root，
// 也是导航锚点滚动与滚动高亮跟随的目标。
const gridScrollRef = ref<HTMLElement | null>(null)
provide('photoGridScrollRoot', gridScrollRef)

// 滚动高亮跟随：分割线越过滚动容器顶部时更新当前段落。
// 坐标必须相对滚动容器顶端换算：getBoundingClientRect 是浏览器视口坐标，
// 而照片列表顶端在视口下方（工具栏 + 统计 + 筛选），直接用视口坐标阈值永不成立。
// 取流中最后一条已越过容器顶部（相对 top ≤ 80px）的分割线；都在顶部之前时取首段。
const NAV_TOP_THRESHOLD_PX = 80

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
    // 兜底候选：流中相对 top 最小的分割线（尚在第一段分割线之前时用）
    if (top < firstTop) {
      firstKey = key
      firstTop = top
    }
  }
  if (current === '') current = firstKey
  // 按天/按月的分割线键是天/月粒度，导航高亮降到月份粒度
  activeNavKey.value =
    settings.segmentMode === 'activity' ? current : current.slice(0, 7)
}

onMounted(() => {
  gridScrollRef.value?.addEventListener('scroll', updateActiveNav, { passive: true })
})
onUnmounted(() => {
  gridScrollRef.value?.removeEventListener('scroll', updateActiveNav)
})

// ── 导航点击跳转 ──
async function handleNavJump(key: string) {
  const seg = segments.value.find((s) => s.key === key)
  if (!seg) return
  await relocateTo(seg.offset)
  await nextTick()
  // 等流渲染完成再定位：relocateTo 后照片数组刚更新，本轮 nextTick 可能只渲染了部分
  await nextTick()
  // 以分段首张渲染照片卡为锚点（而非分割线）：分割线位置受连拍折叠渲染
  // 与 DOM 渲染时机影响有偏差，照片卡是用户感知的落位主体。
  // 全量 offset 落在窗口内后，分段首张照片 = 窗口起点之后该分段的首张渲染照片。
  const sc = gridScrollRef.value
  const anchor = findSegmentFirstPhotoEl(key)
  if (sc && anchor) {
    sc.scrollTop = anchor.offsetTop - NAV_TOP_THRESHOLD_PX
  } else if (sc) {
    sc.scrollTop = 0
  }
  updateActiveNav()
}

// 目标分段首张渲染照片的 DOM 元素。
// 月粒度导航 + 天粒度分割线时按键前缀匹配；遍历渲染流找到分段键（或前缀）匹配的首张照片。
function findSegmentFirstPhotoEl(key: string): HTMLElement | null {
  const sc = gridScrollRef.value
  if (!sc) return null
  const els = sc.querySelectorAll<HTMLElement>('[data-photo-id]')
  const photosById = new Map(photos.value.map((p) => [p.id, p]))
  for (const el of els) {
    const photo = photosById.get(el.dataset.photoId ?? '')
    if (!photo) continue
    if (segmentKeyOfPhoto(photo) === key) return el
    if (settings.segmentMode !== 'activity' && segmentKeyOfPhoto(photo).startsWith(key)) {
      return el
    }
  }
  return null
}

// 照片的分段键（与 utils/segment.ts 的 segKeyOf 对齐）
function segmentKeyOfPhoto(photo: { shot_at: string | null; timeline: string }): string {
  if (settings.segmentMode === 'activity') return photo.timeline || ''
  if (!photo.shot_at) return ''
  const d = new Date(photo.shot_at)
  if (Number.isNaN(d.getTime())) return ''
  return settings.segmentMode === 'day'
    ? d.toISOString().slice(0, 10)
    : d.toISOString().slice(0, 7)
}

// 回到最新：清空跳转筛选恢复默认视图
function handleBackToLatest() {
  resetFilters()
}

// ── 双向加载滚动补偿 ──
// 前插/整页淘汰会改变滚动内容高度，使视口内容跳变。以「锚点照片」插入前后的
// getBoundingClientRect().top 差值补偿滚动，保证视口内照片不跳变。
// overflow-anchor 已在 .grid-main 禁用，避免浏览器默认锚定与手动补偿叠加。

// 视口内最上 / 最下的已渲染照片元素（连拍折叠时未渲染成员不含 data-photo-id）
function firstRenderedPhotoEl(): HTMLElement | null {
  return gridScrollRef.value?.querySelector<HTMLElement>('[data-photo-id]') ?? null
}
function lastRenderedPhotoEl(): HTMLElement | null {
  const sc = gridScrollRef.value
  if (!sc) return null
  const els = sc.querySelectorAll<HTMLElement>('[data-photo-id]')
  return els.length ? els[els.length - 1] : null
}

// 锚点在滚动内容中的坐标（与 scrollTop 无关）：
// rect.top 是浏览器视口坐标，减去滚动容器视口 top 得到相对容器顶的偏移，
// 再加 scrollTop 抵消滚动位移，只剩内容前插/淘汰造成的真实偏移。
// 用视口坐标 getBoundingClientRect().top 直接做差，在「导航跳转 set scrollTop
// 与预加载补偿并发」时会把跳转本身的滚动量也算进补偿，导致跳转后位置被顶走。
function contentOffsetOf(el: HTMLElement, sc: HTMLElement): number {
  return el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop
}

// 向上前插补偿：锚点 = 原窗口最上照片，前插后它应保持原视口位置
async function handleLoadUp() {
  if (loading.value || loadingUp.value || loadingDown.value) return
  const sc = gridScrollRef.value
  const anchor = firstRenderedPhotoEl()
  if (!sc || !anchor) return
  const before = contentOffsetOf(anchor, sc)
  const added = await loadUp()
  if (!added) return
  await nextTick()
  const after = contentOffsetOf(anchor, sc)
  sc.scrollTop += after - before
}

// 向下追加补偿：锚点 = 原窗口最下照片，整页淘汰顶部后它应保持原视口位置
async function handleLoadDown() {
  if (loading.value || loadingUp.value || loadingDown.value) return
  const sc = gridScrollRef.value
  const anchor = lastRenderedPhotoEl()
  if (!sc || !anchor) return
  const before = contentOffsetOf(anchor, sc)
  const added = await loadDown()
  if (!added) return
  await nextTick()
  const after = contentOffsetOf(anchor, sc)
  sc.scrollTop += after - before
}

// ── 方法 ──

async function handleStartVlm() {
  try {
    const result = await startQueue()
    if (result.total === 0) {
      message.info('所有照片已有描述，无需处理')
    } else {
      message.success(`VLM 预处理已启动，共 ${result.total} 张`)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

async function handleStopVlm() {
  await stopQueue()
  message.info('VLM 预处理已中止')
  // 刷新列表和统计
  relocateToStart()
  fetchStats()
}

async function handleTriggerDescribe(photoId: string) {
  processingIds.value = new Set([...processingIds.value, photoId])
  try {
    await enqueuePhoto(photoId)
    message.success('已加入 VLM 处理队列')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '入队失败')
    processingIds.value.delete(photoId)
  }
}

async function handleStartEmbed() {
  try {
    const result = await startEmbedQueue()
    if (result.total === 0) {
      message.info('所有照片已有嵌入，无需处理')
    } else {
      message.success(`Embed 已启动，共 ${result.total} 张`)
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

async function handleStopEmbed() {
  await stopEmbedQueue()
  message.info('Embed 已中止')
  relocateToStart()
  fetchStats()
  fetchEmbedStats()
}

async function handleTriggerEmbed(photoId: string) {
  try {
    await enqueueEmbedPhoto(photoId)
    message.success('已加入 Embed 处理队列')
    // embed 完成后通过 onEmbedComplete → fetchEmbeddedIds 刷新图标状态
  } catch (e) {
    message.error(e instanceof Error ? e.message : '入队失败')
  }
}

function handleViewDescription() {
  if (selectedPhoto.value) {
    descPhoto.value = selectedPhoto.value
    showDescModal.value = true
  }
}

function handleRegenerateDescription() {
  if (descPhoto.value) {
    handleTriggerDescribe(descPhoto.value.id)
  }
  showDescModal.value = false
}

async function handleDeletePhoto(photoId: string) {
  try {
    await deletePhoto(photoId)
    message.success('图片已删除')
    fetchStats()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '删除失败')
  }
}

// ── 连拍分组重算 ──
async function handleRebuildBurst() {
  try {
    const st = await rebuildBurst(() => {
      message.success(
        `连拍分组完成，精细 ${burstStatus.value.group_count} 组 / 模糊 ${burstStatus.value.coarse_group_count} 组`,
      )
      relocateToStart()
    })
    if (st === 'already_running') {
      message.info('连拍分组已在进行中')
    } else {
      message.success('连拍分组重算已启动')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

// ── 连拍展示级别循环切换 ──
const viewLevelOrder: BurstViewLevel[] = ['all', 'fine', 'coarse']
const viewLevelLabels: Record<BurstViewLevel, string> = {
  all: '全部展开',
  fine: '精细连拍',
  coarse: '模糊连拍',
}

function handleCycleViewLevel() {
  const idx = viewLevelOrder.indexOf(settings.burstViewLevel)
  settings.burstViewLevel = viewLevelOrder[(idx + 1) % viewLevelOrder.length]
  applyFilters()
}

// ── 连拍组弹窗 ──
function handleOpenBurstGroup(groupId: string, coverId: string) {
  openBurstGroup(groupId, coverId)
}

function handleBurstSetCover(photoId: string) {
  setBurstCover(burstModalGroup.value, photoId)
    .then(() => message.success('已设为封面'))
    .catch((e) => message.error(e instanceof Error ? e.message : '设为封面失败'))
}

async function handleUploadStart() {
  // 定义冲突处理回调
  showConflictModal.value = true

  await startUpload(async (_item) => {
    // 返回 Promise，等待用户选择
    return new Promise<ConflictResolution>((resolve) => {
      conflictResolver.value = resolve
      showConflictModal.value = true
    })
  })

  showConflictModal.value = false
  closeUploadModal()
  message.success('上传完成')
  relocateToStart()
  fetchSegments()
  fetchStats()
}

function handleConflictResolve(resolution: ConflictResolution) {
  if (conflictResolver.value) {
    conflictResolver.value(resolution)
    conflictResolver.value = null
  }
  showConflictModal.value = false
}

// 冲突弹窗关闭但未选择时，默认 skip，避免上传循环永久阻塞
watch(showConflictModal, (v) => {
  if (!v && conflictResolver.value) {
    conflictResolver.value('skip')
    conflictResolver.value = null
  }
})

// 日期变化处理（NaiveUI DatePicker v-model 返回时间戳或 null）
function handleDateStart(v: number | null) {
  if (v) {
    const d = new Date(v)
    filterShotAtStart.value = d.toISOString()
  } else {
    filterShotAtStart.value = ''
  }
}

function handleDateEnd(v: number | null) {
  if (v) {
    // 结束日期设为当天 23:59:59
    const d = new Date(v)
    d.setHours(23, 59, 59, 999)
    filterShotAtEnd.value = d.toISOString()
  } else {
    filterShotAtEnd.value = ''
  }
}

// 切换排序方向
function toggleSortOrder() {
  sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  applyFilters()
}

// 切换分段方式（导航与分割线响应式重算，照片不重拉）
function handleSegmentModeChange(mode: SegmentMode) {
  settings.segmentMode = mode
  dividerEls.clear()
  activeNavKey.value = ''
  fetchSegments()
}

// ── VLM 完成回调：自动刷新列表和统计 ──
onComplete(() => {
  relocateToStart()
  fetchStats()
})

// ── Embed 完成回调 ──
onEmbedComplete(() => {
  relocateToStart()
  fetchStats()
  fetchEmbedStats()
})

// ── 照片列表变化时自动同步 Embed 状态 ──
watch(photos, (newPhotos) => {
  const ids = newPhotos.map((p) => p.id)
  fetchEmbeddedIds(ids)
})

// ── 初始化 ──
onMounted(async () => {
  await applyFilters()
  fetchStats()
  fetchTimelines()
  fetchEmbedStats()
  fetchBurstStatus()
})

onUnmounted(() => {
  stopBurstPolling()
})
</script>

<template>
  <NLayout class="page-layout">
    <!-- 顶部工具栏（单行：标题 + 总数 + 视图控制 + 更多 | 右侧动作） -->
    <NLayoutHeader bordered>
        <div class="toolbar">
          <div class="toolbar-left">
            <h3 class="toolbar-title">图片管理</h3>

            <!-- 总数（其余统计在「更多」内查看） -->
            <span class="total-count">共 {{ stats?.total ?? total }} 张</span>

            <!-- 视图控制 -->
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

            <NButton size="small" @click="toggleSortOrder">
              {{ sortOrder === 'asc' ? '↑ 升序' : '↓ 降序' }}
            </NButton>

            <!-- 更多：搜索 + 筛选（日期 / 活动）+ 其余统计 -->
            <NPopover
              trigger="click"
              placement="bottom-start"
              :to="false"
              style="width: 360px"
            >
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
                <!-- 搜索组 -->
                <div class="filter-group">
                  <div class="filter-group-title">搜索</div>
                  <NInput
                    v-model:value="searchFilename"
                    placeholder="搜索文件名"
                    size="small"
                    clearable
                    @keyup.enter="applyFilters"
                  >
                    <template #prefix>
                      <NIcon><SearchOutline /></NIcon>
                    </template>
                  </NInput>
                </div>

                <!-- 筛选组 -->
                <div class="filter-group">
                  <div class="filter-group-title">筛选</div>
                  <div class="filter-group-row">
                    <span class="filter-label">拍摄日期</span>
                    <NDatePicker
                      type="date"
                      clearable
                      placeholder="起始日期"
                      size="small"
                      style="width: 132px"
                      @update:value="handleDateStart"
                    />
                    <span class="filter-label">至</span>
                    <NDatePicker
                      type="date"
                      clearable
                      placeholder="结束日期"
                      size="small"
                      style="width: 132px"
                      @update:value="handleDateEnd"
                    />
                  </div>
                  <div class="filter-group-row">
                    <span class="filter-label">活动</span>
                    <NSelect
                      v-model:value="filterTimeline"
                      :options="timelineOptions"
                      placeholder="全部活动"
                      clearable
                      size="small"
                      style="flex: 1"
                      @update:value="applyFilters"
                    />
                  </div>
                </div>

                <!-- 统计组（只读，其余数据） -->
                <div class="filter-group">
                  <div class="filter-group-title">统计</div>
                  <div class="stats-summary">
                    <span>数据完整 {{ embedStats?.with_embedding ?? '...' }} 张</span>
                    <span class="stats-sep">|</span>
                    <span>VLM待处理 {{ stats?.without_description ?? '...' }} 张</span>
                    <span class="stats-sep">|</span>
                    <span>Embed待处理 {{ pendingEmbedCount }} 张</span>
                  </div>
                </div>

                <!-- 重置 -->
                <div class="filter-panel-footer">
                  <NButton size="tiny" quaternary @click="resetFilters">
                    重置筛选
                  </NButton>
                </div>
              </div>
            </NPopover>
          </div>

          <NSpace :wrap="false">
            <!-- VLM 全局控制 -->
            <template v-if="vlmRunning">
              <NTooltip trigger="hover">
                <template #trigger>
                  <NTag
                    type="info"
                    size="large"
                    class="progress-tag"
                    :style="{ cursor: 'pointer' }"
                    @click="handleStopVlm"
                  >
                    {{ vlmCompleted }}/{{ vlmTotal }}
                  </NTag>
                </template>
                点击中止处理
              </NTooltip>
            </template>

            <NButton
              v-if="!vlmRunning"
              type="primary"
              @click="handleStartVlm"
            >
              <template #icon>
                <NIcon><PlayOutline /></NIcon>
              </template>
              VLM
            </NButton>

            <!-- Embed 全局控制 -->
            <template v-if="embedRunning">
              <NTooltip trigger="hover">
                <template #trigger>
                  <NTag
                    type="warning"
                    size="large"
                    class="progress-tag"
                    :style="{ cursor: 'pointer' }"
                    @click="handleStopEmbed"
                  >
                    Embed {{ embedCompleted }}/{{ embedTotal }}
                  </NTag>
                </template>
                点击中止处理
              </NTooltip>
            </template>

            <NButton
              v-if="!embedRunning"
              type="warning"
              @click="handleStartEmbed"
            >
              <template #icon>
                <NIcon><LayersOutline /></NIcon>
              </template>
              Embed
            </NButton>

            <!-- 连拍分组重算 -->
            <template v-if="burstRunning">
              <NTooltip trigger="hover">
                <template #trigger>
                  <NTag
                    type="info"
                    size="large"
                    class="progress-tag"
                    :style="{ cursor: 'pointer' }"
                  >
                    连拍 {{ burstProcessed }}/{{ burstTotal }}
                  </NTag>
                </template>
                正在重算连拍分组
              </NTooltip>
            </template>
            <NButton v-else @click="handleRebuildBurst">
              <template #icon>
                <NIcon><GridOutline /></NIcon>
              </template>
              连拍分组
            </NButton>

            <!-- 上传按钮 -->
            <NButton @click="openUploadModal">
              <template #icon>
                <NIcon><CloudUploadOutline /></NIcon>
              </template>
              上传图片
            </NButton>
          </NSpace>
        </div>
      </NLayoutHeader>

      <!-- 主内容区 -->
      <NLayoutContent>
        <div class="content-wrapper">
          <!-- 照片流 + 右侧分段导航 -->
          <div class="grid-with-nav">
            <div ref="gridScrollRef" class="grid-main">
              <PhotoGrid
                :photos="photos"
                :loading="loading"
                :loading-down="loadingDown"
                :loading-up="loadingUp"
                :no-more-down="noMoreDown"
                :no-more-up="noMoreUp"
                :error="error"
                :processing-ids="processingIds"
                :embedded-ids="embeddedIds"
                :view-level="settings.burstViewLevel"
                :segment-mode="settings.segmentMode"
                @view-detail="fetchPhotoDetail"
                @trigger-describe="handleTriggerDescribe"
                @trigger-embed="handleTriggerEmbed"
                @delete-photo="handleDeletePhoto"
                @open-burst-group="handleOpenBurstGroup"
                @divider-el="setDividerEl"
                @load-down="handleLoadDown"
                @load-up="handleLoadUp"
                @retry="relocateToStart"
              />
            </div>
            <PhotoSegmentNav
              :items="navItems"
              :active-key="activeNavKey"
              @jump="handleNavJump"
              @back-to-latest="handleBackToLatest"
            />
          </div>
        </div>
      </NLayoutContent>
  </NLayout>

  <!-- 照片详情抽屉 -->
  <PhotoDetail
    :show="showDetail"
    :photo="selectedPhoto"
    :loading="detailLoading"
    @close="closeDetail"
    @trigger-describe="handleTriggerDescribe"
    @trigger-embed="handleTriggerEmbed"
    @view-description="handleViewDescription"
  />

  <!-- 连拍组弹窗 -->
  <BurstGroupModal
    :show="burstModalGroup !== ''"
    :group-id="burstModalGroup"
    :members="burstModalMembers"
    :cover-id="burstModalCoverId"
    :loading="burstModalLoading"
    @close="closeBurstGroup"
    @view-detail="fetchPhotoDetail"
    @set-cover="handleBurstSetCover"
  />

  <!-- 描述内容弹窗 -->
  <DescriptionModal
    :show="showDescModal"
    :filename="descPhoto?.filename || ''"
    :description="descPhoto?.description || ''"
    :model="descPhoto?.description_model || ''"
    :processed-at="descPhoto?.description_time || ''"
    @close="showDescModal = false"
    @regenerate="handleRegenerateDescription"
  />

  <!-- 上传弹窗 -->
  <UploadModal
    :show="showUploadModal"
    :files="files"
    :uploading="uploading"
    @close="closeUploadModal"
    @add-files="addFiles"
    @remove-file="removeFile"
    @start-upload="handleUploadStart"
  />

  <!-- 冲突弹窗 -->
  <ConflictModal
    :show="showConflictModal"
    :conflict="currentConflict?.conflict || null"
    :new-filename="currentConflict?.file.originalName || ''"
    :new-shot-at="currentConflict?.file.shotAt || ''"
    @close="showConflictModal = false"
    @resolve="handleConflictResolve"
  />
</template>

<style scoped>
/* 补齐高度链：naive-ui 的 NLayout 内层 scroll-container 是 block 布局，
   NLayoutContent 自带的 flex:auto 因此失效、高度塌成 auto，导致下游
   .content-wrapper / .grid-main 的 height:100% 全部解析为 auto，
   .grid-main 拿不到有界高度就不会滚动（scroll 事件不触发 → 滚动加载失效）。
   把 scroll-container 改为纵向 flex，让 content 区拿到确定高度。 */
.page-layout > :deep(.n-layout-scroll-container) {
  display: flex;
  flex-direction: column;
}
.page-layout :deep(.n-layout-header) {
  flex-shrink: 0;
}
.page-layout :deep(.n-layout-content) {
  flex: 1;
  min-height: 0;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0; /* 宽度不足时优先压缩标题 */
}
.total-count {
  font-size: 13px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
.toolbar-title {
  margin: 0;
  font-size: 16px;
  white-space: nowrap;
}
.filter-trigger {
  flex-shrink: 0;
}
.filter-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 0;
}
.filter-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.filter-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-3);
}
.filter-group-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-panel-footer {
  display: flex;
  justify-content: flex-end;
  border-top: 1px solid var(--n-border-color);
  padding-top: 8px;
}
.progress-tag {
  font-size: 14px;
  padding: 4px 16px;
}
.content-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
  padding: 20px 24px;
  overflow: hidden;
}
.stats-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 0;
  font-size: 13px;
  color: var(--n-text-color-3);
}
.stats-sep {
  margin: 0 8px;
  color: var(--n-divider-color);
}
.filter-label {
  font-size: 13px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}
.grid-with-nav {
  display: flex;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  gap: 16px;
}
.grid-main {
  flex: 1;
  min-width: 0; /* 允许网格收缩 */
  min-height: 0;
  overflow-y: auto;
  overflow-anchor: none; /* 禁用浏览器滚动锚定，滚动补偿由 handleLoadUp/handleLoadDown 手动处理 */
}
</style>
