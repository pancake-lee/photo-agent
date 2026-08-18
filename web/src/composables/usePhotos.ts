import { ref, computed } from 'vue'
import { DEFAULT_PAGE_SIZE, getApiBase } from '../config'
import { photoApi, timelineApi } from '../backend-sdk-client'
import type { ApiPhotoItem, ApiGetPhotoDetailResponse, ApiSearchPhotosResponse, ApiGetPhotoStatsResponse, ApiListTimelinesResponse } from '../../backend-sdk/api'
import type { PhotoListItem, PhotoDetail, PhotoStats } from '../types/photo'

// ------------------------------------------------------------------ #
// 适配器：SDK camelCase → 现有 snake_case 类型
// ------------------------------------------------------------------ #

function adaptPhotoItem(item: ApiPhotoItem): PhotoListItem {
  return {
    id: item.id ?? '',
    filename: item.filename ?? '',
    file_path: item.filePath ?? '',
    timeline: item.timeline ?? '',
    tags: item.tags ?? '',
    description: item.description ?? '',
    shot_at: item.shotAt ?? null,
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
    imported_at: item.importedAt ?? '',
    has_description: item.hasDescription ?? false,
    thumbnail_url: item.id ? `${getApiBase()}/photos/${item.id}/image` : '',
    has_nef: item.hasNef ?? false,
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
    shot_at: photo?.shotAt ?? null,
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
    imported_at: photo?.importedAt ?? '',
    has_description: photo?.hasDescription ?? false,
    thumbnail_url: photo?.id ? `${getApiBase()}/photos/${photo.id}/image` : '',
    image_url: photo?.id ? `${getApiBase()}/photos/${photo.id}/image` : '',
    description_model: resp.descriptionModel ?? '',
    description_time: resp.descriptionTime ?? '',
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
// 全局状态
// ------------------------------------------------------------------ #

const photos = ref<PhotoListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(DEFAULT_PAGE_SIZE)
const loading = ref(false)
const error = ref<string | null>(null)

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
  const totalPages = computed(() =>
    Math.max(1, Math.ceil(total.value / pageSize.value))
  )

  async function fetchPhotos() {
    loading.value = true
    error.value = null

    try {
      const resp: ApiSearchPhotosResponse = await photoApi.photoServiceSearchPhotos(
        page.value,
        pageSize.value,
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
      )
      photos.value = (resp.items ?? []).map(adaptPhotoItem)
      total.value = parseInt(resp.total ?? '0', 10)
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const resp = await photoApi.photoServiceGetPhotoStats()
      stats.value = adaptStats(resp)
    } catch (e) {
      console.warn('获取统计信息失败', e)
    }
  }

  async function fetchTimelines() {
    try {
      const resp: ApiListTimelinesResponse = await timelineApi.timelineServiceListTimelines()
      timelines.value = resp.timelines ?? []
    } catch (e) {
      console.warn('获取时间线列表失败', e)
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

  function setPage(p: number) {
    page.value = p
    fetchPhotos()
  }

  // 应用筛选（重置到第一页）
  function applyFilters() {
    page.value = 1
    fetchPhotos()
  }

  // 重置所有筛选
  function resetFilters() {
    filterTimeline.value = ''
    filterShotAtStart.value = ''
    filterShotAtEnd.value = ''
    sortBy.value = 'shot_at'
    sortOrder.value = 'desc'
    searchFilename.value = ''
    page.value = 1
    fetchPhotos()
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
      // 更新列表中的对应项
      const idx = photos.value.findIndex((p) => p.id === photoId)
      if (idx !== -1) {
        photos.value[idx] = {
          ...photos.value[idx],
          description: detail.description,
          has_description: detail.has_description,
        }
      }
      // 更新详情（如果打开）
      if (selectedPhoto.value?.id === photoId) {
        selectedPhoto.value = detail
      }
    } catch (e) {
      console.warn('刷新照片状态失败', e)
    }
  }

  // 删除照片
  async function deletePhoto(photoId: string): Promise<void> {
    await photoApi.photoServiceDeletePhoto(photoId)
    // SDK 调用成功即表示删除成功（异常由 SDK 抛出）
    // 从本地列表移除
    photos.value = photos.value.filter((p) => p.id !== photoId)
    total.value = Math.max(0, total.value - 1)
    // 如果正在查看被删除的照片详情，关闭详情
    if (selectedPhoto.value?.id === photoId) {
      closeDetail()
    }
  }

  return {
    photos,
    total,
    page,
    pageSize,
    loading,
    error,
    totalPages,
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
    fetchPhotos,
    fetchStats,
    fetchTimelines,
    fetchPhotoDetail,
    closeDetail,
    setPage,
    applyFilters,
    resetFilters,
    markPhotoQueued,
    refreshPhoto,
    deletePhoto,
  }
}
