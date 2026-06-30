import { ref, computed } from 'vue'
import { API_BASE, DEFAULT_PAGE_SIZE } from '../config'
import type { PhotoListItem, PhotoDetail, PhotoListResponse, PhotoStats } from '../types/photo'

// 全局照片列表状态
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
      const params = new URLSearchParams({
        page: String(page.value),
        page_size: String(pageSize.value),
      })
      if (filterTimeline.value) params.set('timeline', filterTimeline.value)
      if (filterShotAtStart.value) params.set('shot_at_start', filterShotAtStart.value)
      if (filterShotAtEnd.value) params.set('shot_at_end', filterShotAtEnd.value)
      if (searchFilename.value) params.set('keyword', searchFilename.value)
      params.set('sort_by', sortBy.value)
      params.set('sort_order', sortOrder.value)

      const resp = await fetch(`${API_BASE}/photos?${params}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const data: PhotoListResponse = await resp.json()
      photos.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const resp = await fetch(`${API_BASE}/photos/stats`)
      if (!resp.ok) return
      stats.value = await resp.json()
    } catch (e) {
      console.warn('获取统计信息失败', e)
    }
  }

  async function fetchTimelines() {
    try {
      const resp = await fetch(`${API_BASE}/timelines`)
      if (!resp.ok) return
      timelines.value = await resp.json()
    } catch (e) {
      console.warn('获取时间线列表失败', e)
    }
  }

  async function fetchPhotoDetail(id: string) {
    detailLoading.value = true
    try {
      const resp = await fetch(`${API_BASE}/photos/${id}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      selectedPhoto.value = await resp.json()
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
      const resp = await fetch(`${API_BASE}/photos/${photoId}`)
      if (!resp.ok) return
      const detail: PhotoDetail = await resp.json()
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
    const resp = await fetch(`${API_BASE}/photos/${photoId}`, {
      method: 'DELETE',
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({ error: '删除失败' }))
      throw new Error(data.error || `HTTP ${resp.status}`)
    }
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
