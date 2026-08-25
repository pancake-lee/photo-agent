<script setup lang="ts">
/**
 * GoldenPhotoPicker — 黄金用例期望照片选择器
 *
 * 从 Go 后端拉取全部照片，按文件名搜索、分页展示，多选后回传
 * { photo_id, filename, uuid }。photo_id 使用去后缀文件名，
 * 与评估匹配口径一致；uuid 用于展示缩略图。
 */
import { ref, computed, onMounted } from 'vue'
import { NInput, NIcon, NSpin, NEmpty, NButton, useMessage } from 'naive-ui'
import { SearchOutline } from '@vicons/ionicons5'
import { getApiBase } from '../config'

interface PickedPhoto {
  photo_id: string
  filename: string
  uuid: string
}

const props = defineProps<{
  selected: PickedPhoto[]
}>()

const emit = defineEmits<{
  'update:selected': [value: PickedPhoto[]]
}>()

const message = useMessage()

const allPhotos = ref<PickedPhoto[]>([])
const loading = ref(false)
const keyword = ref('')
const currentPage = ref(1)
const pageSize = 24

/** 去掉扩展名，与后端 _normalize_ext 口径保持一致 */
function stripExt(name: string): string {
  return name.replace(/\.[^.]+$/, '')
}

const filteredPhotos = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return allPhotos.value
  return allPhotos.value.filter((p) => p.filename.toLowerCase().includes(q))
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredPhotos.value.length / pageSize)))

const pagedPhotos = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredPhotos.value.slice(start, start + pageSize)
})

const selectedSet = computed(() => new Set(props.selected.map((p) => p.photo_id)))

async function loadPhotos() {
  loading.value = true
  try {
    const items: PickedPhoto[] = []
    let page = 1
    while (true) {
      const resp = await fetch(`${getApiBase()}/photos?page=${page}&page_size=200`)
      if (!resp.ok) break
      const data = await resp.json()
      const list = data.items || data
      if (!Array.isArray(list) || list.length === 0) break
      for (const p of list) {
        const filename = stripExt(p.filename || '')
        if (!filename) continue
        items.push({ photo_id: filename, filename, uuid: p.id || '' })
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

function togglePhoto(photo: PickedPhoto) {
  const current = [...props.selected]
  const idx = current.findIndex((p) => p.photo_id === photo.photo_id)
  if (idx >= 0) {
    current.splice(idx, 1)
  } else {
    current.push({ ...photo })
  }
  emit('update:selected', current)
}

function imageUrl(uuid: string): string {
  return uuid ? `${getApiBase()}/photos/${uuid}/image` : ''
}

function goToPage(page: number) {
  if (page >= 1 && page <= totalPages.value) currentPage.value = page
}

onMounted(loadPhotos)
</script>

<template>
  <div class="picker">
    <div class="picker-toolbar">
      <NInput
        v-model:value="keyword"
        size="small"
        placeholder="按文件名搜索..."
        clearable
        style="width: 240px"
        @update:value="currentPage = 1"
      >
        <template #prefix>
          <NIcon size="14"><SearchOutline /></NIcon>
        </template>
      </NInput>
      <span class="picker-count">已选 <strong>{{ selected.length }}</strong> 张</span>
    </div>

    <div v-if="loading" class="picker-loading">
      <NSpin size="medium" />
    </div>
    <div v-else-if="filteredPhotos.length === 0" class="picker-empty">
      <NEmpty :description="allPhotos.length === 0 ? '暂无照片数据' : '没有匹配的照片'" />
    </div>
    <div v-else class="picker-grid">
      <div
        v-for="photo in pagedPhotos"
        :key="photo.photo_id"
        class="picker-item"
        :class="{ selected: selectedSet.has(photo.photo_id) }"
        @click="togglePhoto(photo)"
      >
        <img class="picker-thumb" :src="imageUrl(photo.uuid)" :alt="photo.filename" loading="lazy" />
        <span v-if="selectedSet.has(photo.photo_id)" class="picker-check">✓</span>
        <div class="picker-label">{{ photo.filename }}</div>
      </div>
    </div>

    <div v-if="totalPages > 1" class="picker-pagination">
      <NButton size="tiny" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
        上一页
      </NButton>
      <span class="picker-page-info">{{ currentPage }} / {{ totalPages }}</span>
      <NButton size="tiny" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">
        下一页
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.picker-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
}
.picker-count {
  font-size: 12px;
  color: var(--n-text-color-3);
}
.picker-loading,
.picker-empty {
  display: flex;
  justify-content: center;
  padding: 32px;
}
.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.picker-item {
  position: relative;
  cursor: pointer;
  border: 2px solid transparent;
  border-radius: 6px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.picker-item.selected {
  border-color: var(--n-color-target);
}
.picker-thumb {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}
.picker-check {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--n-color-target);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.picker-label {
  font-size: 10px;
  color: var(--n-text-color-3);
  text-align: center;
  padding: 2px 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.picker-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.picker-page-info {
  font-size: 12px;
  color: var(--n-text-color-3);
}
</style>
