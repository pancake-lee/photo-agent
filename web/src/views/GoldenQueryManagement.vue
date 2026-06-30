<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
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
  NDataTable,
  NPopconfirm,
  NModal,
  useMessage,
} from 'naive-ui'
import {
  TrashOutline,
  EyeOutline,
  BookmarkOutline,
  DownloadOutline,
  CloudUploadOutline,
  BarChartOutline,
  ImageOutline,
} from '@vicons/ionicons5'
import { AGENT_BASE } from '../config'

interface GoldenPhotoRef {
  photo_id: string
  filename: string
  uuid: string
}

interface GoldenQuery {
  id: string
  query_text: string
  relevant_photos: GoldenPhotoRef[]
  category: string
  notes: string
  created_at: string
}

// ── 评估相关类型 ──

interface EvalPhotoItem {
  photo_id: string
  filename: string
  uuid: string
}

interface EvalDetail {
  question: string
  precision: number
  recall: number
  mrr: number
  hits: number
  retrieved: number
  relevant: number
  effective_k: number
  hit_ids: EvalPhotoItem[]
  miss_ids: EvalPhotoItem[]
  remaining_ids: EvalPhotoItem[]
}

interface EvalResult {
  precision_at_k: number
  recall_at_k: number
  mrr: number
  total: number
  precision_k: number
  details: EvalDetail[]
}

const message = useMessage()
const items = ref<GoldenQuery[]>([])
const loading = ref(false)
const importing = ref(false)

// 详情弹窗
const detailVisible = ref(false)
const detailItem = ref<GoldenQuery | null>(null)

// 评估状态
const evaluating = ref(false)
const evalModalVisible = ref(false)
const evalResult = ref<EvalResult | null>(null)

// 评估明细弹窗
const evalDetailVisible = ref(false)
const evalDetailItem = ref<EvalDetail | null>(null)

// ── 图片预览 ──

const previewVisible = ref(false)
const previewUrl = ref('')

function openPreview(url: string) {
  previewUrl.value = url
  previewVisible.value = true
}

function imageUrl(uuid: string): string {
  return uuid ? `/api/v1/photos/${uuid}/image` : ''
}

// ── 照片缩略图列表组件（h 函数渲染）──

function renderPhotoList(photos: EvalPhotoItem[], emptyText: string) {
  if (!photos || photos.length === 0) {
    return h('span', { style: { color: 'var(--n-text-color-3)', fontSize: '13px' } }, emptyText)
  }
  const showThumbs = photos.slice(0, 3)
  const rest = photos.slice(3)
  const thumbChildren: any[] = []
  const nameChildren: any[] = []

  // 前 3 张缩略图
  for (const p of showThumbs) {
    const url = imageUrl(p.uuid)
    thumbChildren.push(
      h('span', {
        class: 'photo-thumb-wrap',
        style: { cursor: 'pointer' },
        onClick: () => url && openPreview(url),
        title: p.filename,
      }, [
        url
          ? h('img', { class: 'photo-thumb', src: url })
          : h(NIcon, { size: 24 }, { default: () => h(ImageOutline) }),
      ]),
    )
  }
  // 超过 3 张显示文件名
  for (const p of rest) {
    nameChildren.push(
      h('span', {
        class: 'photo-name-tag',
        style: { cursor: 'pointer' },
        onClick: () => {
          const url = imageUrl(p.uuid)
          if (url) openPreview(url)
        },
      }, p.filename),
    )
  }

  return h('div', { class: 'photo-thumb-list' }, [
    thumbChildren.length > 0 ? h('div', { class: 'photo-thumb-row' }, thumbChildren) : null,
    nameChildren.length > 0 ? h('div', { class: 'photo-thumb-row' }, nameChildren) : null,
  ].filter(Boolean))
}

// ── 数据加载 ──

async function fetchItems() {
  loading.value = true
  try {
    const resp = await fetch(`${AGENT_BASE}/golden-queries`)
    if (resp.ok) {
      items.value = await resp.json()
    }
  } catch {
    message.error('加载黄金用例失败')
  } finally {
    loading.value = false
  }
}

// ── 删除 ──

async function handleDelete(id: string) {
  try {
    const resp = await fetch(`${AGENT_BASE}/golden-queries/${id}`, {
      method: 'DELETE',
    })
    if (resp.ok) {
      items.value = items.value.filter((it) => it.id !== id)
      message.success('已删除')
    } else {
      const err = await resp.json()
      message.error(err.detail || '删除失败')
    }
  } catch {
    message.error('删除失败')
  }
}

// ── 详情 ──

function showDetail(item: GoldenQuery) {
  detailItem.value = item
  detailVisible.value = true
}

// ── 导出 ──

function handleExport() {
  const exportData = items.value.map(({ query_text, relevant_photos, category, notes }) => ({
    query_text,
    // 导出时剥掉 uuid（UUID 是环境数据，迁移后可能变化）
    relevant_photos: relevant_photos.map(({ photo_id, filename }) => ({ photo_id, filename })),
    category,
    notes,
  }))
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `golden_queries_${new Date().toISOString().slice(0, 10)}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  message.success(`已导出 ${exportData.length} 条用例`)
}

// ── 导入 ──

const fileInput = ref<HTMLInputElement | null>(null)

function triggerImport() {
  fileInput.value?.click()
}

async function handleImport(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  importing.value = true
  try {
    const text = await file.text()
    const data = JSON.parse(text)
    if (!Array.isArray(data)) {
      message.error('文件格式错误：应为 JSON 数组')
      return
    }
    const resp = await fetch(`${AGENT_BASE}/golden-queries/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (resp.ok) {
      const result = await resp.json()
      message.success(`已导入 ${result.imported} 条用例`)
      await fetchItems()
    } else {
      const err = await resp.json()
      message.error(err.detail || '导入失败')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '导入失败，请检查文件格式')
  } finally {
    importing.value = false
    target.value = ''
  }
}

// ── 评估 ──

async function handleEvaluate() {
  if (items.value.length === 0) {
    message.warning('没有黄金用例可评估')
    return
  }
  evaluating.value = true
  evalModalVisible.value = true
  evalResult.value = null
  try {
    const resp = await fetch(`${AGENT_BASE}/golden-queries/evaluate`, {
      method: 'POST',
    })
    if (resp.ok) {
      evalResult.value = await resp.json()
    } else {
      const err = await resp.json()
      message.error(err.detail || '评估失败')
      evalModalVisible.value = false
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '评估请求失败')
    evalModalVisible.value = false
  } finally {
    evaluating.value = false
  }
}

function showEvalDetail(row: EvalDetail) {
  evalDetailItem.value = row
  evalDetailVisible.value = true
}

// ── 初始化 ──

onMounted(() => fetchItems())

// ── 表格列定义 ──

const columns = [
  {
    title: '查询文本',
    key: 'query_text',
    ellipsis: { tooltip: true },
    width: 300,
  },
  {
    title: '关联照片',
    key: 'relevant_photos',
    width: 90,
    render(row: GoldenQuery) {
      return `${row.relevant_photos.length} 张`
    },
  },
  {
    title: '分类',
    key: 'category',
    width: 90,
    render(row: GoldenQuery) {
      return row.category || '—'
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
    render(row: GoldenQuery) {
      if (!row.created_at) return '—'
      return formatDate(row.created_at)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 140,
    render(row: GoldenQuery) {
      return h(NSpace, null, {
        default: () => [
          h(
            NButton,
            { size: 'tiny', onClick: () => showDetail(row) },
            { icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) },
          ),
          h(
            NPopconfirm,
            { onPositiveClick: () => handleDelete(row.id) },
            {
              trigger: () =>
                h(
                  NButton,
                  { size: 'tiny', type: 'error' },
                  { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) },
                ),
              default: () => '确认删除该黄金用例？',
            },
          ),
        ],
      })
    },
  },
]

// ── 评估结果明细列（第一列可点击）──

const evalColumns = [
  {
    title: '查询',
    key: 'question',
    ellipsis: { tooltip: true },
    width: 220,
    render(row: EvalDetail) {
      return h('span', {
        class: 'eval-question-link',
        onClick: () => showEvalDetail(row),
      }, row.question)
    },
  },
  {
    title: 'P@10',
    key: 'precision',
    width: 90,
    render(row: EvalDetail) {
      const pct = (row.precision * 100).toFixed(0) + '%'
      if (row.effective_k && row.effective_k !== evalResult.value?.precision_k) {
        return pct + ` (P@${row.effective_k})`
      }
      return pct
    },
  },
  {
    title: 'Recall',
    key: 'recall',
    width: 60,
    render(row: EvalDetail) { return (row.recall * 100).toFixed(0) + '%' },
  },
  {
    title: 'MRR',
    key: 'mrr',
    width: 60,
    render(row: EvalDetail) { return (row.mrr * 100).toFixed(0) + '%' },
  },
  {
    title: '命中/检索/相关',
    key: 'hits',
    width: 110,
    render(row: EvalDetail) { return `${row.hits}/${row.retrieved}/${row.relevant}` },
  },
]
</script>

<template>
  <NLayout>
    <NLayoutHeader bordered>
      <div class="page-header">
        <div class="page-header-left">
          <NIcon size="20"><BookmarkOutline /></NIcon>
          <h3 class="page-title">黄金用例管理</h3>
          <NTag :bordered="false" size="small">
            {{ items.length }} 条用例
          </NTag>
        </div>
        <NSpace>
          <NButton
            size="small"
            type="primary"
            :loading="evaluating"
            :disabled="items.length === 0"
            @click="handleEvaluate"
          >
            <template #icon>
              <NIcon><BarChartOutline /></NIcon>
            </template>
            评估
          </NButton>
          <NButton
            size="small"
            :disabled="items.length === 0"
            @click="handleExport"
          >
            <template #icon>
              <NIcon><DownloadOutline /></NIcon>
            </template>
            导出
          </NButton>
          <NButton
            size="small"
            :loading="importing"
            @click="triggerImport"
          >
            <template #icon>
              <NIcon><CloudUploadOutline /></NIcon>
            </template>
            导入
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <NLayoutContent>
      <input
        ref="fileInput"
        type="file"
        accept=".json"
        style="display: none"
        @change="handleImport"
      />

      <div class="page-content">
        <NSpin :show="loading">
          <div v-if="!loading && items.length === 0" class="empty-state">
            <NEmpty description="暂无黄金查询用例">
              <template #extra>
                <div class="empty-actions">
                  <span class="empty-hint">在对话页保存用例，或导入已有的 JSON 文件</span>
                  <NButton size="small" @click="triggerImport">
                    导入 JSON
                  </NButton>
                </div>
              </template>
            </NEmpty>
          </div>

          <NDataTable
            v-else
            :columns="columns"
            :data="items"
            :row-key="(row: GoldenQuery) => row.id"
            :single-line="false"
            size="small"
            flex-height
            :row-props="(row: GoldenQuery) => ({ style: 'cursor: pointer;', onClick: () => showDetail(row) })"
            style="height: calc(100vh - 120px)"
          />
        </NSpin>
      </div>
    </NLayoutContent>

    <!-- 黄金用例详情弹窗 -->
    <NModal
      v-model:show="detailVisible"
      preset="card"
      title="黄金用例详情"
      style="width: 640px; max-width: 90vw;"
    >
      <div v-if="detailItem" class="detail-body">
        <div class="detail-field">
          <span class="detail-label">查询文本</span>
          <span class="detail-value">{{ detailItem.query_text }}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">分类</span>
          <span class="detail-value">{{ detailItem.category || '未分类' }}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">备注</span>
          <span class="detail-value">{{ detailItem.notes || '无' }}</span>
        </div>
        <div class="detail-field">
          <span class="detail-label">创建时间</span>
          <span class="detail-value">
            {{ detailItem.created_at ? formatDate(detailItem.created_at) : '—' }}
          </span>
        </div>
        <div class="detail-field">
          <span class="detail-label">关联照片 ({{ detailItem.relevant_photos.length }})</span>
          <div class="photo-thumb-list">
            <!-- 前 3 张缩略图 -->
            <div class="photo-thumb-row">
              <span
                v-for="p in detailItem.relevant_photos.slice(0, 3)"
                :key="p.photo_id"
                class="photo-thumb-wrap"
                :style="{ cursor: p.uuid ? 'pointer' : 'default' }"
                :title="p.filename"
                @click="p.uuid && openPreview(imageUrl(p.uuid))"
              >
                <img v-if="p.uuid" class="photo-thumb" :src="imageUrl(p.uuid)" />
                <span v-else class="photo-name-tag">{{ p.filename }}</span>
              </span>
            </div>
            <!-- 超过 3 张的部分作为文件名标签 -->
            <div
              v-if="detailItem.relevant_photos.length > 3"
              class="photo-thumb-row"
            >
              <span
                v-for="p in detailItem.relevant_photos.slice(3)"
                :key="p.photo_id"
                class="photo-name-tag"
                :class="{ 'photo-name-clickable': !!p.uuid }"
                @click="p.uuid && openPreview(imageUrl(p.uuid))"
              >{{ p.filename }}</span>
            </div>
          </div>
        </div>
      </div>
    </NModal>

    <!-- 评估结果弹窗 -->
    <NModal
      v-model:show="evalModalVisible"
      preset="card"
      title="黄金用例评估结果"
      style="width: 820px; max-width: 95vw;"
      :mask-closable="!evaluating"
    >
      <div class="eval-table-hint">
      随着时间推移，图库的变化，用例评估结果也会变化，主要表现为分数下降，是相关的照片增加导致的。<br>
      请点击条目查看详情，确认遗漏/未命中的具体照片。<br>
      遗漏：可能因为新照片得分更高，把目标照片挤出输出列表了。<br>
      未命中：可能是新照片被检索到了，但“当初”目标集合没有记录，程序误以为是错误照片。<br>
      </div>
      <div v-if="evaluating" class="eval-loading">
        <NSpin size="large" />
        <p>正在运行 {{ items.length }} 条黄金用例评估...</p>
      </div>

      <div v-else-if="evalResult" class="eval-result">
        <div class="eval-summary">
          <div class="eval-metric">
            <span class="eval-metric-value">{{ (evalResult.precision_at_k * 100).toFixed(1) }}%</span>
            <span class="eval-metric-label">P@{{ evalResult.precision_k }}</span>
          </div>
          <div class="eval-metric">
            <span class="eval-metric-value">{{ (evalResult.recall_at_k * 100).toFixed(1) }}%</span>
            <span class="eval-metric-label">Recall</span>
          </div>
          <div class="eval-metric">
            <span class="eval-metric-value">{{ (evalResult.mrr * 100).toFixed(1) }}%</span>
            <span class="eval-metric-label">MRR</span>
          </div>
          <div class="eval-metric">
            <span class="eval-metric-value">{{ evalResult.total }}</span>
            <span class="eval-metric-label">用例数</span>
          </div>
        </div>

        <div class="eval-table-hint">点击查询名称查看命中/遗漏详情</div>

        <NDataTable
          :columns="evalColumns"
          :data="evalResult.details"
          :row-key="(row: EvalDetail) => row.question"
          :single-line="false"
          size="small"
          :max-height="400"
          :row-props="(row: EvalDetail) => ({ style: 'cursor: pointer;', onClick: () => showEvalDetail(row) })"
          style="margin-top: 8px;"
        />
      </div>
    </NModal>

    <!-- 评估明细弹窗 -->
    <NModal
      v-model:show="evalDetailVisible"
      preset="card"
      :title="evalDetailItem?.question || '评估明细'"
      style="width: 720px; max-width: 95vw;"
    >
      <div v-if="evalDetailItem" class="eval-detail-body">
        <!-- 指标 -->
        <div class="eval-detail-metrics">
          <span class="eval-detail-badge">
            P@{{ evalDetailItem.effective_k || 10 }}: {{ (evalDetailItem.precision * 100).toFixed(0) }}%
          </span>
          <span class="eval-detail-badge">Recall: {{ (evalDetailItem.recall * 100).toFixed(0) }}%</span>
          <span class="eval-detail-badge">MRR: {{ (evalDetailItem.mrr * 100).toFixed(0) }}%</span>
          <span class="eval-detail-badge">检索 {{ evalDetailItem.retrieved }} / 相关 {{ evalDetailItem.relevant }}</span>
        </div>

        <!-- 命中 -->
        <div class="eval-section">
          <div class="eval-section-title">
            ✅ 命中 ({{ evalDetailItem.hits }} 张)
            <span class="eval-section-sub">检索结果中属于正确答案的照片</span>
          </div>
          <component :is="renderPhotoList(evalDetailItem.hit_ids, '无命中')" />
        </div>

        <!-- 遗漏 -->
        <div class="eval-section">
          <div class="eval-section-title">
            ❌ 遗漏 ({{ evalDetailItem.remaining_ids.length }} 张)
            <span class="eval-section-sub">标注为相关但未检索到的照片</span>
          </div>
          <component :is="renderPhotoList(evalDetailItem.remaining_ids, '无遗漏')" />
        </div>

        <!-- 未命中 -->
        <div class="eval-section">
          <div class="eval-section-title">
            ⬜ 未命中 ({{ evalDetailItem.miss_ids.length }} 张)
            <span class="eval-section-sub">检索到了但与查询不相关的照片</span>
          </div>
          <component :is="renderPhotoList(evalDetailItem.miss_ids, '无多余')" />
        </div>
      </div>
    </NModal>

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
}
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.detail-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.detail-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
}
.detail-value {
  font-size: 14px;
  color: var(--n-text-color);
}
.photo-id-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.photo-name-clickable {
  cursor: pointer;
}

/* ── 评估结果 ── */
.eval-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 32px;
  color: var(--n-text-color-3);
}
.eval-summary {
  display: flex;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--n-border-color);
}
.eval-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.eval-metric-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--n-color-primary);
}
.eval-metric-label {
  font-size: 12px;
  color: var(--n-text-color-3);
}
.eval-table-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-top: 12px;
}
.eval-question-link {
  color: var(--n-color-target);
  cursor: pointer;
}
.eval-question-link:hover {
  text-decoration: underline;
}

/* ── 评估明细 ── */
.eval-detail-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.eval-detail-metrics {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.eval-detail-badge {
  padding: 4px 12px;
  border-radius: 4px;
  background: var(--n-color-embedded);
  font-size: 13px;
  font-weight: 500;
}
.eval-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.eval-section-title {
  font-size: 14px;
  font-weight: 600;
}
.eval-section-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--n-text-color-3);
  margin-left: 8px;
}

/* ── 照片缩略图 ── */
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
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--n-border-color);
  transition: transform 0.15s;
}
.photo-thumb:hover {
  transform: scale(1.08);
}
.photo-name-tag {
  display: inline-block;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--n-color-target);
  border-radius: 3px;
  background: var(--n-color-embedded);
}
.photo-name-tag:hover {
  text-decoration: underline;
}

/* ── 图片预览 ── */
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
