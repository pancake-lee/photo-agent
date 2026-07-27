<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { formatDate } from '../utils/format'
import {
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NButton,
  NIcon,
  NTag,
  NEmpty,
  NSpin,
  NSpace,
  NModal,
  NPopconfirm,
  useMessage,
} from 'naive-ui'
import {
  BulbOutline,
  PlayOutline,
  TrashOutline,
} from '@vicons/ionicons5'
import { AGENT_BASE } from '../config'

// ── 类型定义 ──

interface HistoryItem {
  id: string
  generated_at: string
  total_photos: number
  cluster_count: number
  pipeline: string
  rating: number
  title: string
  angle: string
  rationale: string
  category: string
  photo_ids: string[]
  error: string
}

// ── 标签映射 ──

const CATEGORY_LABELS: Record<string, string> = {
  editorial_proposal: '编辑提案',
  high_freq_ungrouped: '高频未成组',
  temporal_pattern: '时间线规律',
  scarce_quality: '稀缺优质',
}

const CATEGORY_COLORS: Record<string, string> = {
  editorial_proposal: '#7c3aed',
  high_freq_ungrouped: '#f0a020',
  temporal_pattern: '#2080f0',
  scarce_quality: '#18a058',
}

const CATEGORY_ICONS: Record<string, string> = {
  editorial_proposal: '📝',
  high_freq_ungrouped: '🔍',
  temporal_pattern: '📅',
  scarce_quality: '💎',
}

const PIPELINE_LABELS: Record<string, string> = {
  editorial_three_stage: '编辑视角',
  legacy_three_dimension: '三维度分析',
}

// ── 状态 ──

const message = useMessage()
const loading = ref(false)
const history = ref<HistoryItem[]>([])
const deletingId = ref<string | null>(null)

// 图片预览
const previewVisible = ref(false)
const previewUrl = ref('')

// ── 初始化 ──

onMounted(() => {
  loadHistory()
})

async function loadHistory() {
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/history`)
    if (resp.ok) {
      history.value = await resp.json()
    }
  } catch {
    // 静默失败，保持空列表
  }
}

function imageUrl(uuid: string): string {
  return uuid ? `/api/v1/photos/${uuid}/image` : ''
}

// ── 运行选题建议 ──

async function handleRunSuggest() {
  loading.value = true
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    if (resp.ok) {
      const data = await resp.json()
      if (data.error) {
        message.warning(data.error)
      } else if (data.items && data.items.length > 0) {
        message.success(`生成 ${data.items.length} 个选题建议`)
        // 新生成的 topics 插入列表头部
        history.value = [...data.items, ...history.value]
      } else {
        message.info('未发现合适的选题方向')
      }
    } else {
      const err = await resp.json()
      message.error(err.detail || '选题建议生成失败')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '请求失败')
  } finally {
    loading.value = false
  }
}

// ── 打分 ──

async function handleRate(item: HistoryItem, star: number) {
  const newRating = item.rating === star ? 0 : star
  // 乐观更新
  const oldRating = item.rating
  item.rating = newRating
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/history/${item.id}/rating`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: newRating }),
    })
    if (!resp.ok) {
      item.rating = oldRating
      message.error('评分更新失败')
    }
  } catch {
    item.rating = oldRating
    message.error('评分更新失败')
  }
}

// ── 删除 ──

async function handleDelete(item: HistoryItem) {
  deletingId.value = item.id
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/history/${item.id}`, {
      method: 'DELETE',
    })
    if (resp.ok) {
      history.value = history.value.filter(h => h.id !== item.id)
      message.success('已删除')
    } else {
      const err = await resp.json()
      message.error(err.detail || '删除失败')
    }
  } catch {
    message.error('删除失败')
  } finally {
    deletingId.value = null
  }
}

// ── 图片预览 ──

function openPreview(uuid: string) {
  previewUrl.value = imageUrl(uuid)
  previewVisible.value = true
}

// ── 照片缩略图渲染 ──

function renderPhotoThumbs(photoIds: string[], showAll: boolean) {
  if (!photoIds || photoIds.length === 0) {
    return h('span', { style: { color: 'var(--n-text-color-3)', fontSize: '13px' } }, '无照片')
  }

  const displayIds = showAll ? photoIds : photoIds.slice(0, 3)
  const restCount = showAll ? 0 : Math.max(0, photoIds.length - 3)

  const children: any[] = []

  const thumbChildren: any[] = []
  for (const pid of displayIds) {
    thumbChildren.push(
      h('div', {
        class: 'photo-thumb-wrap',
        style: { cursor: 'pointer' },
        onClick: () => openPreview(pid),
        title: pid,
      }, [
        h('img', { class: 'photo-thumb', src: imageUrl(pid) }),
      ]),
    )
  }
  children.push(h('div', { class: 'photo-thumb-row' }, thumbChildren))

  if (restCount > 0) {
    children.push(
      h('span', { class: 'photo-rest-hint' }, `还有 ${restCount} 张`)
    )
  }

  return h('div', { class: 'photo-thumb-list' }, children)
}

// ── 星级渲染 ──

const hoveredStar = ref<{ itemId: string; star: number } | null>(null)

function renderStars(item: HistoryItem) {
  const stars: any[] = []
  const effectiveRating =
    hoveredStar.value?.itemId === item.id ? hoveredStar.value.star : item.rating
  for (let i = 1; i <= 5; i++) {
    const filled = i <= effectiveRating
    stars.push(
      h('span', {
        class: `star${filled ? ' filled' : ''}`,
        onClick: (e: MouseEvent) => {
          e.stopPropagation()
          handleRate(item, i)
        },
        onMouseenter: () => {
          hoveredStar.value = { itemId: item.id, star: i }
        },
        title: `${i} 分`,
      }, filled ? '★' : '☆'),
    )
  }
  return h('span', {
    class: 'star-rating',
    onMouseleave: () => {
      hoveredStar.value = null
    },
  }, stars)
}

// ── 格式化时间 ──

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return formatDate(iso)
  } catch {
    return iso
  }
}
</script>

<template>
  <NLayout>
    <NLayoutHeader bordered>
      <div class="page-header">
        <div class="page-header-left">
          <NIcon size="20"><BulbOutline /></NIcon>
          <h3 class="page-title">主题发现</h3>
          <NTag v-if="history.length" :bordered="false" size="small">
            {{ history.length }} 条记录
          </NTag>
        </div>
        <NSpace>
          <NButton
            size="small"
            type="primary"
            :loading="loading"
            @click="handleRunSuggest"
          >
            <template #icon>
              <NIcon><PlayOutline /></NIcon>
            </template>
            生成选题建议
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <NLayoutContent>
      <div class="page-content">
        <!-- 加载状态 -->
        <div v-if="loading" class="running-state">
          <NSpin size="large" />
          <p>正在分析照片库，生成选题建议...</p>
          <span class="running-hint">需要调用 AI 模型，可能需要几秒到十几秒</span>
        </div>

        <!-- 空状态 -->
        <div v-else-if="history.length === 0" class="empty-state">
          <NEmpty description="暂无选题建议">
            <template #extra>
              <div class="empty-actions">
                <span class="empty-hint">
                  AI 将扫描照片库，从编辑视角发现潜在选题，支持三阶段智能分析和三维度属性回退
                </span>
                <NButton size="small" type="primary" @click="handleRunSuggest">
                  生成选题建议
                </NButton>
              </div>
            </template>
          </NEmpty>
        </div>

        <!-- 历史列表 -->
        <div v-else class="history-list">
          <div
            v-for="item in history"
            :key="item.id"
            class="history-card"
          >
            <!-- 卡片头部：标题 + 分类 + 星级 + 删除 -->
            <div class="card-header-row">
              <div class="card-header-left">
                <span class="card-title">{{ item.title }}</span>
                <NTag
                  size="tiny"
                  :bordered="false"
                  :color="{ color: CATEGORY_COLORS[item.category] || '#999', textColor: '#fff' }"
                >
                  {{ CATEGORY_ICONS[item.category] || '' }} {{ CATEGORY_LABELS[item.category] || item.category }}
                </NTag>
              </div>
              <div class="card-header-right">
                <component :is="renderStars(item)" />
                <NButton
                  size="tiny"
                  text
                  :loading="deletingId === item.id"
                  @click.stop
                >
                  <NPopconfirm @positive-click="() => handleDelete(item)">
                    <template #trigger>
                      <NIcon size="16" :component="TrashOutline" />
                    </template>
                    确定删除这条选题记录？
                  </NPopconfirm>
                </NButton>
              </div>
            </div>

            <!-- 卡片元信息 -->
            <div class="card-meta">
              <span class="meta-item">{{ formatTime(item.generated_at) }}</span>
              <span class="meta-sep">|</span>
              <NTag size="tiny" :bordered="false">
                {{ PIPELINE_LABELS[item.pipeline] || item.pipeline }}
              </NTag>
              <span class="meta-sep">|</span>
              <span class="meta-item">照片总数：{{ item.total_photos }}</span>
              <span class="meta-sep">|</span>
              <span class="meta-item">已有聚类：{{ item.cluster_count }} 个</span>
            </div>

            <!-- 卡片正文 -->
            <div class="card-body">
              <div class="card-field">
                <span class="field-label">发布角度</span>
                <p class="field-value">{{ item.angle }}</p>
              </div>
              <div class="card-field">
                <span class="field-label">选题理由</span>
                <p class="field-value field-rationale">{{ item.rationale }}</p>
              </div>

              <div class="card-photos" v-if="item.photo_ids && item.photo_ids.length > 0">
                <div class="photos-header">
                  <span class="field-label">
                    推荐照片（{{ item.photo_ids.length }} 张）
                  </span>
                </div>
                <component
                  :is="renderPhotoThumbs(item.photo_ids, true)"
                />
              </div>
            </div>

            <!-- 错误信息 -->
            <div v-if="item.error" class="history-error">
              {{ item.error }}
            </div>
          </div>
        </div>
      </div>
    </NLayoutContent>

    <!-- 图片预览弹窗 -->
    <NModal
      v-model:show="previewVisible"
      preset="card"
      title="照片预览"
      style="width: 90vw; max-width: 1200px;"
    >
      <div class="preview-container">
        <img :src="previewUrl" class="preview-image" />
      </div>
    </NModal>
  </NLayout>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.page-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.page-title {
  margin: 0;
  font-size: 16px;
}
.page-content {
  padding: 16px 24px;
}

/* 加载状态 */
.running-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 400px;
  color: var(--n-text-color-2);
}
.running-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
}

/* 空状态 */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}
.empty-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.empty-hint {
  font-size: 13px;
  color: var(--n-text-color-3);
  max-width: 400px;
  text-align: center;
  line-height: 1.6;
}

/* 历史列表 */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-card {
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  padding: 14px 16px;
}

/* 卡片头部 */
.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.card-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
}

/* 卡片元信息 */
.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.meta-item {
  white-space: nowrap;
}
.meta-sep {
  color: var(--n-border-color);
}

.history-error {
  color: var(--n-text-color-3);
  font-size: 13px;
  padding: 8px 0;
}

/* 卡片正文 */
.card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.card-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.star-rating {
  display: inline-flex;
  gap: 2px;
  cursor: pointer;
}
.star {
  font-size: 16px;
  color: var(--n-border-color);
  transition: color 0.15s, transform 0.1s;
  line-height: 1;
}
.star:hover {
  transform: scale(1.2);
}
.star.filled {
  color: #f0a020;
}

.field-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
}
.field-value {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--n-text-color);
}
.field-rationale {
  font-size: 13px;
  color: var(--n-text-color-2);
}

/* 照片区域 */
.card-photos {
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--n-border-color);
}
.photos-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

/* 照片缩略图 */
.photo-thumb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.photo-thumb-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.photo-thumb-wrap {
  display: inline-block;
  flex-shrink: 0;
}
.photo-thumb {
  width: 80px;
  height: 80px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--n-border-color);
  transition: transform 0.15s;
}
.photo-thumb:hover {
  transform: scale(1.08);
}
.photo-rest-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
  padding: 2px 8px;
}

/* 图片预览 */
.preview-container {
  display: flex;
  justify-content: center;
}
.preview-image {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 8px;
}
</style>
