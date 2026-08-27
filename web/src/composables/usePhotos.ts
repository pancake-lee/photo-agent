import { ref, computed } from 'vue'
import { getApiBase } from '../config'
import { photoApi, timelineApi } from '../backend-sdk-client'
import { settings } from '../stores/settings'
import { useBurstGroups } from './useBurstGroups'
import type {
  ApiPhotoItem,
  ApiGetPhotoDetailResponse,
  ApiSearchPhotosResponse,
  ApiGetPhotoStatsResponse,
  ApiListPhotoSegmentsResponse,
} from '../../backend-sdk/api'
import type { PhotoListItem, PhotoDetail, PhotoStats, BurstProfile } from '../types/photo'

// 滚动加载单页条数（后端单页上限 100）
const SCROLL_PAGE_SIZE = 100
// 窗口内存上界：10 页 = 1000 张，超出后从滚动反方向整页淘汰
const MAX_WINDOW_PAGES = 10

// timeline 筛选 sentinel：筛出无活动标签的散图（后端翻译为空串过滤）
export const TIMELINE_NONE = 'none'

// ------------------------------------------------------------------ #
// 适配器：SDK camelCase → 现有 snake_case 类型
// ------------------------------------------------------------------ #

// 后端把 shot_at/imported_at 存为 int64 Unix 秒，protojson 序列化成字符串
// （如 "1723456789"）。转成 ISO 字符串供前端 new Date 解析；0/空/非法返回 null。
function adaptUnixSec(s?: string): string | null {
  if (!s || s === '0') return null
  const sec = Number(s)
  if (!Number.isFinite(sec) || sec <= 0) return null
  return new Date(sec * 1000).toISOString()
}

function adaptPhotoItem(item: ApiPhotoItem): PhotoListItem {
  return {
    id: item.id ?? '',
    filename: item.filename ?? '',
    file_path: item.filePath ?? '',
    timeline: item.timeline ?? '',
    tags: item.tags ?? '',
    description: item.description ?? '',
    shot_at: adaptUnixSec(item.shotAt),
    width: item.width ?? 0,
    height: item.height ?? 0,
    brand: item.brand ?? '',
    model: item.model ?? '',
    lens: item.lens ?? '',
    focal_length: item.focalLength ?? '',
    aperture: item.aperture ?? '',
    iso: item.iso ?? 0,
    exposure_time: item.exposureTime ?? '',
    latitude: item.latitude ?? null,
    longitude: item.longitude ?? null,
    altitude: item.altitude ?? null,
    imported_at: adaptUnixSec(item.importedAt) ?? '',
    has_description: item.hasDescription ?? false,
    thumbnail_url: item.id ? `${getApiBase()}/photos/${item.id}/image` : '',
    has_nef: item.hasNef ?? false,
    burst_group_id: item.burstGroupId ?? '',
    burst_cover: item.burstCover ?? false,
    burst_count: item.burstCount ?? 0,
  }
}

function adaptPhotoDetail(resp: ApiGetPhotoDetailResponse): PhotoDetail {
  const photo = resp.photo
  return {
    id: photo?.id ?? '',
    filename: photo?.filename ?? '',
    file_path: photo?.filePath ?? '',
    timeline: photo?.timeline ?? '',
    tags: photo?.tags ?? '',
    description: photo?.description ?? '',
    shot_at: adaptUnixSec(photo?.shotAt),
    width: photo?.width ?? 0,
    height: photo?.height ?? 0,
    brand: photo?.brand ?? '',
    model: photo?.model ?? '',
    lens: photo?.lens ?? '',
    focal_length: photo?.focalLength ?? '',
    aperture: photo?.aperture ?? '',
    iso: photo?.iso ?? 0,
    exposure_time: photo?.exposureTime ?? '',
    latitude: photo?.latitude ?? null,
    longitude: photo?.longitude ?? null,
    altitude: photo?.altitude ?? null,
    imported_at: adaptUnixSec(photo?.importedAt) ?? '',
    has_description: photo?.hasDescription ?? false,
    thumbnail_url: photo?.id ? `${getApiBase()}/photos/${photo.id}/image` : '',
    image_url: photo?.id ? `${getApiBase()}/photos/${photo.id}/image` : '',
    description_model: resp.descriptionModel ?? '',
    description_time: resp.descriptionTime ?? '',
    ai_health_status: photo?.aiHealthStatus ?? 'pending',
    ai_health_reason: photo?.aiHealthReason ?? '',
    vlm_status: photo?.vlmStatus ?? 'pending',
    vlm_reason: photo?.vlmReason ?? '',
    embedding_status: photo?.embeddingStatus ?? 'pending',
    embedding_description_time: photo?.embeddingDescriptionTime ?? '',
  }
}

function adaptStats(s: ApiGetPhotoStatsResponse): PhotoStats {
  return {
    total: parseInt(s.total ?? '0', 10),
    with_description: parseInt(s.withDescription ?? '0', 10),
    without_description: parseInt(s.withoutDescription ?? '0', 10),
    brands: (s.brands ?? []).map(b => ({ name: b.name ?? '', count: parseInt(b.count ?? '0', 10) })),
    lens: (s.lens ?? []).map(l => ({ name: l.name ?? '', count: parseInt(l.count ?? '0', 10) })),
    focal_ranges: (s.focalRanges ?? []).map(f => ({ range: f.range ?? '', label: f.label ?? '', count: parseInt(f.count ?? '0', 10) })),
    gps: {
      with_gps: parseInt(s.gps?.withGps ?? '0', 10),
      without_gps: parseInt(s.gps?.withoutGps ?? '0', 10),
    },
    monthly: (s.monthly ?? []).map(m => ({ month: m.month ?? '', count: parseInt(m.count ?? '0', 10) })),
    hourly: (s.hourly ?? []).map(h => ({ hour: h.hour ?? 0, count: parseInt(h.count ?? '0', 10) })),
  }
}

// ------------------------------------------------------------------ #
// 分段导航项（后端 ListPhotoSegments 返回）
// ------------------------------------------------------------------ #

export interface PhotoSegmentNavItem {
  key: string
  label: string
  count: number
  /** 该分段首张照片在完整排序列表中的 0 基下标 */
  offset: number
}

// ------------------------------------------------------------------ #
// 全局状态
// ------------------------------------------------------------------ #

// 照片窗口：photos 是完整排序列表上 [windowStart, windowStart+len) 的连续区间
const photos = ref<PhotoListItem[]>([])
const windowStart = ref(0)
const total = ref(0)
const loading = ref(false) // 初始 / 重定位加载
const loadingDown = ref(false)
const loadingUp = ref(false)
const error = ref<string | null>(null)
// 非关键辅助数据加载失败不会中断照片流，但必须交给页面显示给用户。
const auxiliaryError = ref<string | null>(null)
const pendingPageRequestMap = new Map<string, Promise<{ items: PhotoListItem[]; total: number }>>()

// 分段导航
const segments = ref<PhotoSegmentNavItem[]>([])

// 连拍组弹窗状态（空串 = 未打开）
const burstModalGroup = ref('')
const burstModalMembers = ref<PhotoListItem[]>([])
const burstModalCoverId = ref('')
const burstModalLoading = ref(false)

/** 当前展示级别对应的连拍档位（全部展开时无档位） */
function currentBurstProfile(): BurstProfile | undefined {
  return settings.burstViewLevel === 'all' ? undefined : settings.burstViewLevel
}

// 筛选/排序/搜索状态
const filterTimeline = ref('')
const filterShotAtStart = ref('')
const filterShotAtEnd = ref('')
const sortBy = ref('shot_at')
const sortOrder = ref('desc')
const searchFilename = ref('')

// 综合统计
const stats = ref<PhotoStats | null>(null)

// 时间线列表（供筛选下拉）
const timelines = ref<string[]>([])

// 选中的照片详情
const selectedPhoto = ref<PhotoDetail | null>(null)
const showDetail = ref(false)
const detailLoading = ref(false)

export function usePhotos() {
  // 向下已到列表末尾 / 向上已到列表开头
  const noMoreDown = computed(() => windowStart.value + photos.value.length >= total.value)
  const noMoreUp = computed(() => windowStart.value <= 0)

  // 拉取某页（1 基）照片，返回 items 与全量 total
  async function fetchPage(page: number): Promise<{ items: PhotoListItem[]; total: number }> {
    const requestKey = JSON.stringify({
      page,
      timeline: filterTimeline.value,
      keyword: searchFilename.value,
      shotAtStart: filterShotAtStart.value,
      shotAtEnd: filterShotAtEnd.value,
      sortBy: sortBy.value,
      sortOrder: sortOrder.value,
      burstProfile: currentBurstProfile(),
    })
    const pending = pendingPageRequestMap.get(requestKey)
    if (pending) return pending
    const request = photoApi.photoServiceSearchPhotos(
      page, SCROLL_PAGE_SIZE, filterTimeline.value || undefined, undefined,
      searchFilename.value || undefined, undefined, undefined, undefined, undefined,
      undefined, undefined, filterShotAtStart.value || undefined, filterShotAtEnd.value || undefined,
      sortBy.value, sortOrder.value, undefined, currentBurstProfile(),
    ).then((resp: ApiSearchPhotosResponse) => ({
      items: (resp.items ?? []).map(adaptPhotoItem),
      total: parseInt(resp.total ?? '0', 10),
    })).finally(() => {
      pendingPageRequestMap.delete(requestKey)
    })
    pendingPageRequestMap.set(requestKey, request)
    return request
  }

  // 窗口重定位：以 offset 为中心加载「目标页 + 上下各一页」，
  // 覆盖目标分段及其预加载区间（用于初始加载与导航跳转）。
  async function relocateTo(offset: number) {
    loading.value = true
    error.value = null
    try {
      const rawPage = Math.floor(Math.max(0, offset) / SCROLL_PAGE_SIZE) + 1
      const first = await fetchPage(rawPage)
      total.value = first.total

      if (total.value === 0) {
        photos.value = []
        windowStart.value = 0
        return
      }

      // offset 越界时收敛到合法范围（segments 与窗口同源，正常不会触发）
      const clampedOffset = Math.max(0, Math.min(offset, total.value - 1))
      const centerPage = Math.floor(clampedOffset / SCROLL_PAGE_SIZE) + 1
      let centerItems = first.items
      if (centerPage !== rawPage) {
        const refetched = await fetchPage(centerPage)
        centerItems = refetched.items
      }

      const lastPage = Math.max(1, Math.ceil(total.value / SCROLL_PAGE_SIZE))
      const startPage = Math.max(1, centerPage - 1)
      const endPage = Math.min(lastPage, centerPage + 1)

      const byPage = new Map<number, PhotoListItem[]>()
      byPage.set(centerPage, centerItems)
      const neighbors: number[] = []
      for (let p = startPage; p <= endPage; p++) if (p !== centerPage) neighbors.push(p)
      const neighborResults = await Promise.all(neighbors.map((p) => fetchPage(p)))
      neighborResults.forEach((r, i) => byPage.set(neighbors[i], r.items))

      const items: PhotoListItem[] = []
      for (let p = startPage; p <= endPage; p++) {
        items.push(...(byPage.get(p) ?? []))
      }
      windowStart.value = (startPage - 1) * SCROLL_PAGE_SIZE
      photos.value = items
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败'
    } finally {
      loading.value = false
    }
  }

  // 回到「最新」：desc 排序最新在 index 0，asc 排序最新在列表末尾
  async function relocateToStart() {
    const offset = sortOrder.value === 'asc' ? Math.max(0, total.value - 1) : 0
    await relocateTo(offset)
  }

  // 向下加载（更新/更晚方向）追加一页，返回追加条数
  async function loadDown(): Promise<number> {
    if (loading.value || loadingDown.value || loadingUp.value) return 0
    if (noMoreDown.value) return 0
    loadingDown.value = true
    try {
      const nextIndex = windowStart.value + photos.value.length
      const page = Math.floor(nextIndex / SCROLL_PAGE_SIZE) + 1
      const { items } = await fetchPage(page)
      if (items.length > 0) {
        photos.value = [...photos.value, ...items]
        evictTop()
      }
      return items.length
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败'
      return 0
    } finally {
      loadingDown.value = false
    }
  }

  // 向上加载（更早方向）前插一页，返回前插条数（组件据此补偿滚动位置）
  async function loadUp(): Promise<number> {
    if (loading.value || loadingUp.value || loadingDown.value) return 0
    if (noMoreUp.value) return 0
    loadingUp.value = true
    try {
      const prevIndex = windowStart.value - 1
      const page = Math.floor(prevIndex / SCROLL_PAGE_SIZE) + 1
      const { items } = await fetchPage(page)
      if (items.length > 0) {
        photos.value = [...items, ...photos.value]
        windowStart.value -= items.length
        evictBottom()
      }
      return items.length
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败'
      return 0
    } finally {
      loadingUp.value = false
    }
  }

  // 向下滚动时从窗口头部整页淘汰，保持 windowStart 与页边界对齐
  function evictTop() {
    const maxItems = MAX_WINDOW_PAGES * SCROLL_PAGE_SIZE
    if (photos.value.length > maxItems) {
      const removePages = Math.ceil((photos.value.length - maxItems) / SCROLL_PAGE_SIZE)
      const removeCount = removePages * SCROLL_PAGE_SIZE
      photos.value = photos.value.slice(removeCount)
      windowStart.value += removeCount
    }
  }

  // 向上滚动时从窗口尾部整页淘汰（windowStart 不变）
  function evictBottom() {
    const maxItems = MAX_WINDOW_PAGES * SCROLL_PAGE_SIZE
    if (photos.value.length > maxItems) {
      const removePages = Math.ceil((photos.value.length - maxItems) / SCROLL_PAGE_SIZE)
      const removeCount = removePages * SCROLL_PAGE_SIZE
      photos.value = photos.value.slice(0, photos.value.length - removeCount)
    }
  }

  // 分段导航的 offset 是否已落入当前窗口
  function isLoaded(offset: number): boolean {
    return offset >= windowStart.value && offset < windowStart.value + photos.value.length
  }

  // 拉取分段导航（月/活动），按天模式的导航仍用月粒度
  async function fetchSegments() {
    try {
      const mode = settings.segmentMode === 'activity' ? 'activity' : 'month'
      const resp: ApiListPhotoSegmentsResponse = await photoApi.photoServiceListPhotoSegments(
        filterTimeline.value || undefined,
        undefined, // tag
        searchFilename.value || undefined, // keyword
        undefined, // brand
        undefined, // lens
        undefined, // focalMin
        undefined, // focalMax
        undefined, // isoMin
        undefined, // isoMax
        filterShotAtStart.value || undefined,
        filterShotAtEnd.value || undefined,
        sortBy.value,
        sortOrder.value,
        undefined, // burstGroupId
        currentBurstProfile(),
        mode,
      )
      segments.value = (resp.segments ?? []).map((s) => ({
        key: s.key ?? '',
        label: s.label ?? '',
        count: parseInt(s.count ?? '0', 10),
        offset: parseInt(s.offset ?? '0', 10),
      }))
    } catch (e) {
      auxiliaryError.value = '分段导航加载失败，请重试'
    }
  }

  async function fetchStats() {
    try {
      const resp = await photoApi.photoServiceGetPhotoStats()
      stats.value = adaptStats(resp)
    } catch (e) {
      auxiliaryError.value = '照片统计加载失败，请稍后重试'
    }
  }

  async function fetchTimelines() {
    try {
      // 数据源用 ListEvents：活动事件 + 散片组（散片重算后填充，成为可筛选项）
      const resp = await timelineApi.timelineServiceListEvents()
      const names: string[] = [
        ...(resp.events ?? []).map((e) => e.event ?? ''),
        ...(resp.scattered ?? []).map((e) => e.event ?? ''),
      ].filter((n) => n !== '')
      timelines.value = names
    } catch (e) {
      auxiliaryError.value = '时间线筛选项加载失败，请稍后重试'
    }
  }

  async function fetchPhotoDetail(id: string) {
    detailLoading.value = true
    try {
      const resp = await photoApi.photoServiceGetPhotoDetail(id)
      selectedPhoto.value = adaptPhotoDetail(resp)
      showDetail.value = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取详情失败'
    } finally {
      detailLoading.value = false
    }
  }

  function closeDetail() {
    showDetail.value = false
    selectedPhoto.value = null
  }

  // 应用筛选：回到最新并刷新导航
  async function applyFilters() {
    await Promise.all([relocateToStart(), fetchSegments()])
  }

  // 重置所有筛选（含跳转筛选，恢复默认视图）
  function resetFilters() {
    filterTimeline.value = ''
    filterShotAtStart.value = ''
    filterShotAtEnd.value = ''
    sortBy.value = 'shot_at'
    sortOrder.value = 'desc'
    searchFilename.value = ''
    applyFilters()
  }

  // 标记单张已入队（乐观更新）
  function markPhotoQueued(photoId: string) {
    const idx = photos.value.findIndex((p) => p.id === photoId)
    if (idx !== -1) {
      // 乐观更新：标记为有描述（处理中状态由 useVlmQueue 管理）
    }
  }

  // 刷新单张照片状态
  async function refreshPhoto(photoId: string) {
    try {
      const resp = await photoApi.photoServiceGetPhotoDetail(photoId)
      const detail = adaptPhotoDetail(resp)
      const idx = photos.value.findIndex((p) => p.id === photoId)
      if (idx !== -1) {
        photos.value[idx] = {
          ...photos.value[idx],
          description: detail.description,
          has_description: detail.has_description,
          shot_at: detail.shot_at,
        }
      }
      if (selectedPhoto.value?.id === photoId) {
        selectedPhoto.value = detail
      }
    } catch (e) {
      console.warn('刷新照片状态失败', e)
    }
  }

  // 修改拍摄时间：写 DB + 写 EXIF（后端处理），成功后刷新详情与列表
  async function updatePhotoShotAt(photoId: string, shotAt: Date): Promise<void> {
    const unixSec = Math.floor(shotAt.getTime() / 1000)
    await photoApi.photoServiceUpdatePhotoShotAt({ shotAt: String(unixSec) }, photoId)
    await refreshPhoto(photoId)
  }

  // 删除照片
  async function deletePhoto(photoId: string): Promise<void> {
    await photoApi.photoServiceDeletePhoto(photoId)
    photos.value = photos.value.filter((p) => p.id !== photoId)
    total.value = Math.max(0, total.value - 1)
    // 删除可能清空某段，刷新导航 offset/count
    fetchSegments()
    if (selectedPhoto.value?.id === photoId) {
      closeDetail()
    }
  }

  // 打开连拍组弹窗：按 burst_group_id 拉取组内成员（档位与当前展示级别一致）
  async function openBurstGroup(groupId: string, coverId: string) {
    if (!groupId) return
    burstModalGroup.value = groupId
    burstModalCoverId.value = coverId
    burstModalMembers.value = []
    burstModalLoading.value = true
    try {
      const resp: ApiSearchPhotosResponse =
        await photoApi.photoServiceSearchPhotos(
          1,
          100,
          undefined, // timeline
          undefined, // tag
          undefined, // keyword
          undefined, // brand
          undefined, // lens
          undefined, // focalMin
          undefined, // focalMax
          undefined, // isoMin
          undefined, // isoMax
          undefined, // shotAtStart
          undefined, // shotAtEnd
          'shot_at', // sortBy：组内按拍摄时间正序浏览
          'asc', // sortOrder
          groupId, // burstGroupId
          currentBurstProfile(), // burstProfile
        )
      burstModalMembers.value = (resp.items ?? []).map(adaptPhotoItem)
    } catch (e) {
      console.warn('获取连拍组成员失败', e)
      burstModalMembers.value = []
    } finally {
      burstModalLoading.value = false
    }
  }

  function closeBurstGroup() {
    burstModalGroup.value = ''
    burstModalMembers.value = []
    burstModalCoverId.value = ''
  }

  // 设为封面：调用后端更新组封面，成功后刷新窗口与弹窗内封面标记
  async function setBurstCover(groupId: string, photoId: string) {
    const { setCover } = useBurstGroups()
    await setCover(groupId, photoId)
    burstModalCoverId.value = photoId
    relocateToStart()
  }

  return {
    photos,
    total,
    windowStart,
    loading,
    loadingDown,
    loadingUp,
    noMoreDown,
    noMoreUp,
    error,
    auxiliaryError,
    segments,
    selectedPhoto,
    showDetail,
    detailLoading,
    stats,
    timelines,
    filterTimeline,
    filterShotAtStart,
    filterShotAtEnd,
    sortBy,
    sortOrder,
    searchFilename,
    burstModalGroup,
    burstModalMembers,
    burstModalCoverId,
    burstModalLoading,
    applyFilters,
    resetFilters,
    relocateTo,
    relocateToStart,
    loadDown,
    loadUp,
    fetchSegments,
    fetchStats,
    fetchTimelines,
    fetchPhotoDetail,
    closeDetail,
    markPhotoQueued,
    refreshPhoto,
    updatePhotoShotAt,
    deletePhoto,
    openBurstGroup,
    closeBurstGroup,
    setBurstCover,
    isLoaded,
  }
}
