<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { NButton, NInput, NIcon, NSpin, NEmpty, useMessage } from 'naive-ui'
import { ShuffleOutline, SearchOutline } from '@vicons/ionicons5'
import { AGENT_BASE } from '../config'

interface PhotoItem {
  photo_id: string
  description?: string
}

const props = defineProps<{
  selectedIds: PhotoItem[]
  compact?: boolean
}>()

const emit = defineEmits<{
  'update:selectedIds': [value: PhotoItem[]]
}>()

const message = useMessage()

// 照片存储
const allPhotos = ref<PhotoItem[]>([])
const loading = ref(false)
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 24

// 计算属性
const filteredPhotos = computed(() => {
  if (!searchQuery.value.trim()) return allPhotos.value
  const q = searchQuery.value.toLowerCase()
  return allPhotos.value.filter(p =>
    p.photo_id.toLowerCase().includes(q) ||
    (p.description || '').toLowerCase().includes(q)
  )
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredPhotos.value.length / pageSize)))

const pagedPhotos = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredPhotos.value.slice(start, start + pageSize)
})

const selectedSet = computed(() => new Set(props.selectedIds.map(p => p.photo_id)))

// 初始化加载照片列表
onMounted(() => {
  loadPhotos()
})

async function loadPhotos() {
  loading.value = true
  try {
    // 通过 Go 后端 API 获取全部照片
    let page = 1
    const items: PhotoItem[] = []
    while (true) {
      const resp = await fetch(`/api/v1/photos?page=${page}&page_size=200`)
      if (!resp.ok) break
      const data = await resp.json()
      const list = data.items || data
      if (!Array.isArray(list) || list.length === 0) break
      for (const p of list) {
        items.push({
          photo_id: p.id || '',
          description: (p.description || '').slice(0, 120),
        })
      }
      const tp = data.total_pages || 0
      if (page >= tp) break
      page++
    }
    allPhotos.value = items
    if (items.length === 0) {
      message.warning('未加载到照片，请确认照片库中有数据')
    }
  } catch {
    message.error('加载照片列表失败')
  } finally {
    loading.value = false
  }
}

function togglePhoto(pid: string) {
  const current = [...props.selectedIds]
  const idx = current.findIndex(p => p.photo_id === pid)
  if (idx >= 0) {
    current.splice(idx, 1)
  } else {
    const photo = allPhotos.value.find(p => p.photo_id === pid)
    current.push(photo || { photo_id: pid })
  }
  emit('update:selectedIds', current)
}

async function handleRandomSample() {
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/random-sample`, { method: 'POST' })
    if (resp.ok) {
      const data = await resp.json()
      const ids: Array<{ photo_id: string; description: string }> = data.photos || []
      emit('update:selectedIds', ids.map(p => ({ photo_id: p.photo_id, description: p.description })))
      message.success(`随机选取 ${ids.length} 张照片`)
    }
  } catch {
    message.error('随机采样失败')
  }
}

function imageUrl(uuid: string): string {
  return uuid ? `/api/v1/photos/${uuid}/image` : ''
}

function goToPage(page: number) {
  if (page >= 1 && page <= totalPages.value) {
    currentPage.value = page
  }
}
</script>

<template>
  <div class="photo-selector">
    <!-- 工具栏 -->
    <div class="selector-toolbar">
      <div class="toolbar-left">
        <NInput
          v-model:value="searchQuery"
          size="small"
          placeholder="搜索照片 ID 或描述..."
          clearable
          style="width: 240px"
        >
          <template #prefix>
            <NIcon size="14"><SearchOutline /></NIcon>
          </template>
        </NInput>
        <span class="selected-count">
          已选 <strong>{{ selectedIds.length }}</strong> 张
        </span>
      </div>
      <div class="toolbar-right">
        <NButton size="small" @click="handleRandomSample">
          <template #icon>
            <NIcon size="14"><ShuffleOutline /></NIcon>
          </template>
          随机选取
        </NButton>
      </div>
    </div>

    <!-- 照片网格 -->
    <div v-if="loading" class="selector-loading">
      <NSpin size="medium" />
    </div>
    <div v-else-if="allPhotos.length === 0" class="selector-empty">
      <NEmpty description="暂无照片数据" />
    </div>
    <div v-else class="photo-grid">
      <div
        v-for="photo in pagedPhotos"
        :key="photo.photo_id"
        class="photo-grid-item"
        :class="{ selected: selectedSet.has(photo.photo_id) }"
        @click="togglePhoto(photo.photo_id)"
      >
        <img
          :src="imageUrl(photo.photo_id)"
          :alt="photo.photo_id"
          class="grid-thumb"
          loading="lazy"
        />
        <div class="grid-check">
          <span v-if="selectedSet.has(photo.photo_id)" class="check-mark">✓</span>
        </div>
        <div class="grid-label">{{ photo.photo_id.slice(0, 12) }}</div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="totalPages > 1" class="selector-pagination">
      <NButton size="tiny" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
        上一页
      </NButton>
      <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
      <NButton size="tiny" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">
        下一页
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.photo-selector {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.selector-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.selected-count {
  font-size: 12px;
  color: var(--n-text-color-3);
}
.selector-loading {
  display: flex;
  justify-content: center;
  padding: 40px;
}
.selector-empty {
  padding: 40px;
}
.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
  max-height: 400px;
  overflow-y: auto;
}
.photo-grid-item {
  position: relative;
  cursor: pointer;
  border-radius: 6px;
  overflow: hidden;
  border: 2px solid transparent;
  transition: border-color 0.15s;
}
.photo-grid-item.selected {
  border-color: var(--n-color-primary);
}
.grid-thumb {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}
.grid-check {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--n-color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s;
}
.photo-grid-item.selected .grid-check {
  opacity: 1;
}
.check-mark {
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.grid-label {
  font-size: 10px;
  color: var(--n-text-color-3);
  text-align: center;
  padding: 2px 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selector-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.page-info {
  font-size: 12px;
  color: var(--n-text-color-3);
}
</style>
