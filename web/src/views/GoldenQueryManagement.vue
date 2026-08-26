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
  NInput,
  useMessage,
} from 'naive-ui'
import {
  TrashOutline,
  EyeOutline,
  BookmarkOutline,
  DownloadOutline,
  CloudUploadOutline,
  BarChartOutline,
  AddOutline,
} from '@vicons/ionicons5'
import { getAgentBase, getApiBase } from '../config'
import PhotoThumbList from '../components/PhotoThumbList.vue'
import PhotoPreviewModal from '../components/PhotoPreviewModal.vue'
import PhotoPickOverlay from '../components/PhotoPickOverlay.vue'
import SelectedPhotoList, { type SelectedPhotoItem } from '../components/SelectedPhotoList.vue'
import { photoApi } from '../backend-sdk-client'
import {
  createPickSession,
  readPickSession,
  clearPickSession,
  type PickedPhoto,
} from '../utils/photoPickSession'

type Granularity = 'photo' | 'fine' | 'coarse'

interface GoldenPhotoRef {
  photo_id: string
  filename: string
  uuid: string
  granularity?: Granularity
  burst_group_id?: string
  burst_count?: number
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
  golden_id: string
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

// 新建用例
const createVisible = ref(false)
const creating = ref(false)
const createQuery = ref('')
const createCategory = ref('')
const createNotes = ref('')
const createPhotos = ref<GoldenPhotoRef[]>([])

// 选图覆盖层：打开时隐藏新建弹窗（草稿留在 ref 里），完成后恢复
const pickVisible = ref(false)
const PICK_SOURCE = 'golden-create'

/** 新建弹窗表单草稿（存进选图会话，F5 刷新后可恢复） */
interface CreateDraft {
  query: string
  category: string
  notes: string
}

// 行级单条评估：正在评估的用例 ID
const rowEvaluatingId = ref('')

// 评估明细中追加多余命中
const appendSelected = ref<string[]>([])
const appending = ref(false)

/** FastAPI 错误既可能是 detail 字符串，也可能是校验错误数组，统一转成一行文本 */
async function errText(resp: Response, fallback: string): Promise<string> {
  try {
    const body = await resp.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d) => d.msg || JSON.stringify(d)).join('；')
    }
  } catch {
    // 响应不是 JSON，走兜底文案
  }
  return fallback
}

// ── 图片预览 ──

const previewShow = ref(false)
const previewImg = ref('')

function openPreview(uuid: string) {
  previewImg.value = `${getApiBase()}/photos/${uuid}/image`
  previewShow.value = true
}

// ── 数据加载 ──

async function fetchItems() {
  loading.value = true
  try {
    const resp = await fetch(`${getAgentBase()}/golden-queries`)
    if (resp.ok) {
      items.value = await resp.json()
    }
  } catch (e) {
    console.warn('加载黄金用例失败', e)
    message.error('加载黄金用例失败')
  } finally {
    loading.value = false
  }
}

// ── 删除 ──

async function handleDelete(id: string) {
  try {
    const resp = await fetch(`${getAgentBase()}/golden-queries/${id}`, {
      method: 'DELETE',
    })
    if (resp.ok) {
      items.value = items.value.filter((it) => it.id !== id)
      message.success('已删除')
    } else {
      message.error(await errText(resp, '删除失败'))
    }
  } catch (e) {
    console.warn('删除黄金用例失败', e)
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
    relevant_photos: relevant_photos.map(({ photo_id, filename }) => ({
      photo_id,
      filename,
    })),
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
    const resp = await fetch(`${getAgentBase()}/golden-queries/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (resp.ok) {
      const result = await resp.json()
      message.success(`已导入 ${result.imported} 条用例`)
      await fetchItems()
    } else {
      message.error(await errText(resp, '导入失败'))
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '导入失败，请检查文件格式')
  } finally {
    importing.value = false
    target.value = ''
  }
}

// ── 新建用例 ──

function openCreate() {
  createQuery.value = ''
  createCategory.value = ''
  createNotes.value = ''
  createPhotos.value = []
  createVisible.value = true
}

// ── 选图覆盖层（复用图片管理完整交互）──

/** 打开覆盖层：草稿与已选写入会话（防刷新丢失），新建弹窗先隐藏 */
function openPickOverlay() {
  createPickSession({
    source: PICK_SOURCE,
    selected: createPhotos.value.map((p) => ({
      photo_id: p.photo_id,
      filename: p.filename,
      uuid: p.uuid,
      granularity: p.granularity || 'photo',
      burst_group_id: p.burst_group_id,
      burst_count: p.burst_count,
    })),
    draft: {
      query: createQuery.value,
      category: createCategory.value,
      notes: createNotes.value,
    } satisfies CreateDraft,
  })
  createVisible.value = false
  pickVisible.value = true
}

/** 完成选择：恢复弹窗并合并新选择，连拍信息仅用于已选区展示 */
function onPickConfirm(picked: PickedPhoto[]) {
  clearPickSession()
  pickVisible.value = false
  createVisible.value = true
  createPhotos.value = picked.map((p) => ({
    photo_id: p.photo_id,
    filename: p.filename,
    uuid: p.uuid,
    granularity: p.granularity || 'photo',
    burst_group_id: p.burst_group_id,
    burst_count: p.burst_count,
  }))
}

/** 保存前展开仍以连拍组形式存在的条目；连拍精选后的条目已经是单张。 */
async function expandCreatePhotos(): Promise<GoldenPhotoRef[]> {
  const expanded: GoldenPhotoRef[] = []
  for (const photo of createPhotos.value) {
    const isUncuratedGroup = Boolean(
      photo.burst_group_id && (photo.burst_count || 0) > 1 && photo.granularity !== 'photo',
    )
    if (!isUncuratedGroup) {
      expanded.push({ photo_id: photo.photo_id, filename: photo.filename, uuid: photo.uuid })
      continue
    }
    const response = await photoApi.photoServiceSearchPhotos(
      1, 100, undefined, undefined, undefined, undefined, undefined, undefined,
      undefined, undefined, undefined, undefined, undefined, 'shot_at', 'asc',
      photo.burst_group_id, photo.granularity,
    )
    for (const member of response.items || []) {
      if (member.id) {
        const filename = member.filename || member.id
        expanded.push({
          photo_id: filename.replace(/\.[^.]+$/, ''),
          filename,
          uuid: member.id,
        })
      }
    }
  }
  return expanded
}

/** 取消：恢复弹窗与原选择，覆盖层结果丢弃 */
function onPickCancel() {
  clearPickSession()
  pickVisible.value = false
  createVisible.value = true
}



async function handleCreate() {
  if (!createQuery.value.trim()) {
    message.warning('请填写查询文本')
    return
  }
  if (createPhotos.value.length === 0) {
    message.warning('请至少选择一张期望照片')
    return
  }
  creating.value = true
  try {
    const expandedPhotos = await expandCreatePhotos()
    if (expandedPhotos.length === 0) {
      message.error('已选连拍组没有可加入的照片')
      return
    }
    const resp = await fetch(`${getAgentBase()}/golden-queries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query_text: createQuery.value.trim(),
        relevant_photos: expandedPhotos.map((p) => ({
          photo_id: p.photo_id,
          filename: p.filename,
          uuid: p.uuid,
        })),
        category: createCategory.value.trim(),
        notes: createNotes.value.trim(),
      }),
    })
    if (resp.ok) {
      message.success('已新建黄金用例')
      createVisible.value = false
      await fetchItems()
    } else {
      message.error(await errText(resp, '新建失败'))
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '新建请求失败')
  } finally {
    creating.value = false
  }
}

// ── 评估 ──

/** 运行一次评估，golden_id 为空时评估全部用例 */
async function runEvaluate(goldenId?: string): Promise<EvalResult | null> {
  const resp = await fetch(`${getAgentBase()}/golden-queries/evaluate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(goldenId ? { golden_id: goldenId } : {}),
  })
  if (!resp.ok) {
    message.error(await errText(resp, '评估失败'))
    return null
  }
  return await resp.json()
}

async function handleEvaluate() {
  if (items.value.length === 0) {
    message.warning('没有黄金用例可评估')
    return
  }
  evaluating.value = true
  evalModalVisible.value = true
  evalResult.value = null
  try {
    const result = await runEvaluate()
    if (result) {
      evalResult.value = result
    } else {
      evalModalVisible.value = false
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '评估请求失败')
    evalModalVisible.value = false
  } finally {
    evaluating.value = false
  }
}

/** 行级单条评估：直接展开该条的命中/遗漏/多余命中明细 */
async function handleEvaluateRow(row: GoldenQuery) {
  if (rowEvaluatingId.value) return
  rowEvaluatingId.value = row.id
  try {
    const result = await runEvaluate(row.id)
    const detail = result?.details?.[0]
    if (detail) {
      showEvalDetail(detail)
    } else if (result) {
      message.warning('该用例没有返回评估结果')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '评估请求失败')
  } finally {
    rowEvaluatingId.value = ''
  }
}

function showEvalDetail(row: EvalDetail) {
  evalDetailItem.value = row
  appendSelected.value = []
  evalDetailVisible.value = true
}

/** 单条复评后指标会变，用明细重算汇总，避免概览与明细对不上 */
function recalcEvalSummary() {
  const result = evalResult.value
  if (!result || result.details.length === 0) return
  const avg = (pick: (d: EvalDetail) => number) =>
    result.details.reduce((sum, d) => sum + pick(d), 0) / result.details.length
  result.precision_at_k = avg((d) => d.precision)
  result.recall_at_k = avg((d) => d.recall)
  result.mrr = avg((d) => d.mrr)
}

// ── 把确认后的多余命中加入用例 ──

function toggleAppendPhoto(photoId: string) {
  const idx = appendSelected.value.indexOf(photoId)
  if (idx >= 0) {
    appendSelected.value.splice(idx, 1)
  } else {
    appendSelected.value.push(photoId)
  }
}

async function handleAppendPhotos() {
  const detail = evalDetailItem.value
  if (!detail || !detail.golden_id || appendSelected.value.length === 0) return

  const photos = detail.miss_ids
    .filter((p) => appendSelected.value.includes(p.photo_id))
    .map((p) => ({
      photo_id: p.photo_id,
      filename: p.filename,
      uuid: p.uuid,
    }))

  appending.value = true
  try {
    const resp = await fetch(
      `${getAgentBase()}/golden-queries/${detail.golden_id}/photos`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photos }),
      },
    )
    if (!resp.ok) {
      message.error(await errText(resp, '加入用例失败'))
      return
    }
    message.success(`已加入 ${photos.length} 张照片，正在重新评估`)
    appendSelected.value = []
    await fetchItems()

    // 追加后立刻复评，让明细与列表反映最新用例
    const result = await runEvaluate(detail.golden_id)
    const updated = result?.details?.[0]
    if (updated) {
      evalDetailItem.value = updated
      if (evalResult.value) {
        const idx = evalResult.value.details.findIndex((d) => d.golden_id === updated.golden_id)
        if (idx >= 0) {
          evalResult.value.details[idx] = updated
          recalcEvalSummary()
        }
      }
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '加入用例请求失败')
  } finally {
    appending.value = false
  }
}

// ── 初始化 ──

onMounted(() => {
  fetchItems()
  // 刷新恢复：选图过程中 F5 后会话仍在，恢复草稿与已选，重开覆盖层继续选
  const session = readPickSession<CreateDraft>(PICK_SOURCE)
  if (session && !session.done) {
    const draft = session.draft
    if (draft) {
      createQuery.value = draft.query
      createCategory.value = draft.category
      createNotes.value = draft.notes
    }
    createPhotos.value = session.selected as GoldenPhotoRef[]
    pickVisible.value = true
  }
})

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
    width: 120,
    render(row: GoldenQuery) {
      const base = `${row.relevant_photos.length} 张`
      return base
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
    width: 160,
    render(row: GoldenQuery) {
      return h(NSpace, null, {
        default: () => [
          h(
            NButton,
            { size: 'tiny', onClick: () => showDetail(row) },
            { icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) },
          ),
          h(
            NButton,
            {
              size: 'tiny',
              type: 'primary',
              title: '评估该条用例',
              loading: rowEvaluatingId.value === row.id,
              disabled: !!rowEvaluatingId.value && rowEvaluatingId.value !== row.id,
              onClick: (e: MouseEvent) => {
                e.stopPropagation()
                handleEvaluateRow(row)
              },
            },
            { icon: () => h(NIcon, null, { default: () => h(BarChartOutline) }) },
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
          <NButton size="small" @click="openCreate">
            <template #icon>
              <NIcon><AddOutline /></NIcon>
            </template>
            新建
          </NButton>
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
                  <span class="empty-hint">新建用例、在对话页保存，或导入已有的 JSON 文件</span>
                  <NSpace>
                    <NButton size="small" type="primary" @click="openCreate">新建用例</NButton>
                    <NButton size="small" @click="triggerImport">导入 JSON</NButton>
                  </NSpace>
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
          <PhotoThumbList
            :photos="detailItem.relevant_photos"
            auto-fit
            empty-text="无关联照片"
            @preview="openPreview"
          />
        </div>
      </div>
    </NModal>

    <!-- 新建用例弹窗 -->
    <NModal
      v-model:show="createVisible"
      preset="card"
      title="新建黄金用例"
      style="width: 760px; max-width: 95vw;"
    >
      <div class="create-body">
        <div class="detail-field">
          <span class="detail-label">查询文本</span>
          <NInput v-model:value="createQuery" placeholder="例如：佛像和人的合照" />
        </div>
        <div class="create-row">
          <div class="detail-field create-row-item">
            <span class="detail-label">分类</span>
            <NInput v-model:value="createCategory" placeholder="可留空" />
          </div>
          <div class="detail-field create-row-item">
            <span class="detail-label">备注</span>
            <NInput v-model:value="createNotes" placeholder="可留空" />
          </div>
        </div>

        <div class="detail-field">
          <span class="detail-label">选择期望照片</span>
          <NButton size="small" @click="openPickOverlay">
            选择照片（进入图片管理选图）
          </NButton>
        </div>

        <div v-if="createPhotos.length" class="detail-field">
          <span class="detail-label">已选照片 ({{ createPhotos.length }})</span>
          <span class="selected-photo-hint">连拍集合会把所有子图加入黄金用例；如需精选，请进入连拍组操作。</span>
          <SelectedPhotoList
            :items="createPhotos as SelectedPhotoItem[]"
            @update:items="createPhotos = $event"
            @preview="openPreview"
          />
        </div>
      </div>

      <template #footer>
        <NSpace justify="end">
          <NButton size="small" @click="createVisible = false">取消</NButton>
          <NButton size="small" type="primary" :loading="creating" @click="handleCreate">
            保存
          </NButton>
        </NSpace>
      </template>
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
          <PhotoThumbList :photos="evalDetailItem.hit_ids" empty-text="无命中" @preview="openPreview" />
        </div>

        <!-- 遗漏 -->
        <div class="eval-section">
          <div class="eval-section-title">
            ❌ 遗漏 ({{ evalDetailItem.remaining_ids.length }} 张)
            <span class="eval-section-sub">标注为相关但未检索到的照片</span>
          </div>
          <PhotoThumbList :photos="evalDetailItem.remaining_ids" empty-text="无遗漏" @preview="openPreview" />
        </div>

        <!-- 未命中（多余命中）：确认后可加入当前用例 -->
        <div class="eval-section">
          <div class="eval-section-title">
            ⬜ 未命中 ({{ evalDetailItem.miss_ids.length }} 张)
            <span class="eval-section-sub">检索到了但用例未标注的照片，确认正确后可加入用例</span>
          </div>
          <PhotoThumbList
            v-if="!evalDetailItem.golden_id || evalDetailItem.miss_ids.length === 0"
            :photos="evalDetailItem.miss_ids"
            empty-text="无多余"
            @preview="openPreview"
          />
          <template v-else>
            <div class="miss-grid">
              <div
                v-for="photo in evalDetailItem.miss_ids"
                :key="photo.photo_id"
                class="miss-item"
                :class="{ selected: appendSelected.includes(photo.photo_id) }"
                @click="toggleAppendPhoto(photo.photo_id)"
              >
                <img class="miss-thumb" :src="`${getApiBase()}/photos/${photo.uuid}/image`" />
                <span
                  class="miss-preview"
                  title="查看大图"
                  @click.stop="openPreview(photo.uuid)"
                >
                  <NIcon size="12"><EyeOutline /></NIcon>
                </span>
                <span v-if="appendSelected.includes(photo.photo_id)" class="miss-check">✓</span>
                <div class="miss-label">{{ photo.filename }}</div>
              </div>
            </div>
            <div class="miss-actions">
              <NButton
                size="small"
                type="primary"
                :loading="appending"
                :disabled="appendSelected.length === 0"
                @click="handleAppendPhotos"
              >
                加入用例（{{ appendSelected.length }}）
              </NButton>
              <span class="miss-hint">点击缩略图选择，加入后自动复评</span>
            </div>
          </template>
        </div>
      </div>
    </NModal>

    <!-- 图片预览弹窗 -->
    <PhotoPreviewModal v-model:show="previewShow" :image-url="previewImg" />

    <!-- 选图覆盖层：复用图片管理完整交互 -->
    <PhotoPickOverlay
      :show="pickVisible"
      :preselected="createPhotos.map((p) => ({ photo_id: p.photo_id, filename: p.filename, uuid: p.uuid, granularity: p.granularity, burst_group_id: p.burst_group_id, burst_count: p.burst_count }))"
      @confirm="onPickConfirm"
      @cancel="onPickCancel"
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
.detail-photo-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.detail-group-title {
  font-size: 12px;
  color: var(--n-text-color-3);
}

/* ── 新建用例 ── */
.create-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 68vh;
  overflow-y: auto;
}
.create-row {
  display: flex;
  gap: 16px;
}
.create-row-item {
  flex: 1;
}
.selected-photo-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
}
.picked-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
}
.picked-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.picked-thumb {
  width: 40px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--n-border-color);
  cursor: pointer;
}
.picked-name {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

/* ── 多余命中选择 ── */
.miss-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
}
.miss-item {
  position: relative;
  cursor: pointer;
  border: 2px solid transparent;
  border-radius: 6px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.miss-item.selected {
  border-color: var(--n-color-target);
}
.miss-thumb {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  display: block;
}
.miss-preview {
  position: absolute;
  top: 4px;
  left: 4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.miss-check {
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
.miss-label {
  font-size: 10px;
  color: var(--n-text-color-3);
  text-align: center;
  padding: 2px 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.miss-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.miss-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
}
</style>
