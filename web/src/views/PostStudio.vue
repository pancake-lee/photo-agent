<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NLayout, NLayoutContent, NLayoutHeader,
  NButton, NInput, NRadioGroup, NRadioButton,
  NSelect, NSpace, NEmpty, NIcon, NTag, NSpin, NModal, NCheckbox,
  useMessage,
} from 'naive-ui'
import { AddOutline, CreateOutline } from '@vicons/ionicons5'
import draggable from 'vuedraggable'
import { getApiBase, getAgentBase } from '../config'
import { photoApi } from '../backend-sdk-client'
import PhotoDetail from '../components/PhotoDetail.vue'
import PhotoCard from '../components/PhotoCard.vue'
import BurstGroupModal from '../components/BurstGroupModal.vue'
import type { ApiPhotoItem, ApiGetPhotoDetailResponse, ApiSearchPhotosResponse } from '../../backend-sdk/api'
import type { PhotoDetail as PhotoDetailType, PhotoListItem } from '../types/photo'
import { useVlmQueue } from '../composables/useVlmQueue'
import { useEmbedQueue } from '../composables/useEmbedQueue'

const route = useRoute()
const message = useMessage()

interface PhotoItem {
  photo_id: string
  filename: string
  description: string
  image_url: string
  burst_group_id: string
  burst_cover: boolean
  burst_count: number
}

// 图文工坊照片列表条目：单张照片 或 连拍组（组内成员懒加载后常驻）
type StudioItem =
  | { kind: 'photo'; key: string; photo: PhotoItem }
  | { kind: 'group'; key: string; groupId: string; cover: PhotoItem; members: PhotoItem[] }

const styleOptions = [
  { label: '文艺', value: 'literary' },
  { label: '纪实', value: 'documentary' },
  { label: '轻松', value: 'casual' },
  { label: '攻略', value: 'guide' },
]

// 提示词模式的默认文本，用户可在此基础上修改
const DEFAULT_PROMPT = '介绍一下这次出行的行程，重点写印象最深的场景'

const items = ref<StudioItem[]>([])
const title = ref('')
const content = ref('')
const style = ref('casual')
const source = ref('self_select')
const mode = ref<'prompt' | 'draft'>('prompt')
const promptText = ref(DEFAULT_PROMPT)
const draftInput = ref('')
const isGenerating = ref(false)
const isLoading = ref(false)
const isPhotosLoading = ref(false)
const draftId = ref('')

const showPhotoPicker = ref(false)
const photoPickerQuery = ref('')
const photoPickerResults = ref<PhotoItem[]>([])
const photoPickerSelected = ref<Set<string>>(new Set())
const isPickerLoading = ref(false)

// 照片详情抽屉（复用图片管理的 PhotoDetail）
const showDetail = ref(false)
const detailLoading = ref(false)
const selectedDetail = ref<PhotoDetailType | null>(null)
const { enqueuePhoto: enqueueVlmPhoto, describeProcessingIds } = useVlmQueue()
const { enqueuePhoto: enqueueEmbedPhoto, embedProcessingIds } = useEmbedQueue()
const detailDescribeProcessing = computed(() => !!selectedDetail.value && describeProcessingIds.value.has(selectedDetail.value.id))
const detailEmbedProcessing = computed(() => !!selectedDetail.value && embedProcessingIds.value.has(selectedDetail.value.id))

async function handleDetailDescribe(photoId: string) {
  try {
    await enqueueVlmPhoto(photoId)
    message.info('已开始重新生成描述')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '重新生成描述失败')
  }
}

async function handleDetailEmbed(photoId: string) {
  try {
    await enqueueEmbedPhoto(photoId)
    message.info('已开始重新生成 Embedding')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '重新生成 Embedding 失败')
  }
}

// 连拍组浏览弹窗（复用图片管理 BurstGroupModal 的 curate 模式）
const showGroupModal = ref(false)
const groupModalGroupId = ref('')
const groupModalCoverId = ref('')
const groupModalMembers = ref<{ id: string; thumbnail_url: string; filename: string }[]>([])
const curatingIndex = ref(-1)

// 扁平化照片列表（连拍组展开为成员），用于生成文案 / 详情导航
const flatPhotos = computed(() =>
  items.value.flatMap((it) => (it.kind === 'photo' ? [it.photo] : it.members)),
)

const hasPhotos = computed(() => items.value.length > 0)
const canSave = computed(() => hasPhotos.value || title.value.trim() || content.value.trim())

const promptOrDraft = computed<string>({
  get: () => (mode.value === 'prompt' ? promptText.value : draftInput.value),
  set: (v: string) => {
    if (mode.value === 'prompt') promptText.value = v
    else draftInput.value = v
  },
})

const generateDisabled = computed(() => (
  mode.value === 'draft' && !draftInput.value.trim()
))

function imageUrl(id: string): string {
  return id ? `${getApiBase()}/photos/${id}/image` : ''
}

function originalImageUrl(id: string): string {
  return id ? `${getApiBase()}/photos/${id}/image?size=original&download=1` : ''
}

function photoToItem(p: ApiPhotoItem): PhotoItem {
  return {
    photo_id: p.id ?? '',
    filename: p.filename ?? '',
    description: p.description ?? '',
    image_url: p.id ? imageUrl(p.id) : '',
    burst_group_id: p.burstGroupId ?? '',
    burst_cover: p.burstCover ?? false,
    burst_count: p.burstCount ?? 0,
  }
}

// 单张照片详情 → PhotoItem
async function fetchPhoto(id: string): Promise<PhotoItem | null> {
  try {
    const resp = await photoApi.photoServiceGetPhotoDetail(id)
    return resp.photo ? photoToItem(resp.photo) : null
  } catch {
    return null
  }
}

// 按 burst_group_id 拉取组内成员（按拍摄时间正序）
async function fetchGroupMembers(groupId: string): Promise<PhotoItem[]> {
  // 组 id 形如 burst_fine_xxx / burst_coarse_xxx，据此决定过滤哪一档分组列
  const profile = groupId.startsWith('burst_coarse_') ? 'coarse' : 'fine'
  try {
    const resp: ApiSearchPhotosResponse = await photoApi.photoServiceSearchPhotos(
      1, 100,
      undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined,
      'shot_at', 'asc',
      groupId, profile,
    )
    return (resp.items ?? []).map(photoToItem)
  } catch {
    return []
  }
}

function adaptUnixSec(s?: string): string | null {
  if (!s || s === '0') return null
  const sec = Number(s)
  if (!Number.isFinite(sec) || sec <= 0) return null
  return new Date(sec * 1000).toISOString()
}

// 详情抽屉数据适配：SDK 响应 → PhotoDetail（与 usePhotos 的 adaptPhotoDetail 同构）
function toPhotoDetail(resp: ApiGetPhotoDetailResponse): PhotoDetailType {
  const p = resp.photo
  const id = p?.id ?? ''
  return {
    id,
    filename: p?.filename ?? '',
    file_path: p?.filePath ?? '',
    timeline: p?.timeline ?? '',
    tags: p?.tags ?? '',
    description: p?.description ?? '',
    shot_at: adaptUnixSec(p?.shotAt),
    width: p?.width ?? 0,
    height: p?.height ?? 0,
    brand: p?.brand ?? '',
    model: p?.model ?? '',
    lens: p?.lens ?? '',
    focal_length: p?.focalLength ?? '',
    aperture: p?.aperture ?? '',
    iso: p?.iso ?? 0,
    exposure_time: p?.exposureTime ?? '',
    latitude: p?.latitude ?? null,
    longitude: p?.longitude ?? null,
    altitude: p?.altitude ?? null,
    imported_at: adaptUnixSec(p?.importedAt) ?? '',
    has_description: p?.hasDescription ?? false,
    thumbnail_url: id ? imageUrl(id) : '',
    image_url: id ? imageUrl(id) : '',
    description_model: resp.descriptionModel ?? '',
    description_time: resp.descriptionTime ?? '',
    ai_health_status: p?.aiHealthStatus ?? 'pending',
    ai_health_reason: p?.aiHealthReason ?? '',
    vlm_status: p?.vlmStatus ?? 'pending',
    vlm_reason: p?.vlmReason ?? '',
    embedding_status: p?.embeddingStatus ?? 'pending',
    embedding_description_time: p?.embeddingDescriptionTime ?? '',
  }
}

// 上/下一张导航列表：图文工坊用的是「已选帖子的照片列表」
const photoNavList = computed(() => flatPhotos.value.map((p) => ({ id: p.photo_id, label: p.filename })))

// 条目 → PhotoCard 所需的 PhotoListItem（EXIF 等字段留空，工坊内不展示）
function toCardPhoto(it: StudioItem): PhotoListItem {
  if (it.kind === 'group') {
    return {
      id: it.cover.photo_id,
      filename: it.cover.filename,
      file_path: '',
      timeline: '',
      tags: '',
      description: '',
      shot_at: null,
      width: 0,
      height: 0,
      brand: '',
      model: '',
      lens: '',
      focal_length: '',
      aperture: '',
      iso: 0,
      exposure_time: '',
      latitude: null,
      longitude: null,
      altitude: null,
      imported_at: '',
      has_description: false,
      thumbnail_url: it.cover.image_url,
      has_nef: false,
      burst_group_id: it.groupId,
      burst_cover: true,
      burst_count: it.members.length,
    }
  }
  const p = it.photo
  return {
    id: p.photo_id,
    filename: p.filename,
    file_path: '',
    timeline: '',
    tags: '',
    description: p.description,
    shot_at: null,
    width: 0,
    height: 0,
    brand: '',
    model: '',
    lens: '',
    focal_length: '',
    aperture: '',
    iso: 0,
    exposure_time: '',
    latitude: null,
    longitude: null,
    altitude: null,
    imported_at: '',
    has_description: !!p.description,
    thumbnail_url: p.image_url,
    has_nef: false,
    burst_group_id: '',
    burst_cover: false,
    burst_count: 0,
  }
}

function openGroupBrowser(index: number) {
  const it = items.value[index]
  if (it?.kind !== 'group') return
  curatingIndex.value = index
  groupModalGroupId.value = it.groupId
  groupModalCoverId.value = it.cover.photo_id
  groupModalMembers.value = it.members.map((m) => ({
    id: m.photo_id,
    thumbnail_url: m.image_url,
    filename: m.filename,
  }))
  showGroupModal.value = true
}

function handleCurate(selectedIds: string[]) {
  const idx = curatingIndex.value
  const it = items.value[idx]
  if (idx < 0 || it?.kind !== 'group') return
  const chosen = it.members.filter((m) => selectedIds.includes(m.photo_id))
  const replacements: StudioItem[] = chosen.map((m) => ({
    kind: 'photo',
    key: m.photo_id,
    photo: m,
  }))
  items.value.splice(idx, 1, ...replacements)
  showGroupModal.value = false
  curatingIndex.value = -1
}

function removeItem(index: number) {
  items.value.splice(index, 1)
}

async function openPhotoDetail(id: string) {
  detailLoading.value = true
  try {
    const resp = await photoApi.photoServiceGetPhotoDetail(id)
    selectedDetail.value = toPhotoDetail(resp)
    showDetail.value = true
  } catch (e: any) {
    message.error(e?.message || '获取照片详情失败')
  } finally {
    detailLoading.value = false
  }
}

watch(describeProcessingIds, async (next, previous) => {
  if (selectedDetail.value && previous.has(selectedDetail.value.id) && !next.has(selectedDetail.value.id)) {
    openPhotoDetail(selectedDetail.value.id)
    await new Promise((resolve) => setTimeout(resolve, 0))
    if (selectedDetail.value?.vlm_status === 'healthy') {
      await enqueueEmbedPhoto(selectedDetail.value.id)
    }
  }
})
watch(embedProcessingIds, (next, previous) => {
  if (selectedDetail.value && previous.has(selectedDetail.value.id) && !next.has(selectedDetail.value.id)) {
    openPhotoDetail(selectedDetail.value.id)
  }
})

onMounted(async () => {
  const qDraftId = route.query.draft_id as string
  const qTopicId = route.query.topic_id as string
  const qPhotoIds = route.query.photo_ids as string

  if (qDraftId) {
    await loadDraft(qDraftId)
  } else if (qTopicId) {
    await loadTopic(qTopicId)
  } else if (qPhotoIds) {
    await addItemsFromTokens(qPhotoIds.split(',').filter(Boolean))
  }
})

async function loadDraft(id: string) {
  isLoading.value = true
  try {
    const resp = await fetch(`${getApiBase()}/drafts/${id}`)
    if (!resp.ok) throw new Error('加载草稿失败')
    const data = await resp.json()
    draftId.value = data.id
    title.value = data.title || ''
    content.value = data.content || ''
    style.value = data.style || 'casual'
    source.value = data.source || 'self_select'
    if (data.photo_ids?.length) {
      await addItemsFromTokens(data.photo_ids)
    }
  } catch (e: any) {
    message.error(e.message || '加载草稿失败')
  } finally {
    isLoading.value = false
  }
}

interface TopicDetail {
  title?: string
  angle?: string
  rationale?: string
  photo_ids?: string[]
  photo_sequence?: Array<{ photo_id?: string }>
}

async function loadTopic(id: string) {
  isLoading.value = true
  try {
    const resp = await fetch(`${getAgentBase()}/suggest/history/${id}/detail`)
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || '加载选题失败')
    }
    const topic: TopicDetail = await resp.json()
    const sequencePhotoIds = (topic.photo_sequence ?? [])
      .map((item) => item.photo_id ?? '')
      .filter(Boolean)
    const photoIds = sequencePhotoIds.length > 0 ? sequencePhotoIds : (topic.photo_ids ?? [])

    const topicReason = topic.rationale ?? topic.angle ?? ''
    title.value = topic.title ?? ''
    content.value = topicReason
    draftInput.value = topicReason
    mode.value = 'draft'
    source.value = 'topic'
    await addItemsFromTokens(photoIds)
    message.success('已采纳选题，可继续编辑')
  } catch (e: any) {
    message.error(e?.message || '加载选题失败')
  } finally {
    isLoading.value = false
  }
}

// 按 token 加载条目：普通 id → 单张；g:<封面id> → 连拍组（含成员）
async function addItemsFromTokens(tokens: string[]) {
  const missing = tokens.filter((t) => t && !items.value.some((it) => it.key === t))
  if (!missing.length) return
  isPhotosLoading.value = true
  try {
    for (const token of missing) {
      if (token.startsWith('g:')) {
        const [groupId, coverId] = token.slice(2).split(':')
        if (!groupId || !coverId) continue
        const cover = await fetchPhoto(coverId)
        if (!cover) continue
        const members = await fetchGroupMembers(groupId)
        if (members.length === 0) console.warn('[PostStudio] 连拍组成员为空:', groupId)
        items.value.push({ kind: 'group', key: token, groupId, cover, members })
      } else {
        const photo = await fetchPhoto(token)
        if (photo) items.value.push({ kind: 'photo', key: token, photo })
      }
    }
  } finally {
    isPhotosLoading.value = false
  }
}

async function handleGenerate() {
  if (mode.value === 'prompt') {
    if (!hasPhotos.value) {
      message.warning('请先添加照片')
      return
    }
  } else if (!draftInput.value.trim()) {
    message.warning('请粘贴草稿内容')
    return
  }

  isGenerating.value = true
  try {
    const isPrompt = mode.value === 'prompt'
    const body = isPrompt
      ? { photo_ids: flatPhotos.value.map(p => p.photo_id), style: style.value, prompt: promptText.value }
      : { content: draftInput.value, style: style.value, photo_ids: flatPhotos.value.map(p => p.photo_id) }
    const resp = await fetch(`${getAgentBase()}/post-studio/${isPrompt ? 'generate' : 'refine'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || (isPrompt ? '生成失败' : '润色失败'))
    }
    const data = await resp.json()
    title.value = data.title || ''
    content.value = data.content || ''
    if (data.warnings?.length) {
      data.warnings.forEach((w: string) => message.warning(w))
    } else {
      message.success(isPrompt ? '文案已生成' : '文案已润色')
    }
  } catch (e: any) {
    message.error(e.message || '操作失败')
  } finally {
    isGenerating.value = false
  }
}

// 草稿 photo_ids：单张存真实 id，连拍组存 g:<组id>:<封面id> 以保留组结构
function draftPhotoIds(): string[] {
  return items.value.map((it) => (it.kind === 'photo' ? it.photo.photo_id : `g:${it.groupId}:${it.cover.photo_id}`))
}

async function saveDraft() {
  const body = {
    title: title.value,
    content: content.value,
    photo_ids: draftPhotoIds(),
    style: style.value,
    source: source.value,
  }

  try {
    let resp: Response
    if (draftId.value) {
      resp = await fetch(`${getApiBase()}/drafts/${draftId.value}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } else {
      resp = await fetch(`${getApiBase()}/drafts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    }
    if (!resp.ok) throw new Error('保存失败')
    const data = await resp.json()
    draftId.value = data.id
    message.success('草稿已保存')
  } catch (e: any) {
    message.error(e.message || '保存失败')
  }
}

function markdownText(): string {
  return `# ${title.value.trim() || '无标题'}\n\n${content.value}`
}

function plainText(): string {
  return [title.value.trim(), content.value.trim()].filter(Boolean).join('\n\n')
}

async function copyText(text: string, successMessage: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(successMessage)
  } catch {
    message.error('复制失败，请检查浏览器剪贴板权限')
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

function downloadMarkdown() {
  downloadBlob(new Blob([markdownText()], { type: 'text/markdown;charset=utf-8' }), 'post.md')
}

function downloadPhoto(photo: PhotoItem) {
  const anchor = document.createElement('a')
  anchor.href = originalImageUrl(photo.photo_id)
  anchor.download = photo.filename || 'photo'
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
}

async function downloadZip() {
  if (!draftId.value) {
    message.warning('请先保存草稿，再导出 ZIP')
    return
  }
  try {
    const resp = await fetch(`${getApiBase()}/drafts/${draftId.value}/export`)
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.error || err.message || 'ZIP 导出失败')
    }
    downloadBlob(await resp.blob(), `draft-${draftId.value}.zip`)
    message.success('ZIP 已开始下载')
  } catch (e: any) {
    message.error(e?.message || 'ZIP 导出失败')
  }
}

function openPhotoPicker() {
  showPhotoPicker.value = true
  photoPickerQuery.value = ''
  photoPickerResults.value = []
  photoPickerSelected.value = new Set()
  loadPickerPhotos()
}

async function loadPickerPhotos(keyword = '') {
  isPickerLoading.value = true
  try {
    const resp = await photoApi.photoServiceSearchPhotos(
      1, 50, undefined, undefined, keyword || undefined,
    )
    photoPickerResults.value = (resp.items ?? []).map(photoToItem)
  } catch {
    message.error('加载照片失败')
    photoPickerResults.value = []
  } finally {
    isPickerLoading.value = false
  }
}

function togglePickerPhoto(id: string) {
  const next = new Set(photoPickerSelected.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  photoPickerSelected.value = next
}

async function confirmPickerSelection() {
  await addItemsFromTokens([...photoPickerSelected.value])
  showPhotoPicker.value = false
}
</script>

<template>
  <NLayout class="studio-layout">
    <NLayoutHeader bordered>
      <div class="page-header">
        <div class="page-header-left">
          <NIcon size="20"><CreateOutline /></NIcon>
          <h3 class="page-title">图文工坊</h3>
          <NTag v-if="draftId" size="small" :bordered="false">编辑草稿</NTag>
        </div>
        <NSpace>
          <NButton size="small" type="primary" :disabled="!canSave" @click="saveDraft">
            保存草稿
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <NLayoutContent>
      <div class="page-content">
        <NSpin :show="isLoading">
          <!-- 照片区 -->
          <div class="panel photo-panel">
            <div class="panel-header">
              <span class="panel-title">照片<template v-if="items.length"> · {{ items.length }} 张</template></span>
              <NButton size="small" @click="openPhotoPicker">
                <template #icon><NIcon><AddOutline /></NIcon></template>
                添加照片
              </NButton>
            </div>

            <div v-if="!hasPhotos" class="photo-empty">
              <NEmpty description="暂无照片，点击「添加照片」开始选择" />
            </div>

            <NSpin :show="isPhotosLoading">
              <draggable
                v-if="hasPhotos"
                v-model="items"
                item-key="key"
                class="photo-grid"
                ghost-class="photo-ghost"
              >
                <template #item="{ element, index }">
                  <PhotoCard
                    :photo="toCardPhoto(element)"
                    :view-level="element.kind === 'group' ? 'fine' : 'all'"
                    :show-status="false"
                    :show-embed="false"
                    :show-delete="false"
                    :show-remove="true"
                    :show-tooltip="false"
                    @view-detail="openPhotoDetail"
                    @open-burst-group="() => openGroupBrowser(index)"
                    @remove="removeItem(index)"
                  />
                </template>
              </draggable>
            </NSpin>
          </div>

          <!-- 文案区 -->
          <div class="panel copy-panel">
            <div class="controls-row">
              <div class="field-group style-select">
                <label class="field-label">风格</label>
                <NSelect
                  v-model:value="style"
                  :options="styleOptions"
                  placeholder="选择或输入风格"
                  filterable
                  tag
                  clearable
                  size="small"
                />
              </div>

              <div class="field-group mode-select">
                <label class="field-label">模式</label>
                <NRadioGroup v-model:value="mode" size="small">
                  <NRadioButton value="prompt">提示词</NRadioButton>
                  <NRadioButton value="draft">草稿润色</NRadioButton>
                </NRadioGroup>
              </div>
            </div>

            <div class="field-group">
              <label class="field-label">{{ mode === 'prompt' ? '提示词' : '草稿内容' }}</label>
              <NInput
                v-model:value="promptOrDraft"
                type="textarea"
                :placeholder="mode === 'prompt'
                  ? '补充本次的具体要求，可留空。例如：重点写第二天爬山那段'
                  : '请输入文案'"
                :rows="3"
              />
            </div>

            <div class="generate-row">
              <NButton
                :type="mode === 'prompt' ? 'primary' : 'warning'"
                :loading="isGenerating"
                :disabled="generateDisabled"
                @click="handleGenerate"
              >
                {{ mode === 'prompt' ? '生成文案' : '润色文案' }}
              </NButton>
            </div>

            <div class="field-group">
              <label class="field-label">标题</label>
              <NInput v-model:value="title" placeholder="帖子标题（AI 会自动生成）" />
            </div>

            <div class="field-group content-editor">
              <label class="field-label">正文</label>
              <NInput
                v-model:value="content"
                type="textarea"
                placeholder="AI 生成的内容会填入这里，你也可以直接编辑"
                :rows="8"
              />
            </div>
          </div>

          <!-- 导出区 -->
          <div class="panel export-panel">
            <div class="panel-header">
              <span class="panel-title">导出</span>
              <NSpace size="small" wrap>
                <NButton size="small" @click="copyText(markdownText(), 'Markdown 已复制')">
                  复制 Markdown
                </NButton>
                <NButton size="small" @click="copyText(plainText(), '纯文本已复制')">
                  复制纯文本
                </NButton>
                <NButton size="small" @click="downloadMarkdown">
                  下载 .md
                </NButton>
                <NButton size="small" type="primary" :disabled="!draftId" @click="downloadZip">
                  下载 ZIP
                </NButton>
              </NSpace>
            </div>
            <div v-if="flatPhotos.length" class="export-photo-list">
              <div v-for="photo in flatPhotos" :key="photo.photo_id" class="export-photo-item">
                <span class="export-photo-name">{{ photo.filename }}</span>
                <NButton size="tiny" @click="downloadPhoto(photo)">下载原图</NButton>
              </div>
            </div>
            <span v-else class="export-hint">添加照片后可下载原图，保存草稿后可打包 ZIP。</span>
          </div>
        </NSpin>
      </div>
    </NLayoutContent>

    <!-- 照片选择弹窗 -->
    <NModal
      v-model:show="showPhotoPicker"
      preset="card"
      title="选择照片"
      style="width: min(90vw, 720px)"
    >
      <div class="picker-search">
        <NInput
          v-model:value="photoPickerQuery"
          placeholder="搜索照片（关键词、标签）"
          clearable
          @keyup.enter="loadPickerPhotos(photoPickerQuery)"
        />
        <NButton :loading="isPickerLoading" @click="loadPickerPhotos(photoPickerQuery)">搜索</NButton>
      </div>

      <NSpin :show="isPickerLoading">
        <div v-if="photoPickerResults.length" class="picker-grid">
          <div
            v-for="p in photoPickerResults"
            :key="p.photo_id"
            class="picker-item"
            :class="{ selected: photoPickerSelected.has(p.photo_id) }"
            @click="togglePickerPhoto(p.photo_id)"
          >
            <img :src="p.image_url" :alt="p.filename" class="picker-thumb" />
            <NCheckbox
              :checked="photoPickerSelected.has(p.photo_id)"
              class="picker-check"
              @click.stop
              @update:checked="togglePickerPhoto(p.photo_id)"
            />
          </div>
        </div>
        <NEmpty v-else-if="!isPickerLoading" description="没有找到照片" />
      </NSpin>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="showPhotoPicker = false">取消</NButton>
          <NButton type="primary" :disabled="photoPickerSelected.size === 0" @click="confirmPickerSelection">
            添加 {{ photoPickerSelected.size }} 张
          </NButton>
        </NSpace>
      </template>
    </NModal>
  </NLayout>

  <!-- 照片详情抽屉（复用图片管理，仅展示信息，不含 VLM/Embed 处理入口） -->
  <PhotoDetail
    :show="showDetail"
    :photo="selectedDetail"
    :loading="detailLoading"
    :nav-list="photoNavList"
    :describe-processing="detailDescribeProcessing"
    :validate-processing="false"
    :embed-processing="detailEmbedProcessing"
    :show-vlm-actions="false"
    @close="showDetail = false"
    @navigate="openPhotoDetail"
    @trigger-describe="handleDetailDescribe"
    @trigger-embed="handleDetailEmbed"
  />

  <!-- 连拍组浏览弹窗（复用图片管理样式，curate 模式：复选 + 连拍精选） -->
  <BurstGroupModal
    :show="showGroupModal"
    :group-id="groupModalGroupId"
    :members="groupModalMembers"
    :cover-id="groupModalCoverId"
    :loading="false"
    mode="curate"
    @close="showGroupModal = false"
    @view-detail="openPhotoDetail"
    @curate="handleCurate"
  />
</template>

<style scoped>
.studio-layout :deep(.n-layout-scroll-container) { display: flex; flex-direction: column; }
.studio-layout :deep(.n-layout-header) { flex-shrink: 0; }
.studio-layout :deep(.n-layout-content) { flex: 1; min-height: 0; }

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
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 24px 24px;
  max-width: 960px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

.panel {
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  padding: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 8px;
  flex-wrap: wrap;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
}

.photo-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
}

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 12px;
}

.photo-ghost {
  opacity: 0.4;
  outline: 2px dashed var(--n-color-primary);
}

.copy-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.export-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.export-photo-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.export-photo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.export-photo-name,
.export-hint {
  overflow: hidden;
  color: var(--n-text-color-2);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.controls-row {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 16px;
}
.style-select { flex: 0 0 200px; }
.mode-select { flex: 0 0 auto; }

.field-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--n-text-color-2);
}

.generate-row {
  display: flex;
  justify-content: flex-start;
}

.content-editor :deep(textarea) {
  min-height: 160px;
}

/* 照片选择弹窗 */
.picker-search {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.picker-search :deep(.n-input) { flex: 1; }

.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 8px;
  max-height: 400px;
  overflow-y: auto;
}

.picker-item {
  position: relative;
  aspect-ratio: 1;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  border: 2px solid transparent;
  transition: border-color 0.15s;
}
.picker-item.selected { border-color: var(--n-color-primary); }

.picker-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.picker-check {
  position: absolute;
  top: 4px;
  left: 4px;
}
</style>
