<script setup lang="ts">
import { computed, ref, onMounted, h } from 'vue'
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
import PhotoPreviewModal from '../components/PhotoPreviewModal.vue'
import PhotoPickOverlay from '../components/PhotoPickOverlay.vue'
import GoldenQueryDetailModal from '../components/GoldenQueryDetailModal.vue'
import GoldenQueryCreateModal from '../components/GoldenQueryCreateModal.vue'
import GoldenQueryEvaluationModals from '../components/GoldenQueryEvaluationModals.vue'
import { photoApi } from '../backend-sdk-client'
import {
  createPickSession,
  readPickSession,
  clearPickSession,
  type PickedPhoto,
} from '../utils/photoPickSession'
import type { EvalDetail, EvalResult, GoldenPhotoRef, GoldenQuery } from '../types/goldenQuery'

const message = useMessage()
const items = ref<GoldenQuery[]>([])
const loading = ref(false)
const importing = ref(false)

// 详情弹窗
const detailVisible = ref(false)
const detailItem = ref<GoldenQuery | null>(null)
const detailSaving = ref(false)
const detailQuery = ref('')
const detailCategory = ref('')
const detailNotes = ref('')
const detailPhotos = ref<GoldenPhotoRef[]>([])

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
const DETAIL_PICK_SOURCE = 'golden-detail-edit'
const pickMode = ref<'create' | 'detail' | null>(null)

const pickerPreselected = computed(() => {
  const photos = pickMode.value === 'detail' ? detailPhotos.value : createPhotos.value
  return photos.map((photo) => ({
    photo_id: photo.photo_id,
    filename: photo.filename,
    uuid: photo.uuid,
    granularity: photo.granularity,
    burst_group_id: photo.burst_group_id,
    burst_count: photo.burst_count,
  }))
})

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
  detailQuery.value = item.query_text
  detailCategory.value = item.category
  detailNotes.value = item.notes
  detailPhotos.value = item.relevant_photos.map((photo) => ({ ...photo }))
  detailVisible.value = true
}

function cancelDetailEdit() {
  detailPhotos.value = []
  detailVisible.value = false
}

function removeDetailPhoto(photoId: string) {
  detailPhotos.value = detailPhotos.value.filter((photo) => photo.photo_id !== photoId)
}

function openDetailPhotoPicker() {
  createPickSession({
    source: DETAIL_PICK_SOURCE,
    selected: detailPhotos.value.map((photo) => ({
      photo_id: photo.photo_id,
      filename: photo.filename,
      uuid: photo.uuid,
      granularity: 'photo',
    })),
  })
  pickMode.value = 'detail'
  detailVisible.value = false
  pickVisible.value = true
}

async function saveDetailEdit() {
  if (!detailItem.value) return
  if (!detailQuery.value.trim()) {
    message.warning('请填写查询文本')
    return
  }
  if (detailPhotos.value.length === 0) {
    message.warning('请至少保留一张关联照片')
    return
  }

  detailSaving.value = true
  try {
    const resp = await fetch(`${getAgentBase()}/golden-queries/${detailItem.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query_text: detailQuery.value.trim(),
        category: detailCategory.value.trim(),
        notes: detailNotes.value.trim(),
        relevant_photos: detailPhotos.value.map(({ photo_id, filename, uuid }) => ({
          photo_id,
          filename,
          uuid,
        })),
      }),
    })
    if (!resp.ok) {
      message.error(await errText(resp, '保存失败'))
      return
    }
    const updated: GoldenQuery = await resp.json()
    const index = items.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) items.value[index] = updated
    detailItem.value = updated
    detailPhotos.value = updated.relevant_photos.map((photo) => ({ ...photo }))
    message.success('已保存')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    detailSaving.value = false
  }
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
  pickMode.value = 'create'
  createVisible.value = false
  pickVisible.value = true
}

/** 完成选择：恢复弹窗并合并新选择，连拍信息仅用于已选区展示 */
function onPickConfirm(picked: PickedPhoto[]) {
  clearPickSession()
  pickVisible.value = false
  if (pickMode.value === 'detail') {
    detailPhotos.value = picked.map((p) => ({
      photo_id: p.photo_id,
      filename: p.filename,
      uuid: p.uuid,
    }))
    detailVisible.value = true
    pickMode.value = null
    return
  }
  createVisible.value = true
  pickMode.value = null
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
  if (pickMode.value === 'detail') {
    detailVisible.value = true
    pickMode.value = null
    return
  }
  createVisible.value = true
  pickMode.value = null
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

    <GoldenQueryDetailModal v-model:show="detailVisible" :item="detailItem" :saving="detailSaving" :query="detailQuery" :category="detailCategory" :notes="detailNotes" :photos="detailPhotos" @update:query="detailQuery = $event" @update:category="detailCategory = $event" @update:notes="detailNotes = $event" @preview="openPreview" @remove="removeDetailPhoto" @add="openDetailPhotoPicker" @cancel="cancelDetailEdit" @save="saveDetailEdit" />

    <GoldenQueryCreateModal v-model:show="createVisible" :creating="creating" :query="createQuery" :category="createCategory" :notes="createNotes" :photos="createPhotos" @update:query="createQuery = $event" @update:category="createCategory = $event" @update:notes="createNotes = $event" @update:photos="createPhotos = $event" @preview="openPreview" @pick="openPickOverlay" @create="handleCreate" />

    <GoldenQueryEvaluationModals
      v-model:result-visible="evalModalVisible"
      v-model:detail-visible="evalDetailVisible"
      :evaluating="evaluating"
      :result="evalResult"
      :item-count="items.length"
      :columns="evalColumns"
      :detail="evalDetailItem"
      :appending="appending"
      :append-selected="appendSelected"
      :image-base="getApiBase()"
      @show-detail="showEvalDetail"
      @preview="openPreview"
      @toggle-append="toggleAppendPhoto"
      @append="handleAppendPhotos"
    />

    <!-- 图片预览弹窗 -->
    <PhotoPreviewModal v-model:show="previewShow" :image-url="previewImg" />

    <!-- 选图覆盖层：复用图片管理完整交互 -->
    <PhotoPickOverlay
      :show="pickVisible"
      :preselected="pickerPreselected"
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
.eval-question-link {
  color: var(--n-color-target);
  cursor: pointer;
}
.eval-question-link:hover {
  text-decoration: underline;
}

</style>
