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
  NDropdown,
  useMessage,
} from 'naive-ui'
import {
  BulbOutline,
  PlayOutline,
  TrashOutline,
  AddOutline,
  FlashOutline,
  InformationCircleOutline,
} from '@vicons/ionicons5'
import { AGENT_BASE } from '../config'
import SuggestDetailModal from '../components/SuggestDetailModal.vue'
import SuggestManualModal from '../components/SuggestManualModal.vue'

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
  photo_sequence: Array<{ photo_id: string; role_in_narrative: string }>
  error: string
}

// ── 标签映射 ──

const CATEGORY_LABELS: Record<string, string> = {
  editorial_proposal: '编辑提案',
}

const CATEGORY_COLORS: Record<string, string> = {
  editorial_proposal: '#7c3aed',
}

const CATEGORY_ICONS: Record<string, string> = {
  editorial_proposal: '📝',
}

const PIPELINE_LABELS: Record<string, string> = {
  editorial_three_stage: '编辑视角',
}

// ── 状态 ──

const message = useMessage()
const loading = ref(false)
const history = ref<HistoryItem[]>([])
const deletingId = ref<string | null>(null)

// 图片预览
const previewVisible = ref(false)
const previewUrl = ref('')

// 详情 Modal
const detailVisible = ref(false)
const detailItemId = ref<string | null>(null)

// 手动选题 Modal
const manualVisible = ref(false)

// 按钮下拉选项
const suggestDropdownOptions = [
  {
    label: '自动生成选题建议',
    key: 'auto',
    icon: () => h(NIcon, null, { default: () => h(FlashOutline) }),
  },
  {
    label: '手动生成选题建议',
    key: 'manual',
    icon: () => h(NIcon, null, { default: () => h(AddOutline) }),
  },
]

// ── 初始化 ──

onMounted(() => {
  loadHistory()
})

async function loadHistory() {
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/history`)
    if (resp.ok) {
      history.value = await resp.json()
    } else {
      const err = await resp.json().catch(() => ({}))
      message.error(err.detail || '加载历史记录失败')
    }
  } catch {
    message.error('网络请求失败，无法加载历史记录')
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
  hoveredStar.value = null
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

function renderPhotoThumbs(
  photoIds: string[],
  showAll: boolean,
  photoSequence?: Array<{ photo_id: string; role_in_narrative: string }>,
) {
  if (!photoIds || photoIds.length === 0) {
    return h('span', { style: { color: 'var(--n-text-color-3)', fontSize: '13px' } }, '无照片')
  }

  // 构建 photo_id → role_in_narrative 映射
  const roleMap: Record<string, string> = {}
  if (photoSequence && photoSequence.length > 0) {
    for (const s of photoSequence) {
      if (s.photo_id && s.role_in_narrative) {
        roleMap[s.photo_id] = s.role_in_narrative
      }
    }
  }

  const displayIds = showAll ? photoIds : photoIds.slice(0, 3)
  const restCount = showAll ? 0 : Math.max(0, photoIds.length - 3)

  const children: any[] = []

  const thumbChildren: any[] = []
  for (const pid of displayIds) {
    const role = roleMap[pid] || ''
    const wrapChildren: any[] = [
      h('img', { class: 'photo-thumb', src: imageUrl(pid) }),
    ]
    if (role) {
      wrapChildren.push(
        h('span', { class: 'photo-role-tag' }, role),
      )
    }
    thumbChildren.push(
      h('div', {
        class: 'photo-thumb-wrap',
        style: { cursor: 'pointer' },
        onClick: () => openPreview(pid),
        title: role ? `${role} — ${pid}` : pid,
      }, wrapChildren),
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

function getStarState(i: number, currentRating: number, hoverStar: number | null): 'empty' | 'solid' | 'glowing' {
  if (hoverStar === null) {
    return i <= currentRating ? 'glowing' : 'empty'
  }
  if (hoverStar > currentRating) {
    if (i <= currentRating) return 'glowing'
    if (i <= hoverStar) return 'solid'
    return 'empty'
  }
  if (hoverStar < currentRating) {
    return i <= hoverStar ? 'glowing' : 'empty'
  }
  // hoverStar === currentRating: 取消——全部空心
  return 'empty'
}

function getStarTooltip(currentRating: number, hoverStar: number | null): string {
  if (hoverStar !== null) {
    if (hoverStar === currentRating && currentRating > 0) return '取消评分'
    return `${hoverStar} 分`
  }
  return currentRating > 0 ? `${currentRating} 分` : ''
}

const STAR_CHARS: Record<string, string> = {
  empty: '★',
  solid: '★',
  glowing: '★',
}

function renderStars(item: HistoryItem) {
  const stars: any[] = []
  const currentRating = item.rating
  const hoverStar = hoveredStar.value?.itemId === item.id ? hoveredStar.value.star : null

  for (let i = 1; i <= 5; i++) {
    const state = getStarState(i, currentRating, hoverStar)
    stars.push(
      h('span', {
        class: `star ${state}`,
        onClick: (e: MouseEvent) => {
          e.stopPropagation()
          handleRate(item, i)
        },
        onMouseenter: () => {
          hoveredStar.value = { itemId: item.id, star: i }
        },
        title: getStarTooltip(currentRating, hoverStar),
      }, STAR_CHARS[state]),
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

// ── 详情/手动选题 ──

function handleDropdownSelect(key: string) {
  if (key === 'auto') {
    handleRunSuggest()
  } else if (key === 'manual') {
    manualVisible.value = true
  }
}

function handleCardClick(item: HistoryItem) {
  detailItemId.value = item.id
  detailVisible.value = true
}

function handleManualDone(itemId: string) {
  // 手动选题完成，刷新列表并打开详情
  loadHistory()
  detailItemId.value = itemId
  detailVisible.value = true
}

function handleDetailRefreshed() {
  loadHistory()
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
          <NDropdown
            trigger="click"
            :options="suggestDropdownOptions"
            @select="handleDropdownSelect"
          >
            <NButton size="small" type="primary" :loading="loading">
              <template #icon>
                <NIcon><PlayOutline /></NIcon>
              </template>
              生成选题建议
            </NButton>
          </NDropdown>
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
                  AI 将扫描照片库，从编辑视角发现潜在选题，通过三阶段智能分析生成选题建议
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
                  @click.stop="handleCardClick(item)"
                >
                  <template #icon>
                    <NIcon size="16" :component="InformationCircleOutline" />
                  </template>
                  详情
                </NButton>
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
                  :is="renderPhotoThumbs(item.photo_ids, true, item.photo_sequence)"
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

    <!-- 选题详情弹窗 -->
    <SuggestDetailModal
      :item-id="detailItemId"
      :visible="detailVisible"
      @update:visible="detailVisible = $event"
      @refreshed="handleDetailRefreshed"
    />

    <!-- 手动选题弹窗 -->
    <SuggestManualModal
      :visible="manualVisible"
      @update:visible="manualVisible = $event"
      @done="handleManualDone"
    />
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
  transition: border-color 0.15s, box-shadow 0.15s;
}
.history-card:hover {
  border-color: var(--n-color-primary);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
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
  display: inline-block;
  width: 1em;
  text-align: center;
  font-size: 16px;
  transition: color 0.15s, transform 0.1s, text-shadow 0.15s;
  line-height: 1;
  color: var(--n-border-color);
}
.star.solid,
.star.glowing {
  color: #f0a020;
}
.star.glowing {
  transform: scale(1.3);
  text-shadow:
    0 0 4px rgba(240, 160, 32, 0.4),
    0 0 10px rgba(240, 160, 32, 0.3),
    0 0 16px rgba(240, 160, 32, 0.2);
}
.star:hover {
  transform: scale(1.2);
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
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.photo-role-tag {
  display: inline-block;
  font-size: 10px;
  color: var(--n-text-color-3);
  background: var(--n-action-color);
  padding: 1px 6px;
  border-radius: 4px;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  line-height: 1.4;
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
