<script setup lang="ts">
import { ref, h } from 'vue'
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
  useMessage,
} from 'naive-ui'
import {
  BulbOutline,
  PlayOutline,
} from '@vicons/ionicons5'
import { AGENT_BASE } from '../config'

// ── 类型定义 ──

interface SuggestionItem {
  title: string
  angle: string
  rationale: string
  category: string
  photo_ids: string[]
}

interface SuggestResult {
  generated_at: string
  total_photos: number
  cluster_count: number
  candidates_found: number
  suggestions: SuggestionItem[]
  error: string
}

// ── 分类标签映射 ──

const CATEGORY_LABELS: Record<string, string> = {
  high_freq_ungrouped: '高频未成组',
  temporal_pattern: '时间线规律',
  scarce_quality: '稀缺优质',
}

const CATEGORY_COLORS: Record<string, string> = {
  high_freq_ungrouped: '#f0a020',
  temporal_pattern: '#2080f0',
  scarce_quality: '#18a058',
}

const CATEGORY_ICONS: Record<string, string> = {
  high_freq_ungrouped: '🔍',
  temporal_pattern: '📅',
  scarce_quality: '💎',
}

// ── 状态 ──

const message = useMessage()
const loading = ref(false)
const result = ref<SuggestResult | null>(null)
const expandedCards = ref<Set<number>>(new Set())

// 图片预览
const previewVisible = ref(false)
const previewUrl = ref('')

function imageUrl(uuid: string): string {
  return uuid ? `/api/v1/photos/${uuid}/image` : ''
}

// ── 运行选题建议 ──

async function handleRunSuggest() {
  loading.value = true
  result.value = null
  expandedCards.value = new Set()
  try {
    const resp = await fetch(`${AGENT_BASE}/suggest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    if (resp.ok) {
      const data = await resp.json()
      result.value = data
      if (data.error) {
        message.warning(data.error)
      } else if (data.suggestions.length > 0) {
        message.success(`生成 ${data.suggestions.length} 个选题建议`)
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

// ── 展开/收起 ──

function toggleExpand(idx: number) {
  const next = new Set(expandedCards.value)
  if (next.has(idx)) {
    next.delete(idx)
  } else {
    next.add(idx)
  }
  expandedCards.value = next
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

  // 缩略图
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

  // 剩余数量提示
  if (restCount > 0) {
    children.push(
      h('span', { class: 'photo-rest-hint' }, `还有 ${restCount} 张`)
    )
  }

  return h('div', { class: 'photo-thumb-list' }, children)
}

// ── 格式化时间 ──

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN')
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
          <NTag v-if="result" :bordered="false" size="small">
            {{ result.suggestions.length }} 个建议
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
        <NSpin :show="loading">
          <div v-if="loading" class="running-state">
            <NSpin size="large" />
            <p>正在分析照片库，生成选题建议...</p>
            <span class="running-hint">需要调用 AI 模型，可能需要几秒到十几秒</span>
          </div>

          <!-- 空状态 -->
          <div v-else-if="!result" class="empty-state">
            <NEmpty description="暂无选题建议">
              <template #extra>
                <div class="empty-actions">
                  <span class="empty-hint">
                    AI 将扫描照片库，从「高频未成组」「时间线规律」「稀缺优质」三个维度发现潜在选题
                  </span>
                  <NButton size="small" type="primary" @click="handleRunSuggest">
                    生成选题建议
                  </NButton>
                </div>
              </template>
            </NEmpty>
          </div>

          <!-- 结果为空 -->
          <div v-else-if="result.suggestions.length === 0" class="empty-state">
            <NEmpty :description="result.error || '未发现合适的选题方向'">
              <template #extra>
                <div class="empty-actions">
                  <span class="empty-hint">建议上传更多照片或运行聚类后再试</span>
                  <NButton size="small" type="primary" @click="handleRunSuggest">
                    重新分析
                  </NButton>
                </div>
              </template>
            </NEmpty>
          </div>

          <!-- 结果展示 -->
          <div v-else class="suggest-results">
            <!-- 摘要 -->
            <div class="result-meta">
              <span class="meta-item">
                生成时间：{{ formatTime(result.generated_at) }}
              </span>
              <span class="meta-sep">|</span>
              <span class="meta-item">照片总数：{{ result.total_photos }}</span>
              <span class="meta-sep">|</span>
              <span class="meta-item">已有聚类：{{ result.cluster_count }} 个</span>
              <span class="meta-sep">|</span>
              <span class="meta-item">分析候选：{{ result.candidates_found }} 个</span>
            </div>

            <!-- 建议卡片列表 -->
            <div class="suggest-cards">
              <div
                v-for="(s, idx) in result.suggestions"
                :key="idx"
                class="suggest-card"
              >
                <div class="card-header">
                  <div class="card-title-row">
                    <span class="card-index">{{ idx + 1 }}.</span>
                    <span class="card-title">{{ s.title }}</span>
                    <NTag
                      size="tiny"
                      :bordered="false"
                      :color="{ color: CATEGORY_COLORS[s.category] || '#999', textColor: '#fff' }"
                    >
                      {{ CATEGORY_ICONS[s.category] || '' }} {{ CATEGORY_LABELS[s.category] || s.category }}
                    </NTag>
                  </div>
                </div>

                <div class="card-body">
                  <div class="card-field">
                    <span class="field-label">发布角度</span>
                    <p class="field-value">{{ s.angle }}</p>
                  </div>
                  <div class="card-field">
                    <span class="field-label">选题理由</span>
                    <p class="field-value field-rationale">{{ s.rationale }}</p>
                  </div>

                  <!-- 照片区域 -->
                  <div class="card-photos" v-if="s.photo_ids && s.photo_ids.length > 0">
                    <div class="photos-header" @click="toggleExpand(idx)">
                      <span class="field-label">
                        推荐照片（{{ s.photo_ids.length }} 张）
                      </span>
                      <NButton size="tiny" text>
                        {{ expandedCards.has(idx) ? '收起' : '展开查看' }}
                      </NButton>
                    </div>
                    <component
                      :is="renderPhotoThumbs(s.photo_ids, expandedCards.has(idx))"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </NSpin>
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

/* 结果区域 */
.suggest-results {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--n-text-color-3);
  padding: 8px 0;
  flex-wrap: wrap;
}
.meta-item {
  white-space: nowrap;
}
.meta-sep {
  color: var(--n-border-color);
}

/* 卡片列表 */
.suggest-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: calc(100vh - 180px);
  overflow-y: auto;
}

.suggest-card {
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  padding: 16px;
  transition: border-color 0.15s;
}
.suggest-card:hover {
  border-color: var(--n-color-primary);
}

.card-header {
  margin-bottom: 12px;
}
.card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-index {
  font-size: 18px;
  font-weight: 700;
  color: var(--n-color-primary);
  min-width: 24px;
}
.card-title {
  font-size: 16px;
  font-weight: 600;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.card-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--n-border-color);
}
.photos-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  cursor: pointer;
}

/* 照片缩略图（复用组图发现样式） */
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
