import { ref, computed } from 'vue'
import { API_BASE, DEFAULT_PAGE_SIZE } from '../config'
import type { PhotoListItem, PhotoDetail, PhotoListResponse } from '../types/photo'

// 全局照片列表状态
const photos = ref<PhotoListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(DEFAULT_PAGE_SIZE)
const loading = ref(false)
const error = ref<string | null>(null)

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
    } catch {
      // 静默失败
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
    fetchPhotos,
    fetchPhotoDetail,
    closeDetail,
    setPage,
    markPhotoQueued,
    refreshPhoto,
  }
}
