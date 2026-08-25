<script setup lang="ts">
import { ref, watch, onMounted, nextTick, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NLayout,
  NLayoutHeader,
  NLayoutContent,
  NButton,
  NIcon,
  NInput,
  NTag,
  NEmpty,
  NSpin,
  NSpace,
  NModal,
  NRadioGroup,
  NRadioButton,
  useMessage,
} from 'naive-ui'
import { TrashOutline, SendOutline, ImageOutline, DownloadOutline, BookmarkOutline } from '@vicons/ionicons5'
import { marked } from 'marked'
import { useChat } from '../composables/useChat'
import { getAgentBase, getApiBase } from '../config'
import type { PhotoRef, Granularity } from '../types/chat'
import PhotoPreviewModal from '../components/PhotoPreviewModal.vue'
import BurstGroupModal from '../components/BurstGroupModal.vue'
import { photoApi } from '../backend-sdk-client'
import type { ApiSearchPhotosResponse } from '../../backend-sdk/api'

const route = useRoute()
const router = useRouter()
const message = useMessage()

const {
  currentSession,
  messages,
  isLoading,
  fetchSessions,
  createSession,
  loadSession,
  sendMessage,
  deleteSession,
  resetChat,
} = useChat()

const inputText = ref('')
const messagesContainer = ref<HTMLElement | null>(null)
const isCreating = ref(false)

// 检索粒度：会话内保持，直到用户主动切换
const granularity = ref<Granularity>('photo')
const granularityOptions: { label: string; value: Granularity }[] = [
  { label: '精确检索', value: 'photo' },
  { label: '精细连拍组', value: 'fine' },
  { label: '模糊连拍组', value: 'coarse' },
]

// 路由类型中文映射
const routeLabel: Record<string, string> = {
  sql: 'SQL 统计',
  rag: 'RAG 检索',
  tool: 'API 调用',
  error: '错误',
}

// ── 路由监听 ──

watch(
  () => route.params.sessionId,
  async (newId) => {
    if (newId && typeof newId === 'string') {
      await loadSession(newId)
    } else {
      resetChat()
    }
  },
  { immediate: true }
)

onMounted(() => {
  fetchSessions()
})

// ── 新建对话 ──

async function handleNewChat() {
  if (isCreating.value) return
  isCreating.value = true
  try {
    const id = await createSession()
    router.push(`/chat/${id}`)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '创建会话失败')
  } finally {
    isCreating.value = false
  }
}

// ── 发送消息 ──

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || isLoading.value) return
  inputText.value = ''

  // 如果还没有会话，先创建
  if (!currentSession.value) {
    try {
      isCreating.value = true
      const id = await createSession()
      router.push(`/chat/${id}`)
      // 等待路由更新后再发送
      await nextTick()
      // router change triggers watcher → loadSession → currentSession set
      // but it's async, so we wait a tick
      await nextTick()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '创建会话失败')
      isCreating.value = false
      return
    } finally {
      isCreating.value = false
    }
  }

  try {
    await sendMessage(text, granularity.value)
    scrollToBottom()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '发送失败')
  }
}

// ── 删除会话 ──

async function handleDelete() {
  if (!currentSession.value) return
  try {
    await deleteSession(currentSession.value.session_id)
    message.success('会话已删除')
    router.push('/photos')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '删除失败')
  }
}

// ── 键盘处理 ──

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

// ── 滚动 ──

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// 消息变化时自动滚动
watch(
  () => messages.value.length,
  () => scrollToBottom()
)

// ── Markdown 渲染 ──

marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text: string): string {
  const result = marked.parse(text)
  return typeof result === 'string' ? result : ''
}

// ── 图片预览与下载 ──

const previewVisible = ref(false)
const previewUrl = ref('')

// ── 保存为黄金用例 ──

const goldenModalVisible = ref(false)
const goldenQueryText = ref('')
const goldenPhotoIds = ref<{photo_id: string; filename: string}[]>([])
const goldenCategory = ref('')
const goldenNotes = ref('')
const goldenSaving = ref(false)

function openGoldenSave(aiMsgIndex: number) {
  // 找到该 AI 消息前最近的一条 user 消息作为查询文本
  let queryText = ''
  for (let i = aiMsgIndex - 1; i >= 0; i--) {
    if (messages.value[i]?.role === 'user') {
      queryText = messages.value[i].content
      break
    }
  }
  const aiMsg = messages.value[aiMsgIndex]
  const photoRefs = (aiMsg?.photos || []).map((p: PhotoRef) => {
    const stripExt = (s: string) => s.replace(/\.[^.]+$/, '')
    return {
      photo_id: stripExt(p.photo_id),
      filename: stripExt(p.filename || p.photo_id),
    }
  })

  goldenQueryText.value = queryText
  goldenPhotoIds.value = photoRefs
  goldenCategory.value = ''
  goldenNotes.value = ''
  goldenModalVisible.value = true
}

async function handleGoldenSave() {
  if (!goldenQueryText.value.trim() || goldenPhotoIds.value.length === 0) return
  goldenSaving.value = true
  try {
    const resp = await fetch(`${getAgentBase()}/golden-queries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query_text: goldenQueryText.value.trim(),
        relevant_photos: goldenPhotoIds.value.map(p => ({ photo_id: p.photo_id, filename: p.filename })),
        category: goldenCategory.value.trim(),
        notes: goldenNotes.value.trim(),
      }),
    })
    if (resp.ok) {
      message.success('已保存为黄金用例')
      goldenModalVisible.value = false
    } else {
      const err = await resp.json()
      message.error(err.detail || '保存失败')
    }
  } catch (e) {
    console.warn('保存黄金用例失败', e)
    message.error('保存失败')
  } finally {
    goldenSaving.value = false
  }
}

function previewPhoto(photo: PhotoRef) {
  previewUrl.value = photo.image_url
  previewVisible.value = true
}

function downloadPhoto(photo: PhotoRef) {
  downloadImageUrl(photo.image_url, photo.filename || photo.photo_id)
}

function downloadImageUrl(url: string, filename: string) {
  // 通过 fetch 下载为 blob，确保跨场景可靠触发下载
  fetch(url)
    .then(res => res.blob())
    .then(blob => {
      const objUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objUrl)
    })
    .catch(() => {
      // fallback: 直接打开图片
      window.open(url, '_blank')
    })
}

// ── 连拍组结果浏览 ──

const groupModalVisible = ref(false)
const groupModalId = ref('')
const groupModalCoverId = ref('')
const groupModalLoading = ref(false)
const groupModalMembers = ref<{ id: string; thumbnail_url: string; filename: string }[]>([])

// 组粒度检索的结果带 burst_group_id，用它区分组卡片与单张照片列表
function isGroupRef(photo: PhotoRef): boolean {
  return !!photo.burst_group_id
}

async function openGroupModal(photo: PhotoRef) {
  const groupId = photo.burst_group_id
  if (!groupId) return
  groupModalId.value = groupId
  groupModalCoverId.value = photo.photo_id
  groupModalMembers.value = []
  groupModalLoading.value = true
  groupModalVisible.value = true
  try {
    groupModalMembers.value = await fetchGroupMembers(groupId)
  } finally {
    groupModalLoading.value = false
  }
}

// 组 id 形如 burst_fine_xxx / burst_coarse_xxx，据此决定过滤哪一档分组列
async function fetchGroupMembers(groupId: string) {
  const profile = groupId.startsWith('burst_coarse_') ? 'coarse' : 'fine'
  try {
    const resp: ApiSearchPhotosResponse = await photoApi.photoServiceSearchPhotos(
      1, 100,
      undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined,
      'shot_at', 'asc',
      groupId, profile,
    )
    return (resp.items ?? []).map((it) => ({
      id: it.id ?? '',
      filename: it.filename ?? '',
      thumbnail_url: it.id ? `${getApiBase()}/photos/${it.id}/image` : '',
    }))
  } catch (e) {
    console.warn('获取连拍组成员失败', e)
    return []
  }
}

function closeGroupModal() {
  groupModalVisible.value = false
  groupModalId.value = ''
}

// 组内点击主图：聊天场景没有详情抽屉，直接用现有大图预览
function viewGroupPhotoDetail(photoId: string) {
  previewUrl.value = `${getApiBase()}/photos/${photoId}/image`
  previewVisible.value = true
}

// ── 计算属性 ──

const hasSession = computed(() => currentSession.value !== null)
const hasMessages = computed(() => messages.value.length > 0)
</script>

<template>
  <NLayout>
    <!-- 顶部栏 -->
    <NLayoutHeader bordered>
      <div class="chat-header">
        <div class="chat-header-left">
          <h3 class="chat-title">
            {{ currentSession?.title || '新建对话' }}
          </h3>
          <NTag v-if="isLoading" type="info" size="small" :bordered="false">
            思考中...
          </NTag>
        </div>
        <NSpace>
          <NButton
            v-if="hasSession"
            size="small"
            @click="handleDelete"
          >
            <template #icon>
              <NIcon><TrashOutline /></NIcon>
            </template>
            删除
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <!-- 消息列表 -->
    <NLayoutContent>
      <div class="chat-content">
        <!-- 空状态 -->
        <div v-if="!hasMessages && !isLoading" class="empty-state">
          <NEmpty description="开始一段新对话">
            <template #extra>
              <NButton
                v-if="!hasSession"
                type="primary"
                :loading="isCreating"
                @click="handleNewChat"
              >
                新建对话
              </NButton>
            </template>
          </NEmpty>
        </div>

        <!-- 消息列表 -->
        <div
          v-else
          ref="messagesContainer"
          class="messages-container"
        >
          <div
            v-for="(msg, i) in messages"
            :key="msg.id || `${msg.role}-${msg.created_at}`"
            class="message-row"
            :class="msg.role === 'user' ? 'message-row--user' : 'message-row--assistant'"
          >
            <div class="message-bubble" :class="`message-bubble--${msg.role}`">
              <!-- 用户消息：转义文本；AI 消息：渲染 Markdown -->
              <div
                v-if="msg.role === 'user'"
                class="message-text"
              >{{ msg.content }}</div>
              <div
                v-else
                class="message-text markdown-body"
                v-html="renderMarkdown(msg.content)"
              ></div>
              <div v-if="msg.role === 'assistant' && msg.query_type" class="message-meta">
                <NTag :bordered="false" size="tiny">
                  {{ routeLabel[msg.query_type] || msg.query_type }}
                </NTag>
                <NButton
                  v-if="msg.photos && msg.photos.length"
                  size="tiny"
                  text
                  @click="openGoldenSave(i)"
                  title="保存为黄金用例"
                >
                  <template #icon>
                    <NIcon size="14"><BookmarkOutline /></NIcon>
                  </template>
                  保存为黄金用例
                </NButton>
              </div>

              <!-- 附件列表（仅 AI 消息且有照片引用时显示） -->
              <div
                v-if="msg.role === 'assistant' && msg.photos && msg.photos.length"
                class="photo-attachments"
              >
                <div class="attachments-header">📎 相关照片 ({{ msg.photos.length }})</div>

                <!-- 连拍组结果：封面缩略图 + 共 N 张，点击展开组内浏览 -->
                <div
                  v-if="msg.photos.some(isGroupRef)"
                  class="group-cards"
                >
                  <div
                    v-for="photo in msg.photos"
                    :key="photo.photo_id"
                    class="group-card"
                    :title="photo.filename"
                    @click="isGroupRef(photo) ? openGroupModal(photo) : previewPhoto(photo)"
                  >
                    <img :src="photo.image_url" :alt="photo.filename" class="group-card-img" />
                    <div class="group-card-caption">
                      共 {{ photo.burst_count || 1 }} 张
                    </div>
                  </div>
                </div>

                <div v-else class="attachments-list">
                  <div
                    v-for="photo in msg.photos"
                    :key="photo.photo_id"
                    class="attachment-item"
                  >
                    <span class="attachment-icon">
                      <NIcon size="16"><ImageOutline /></NIcon>
                    </span>
                    <span class="attachment-name" @click="previewPhoto(photo)">
                      {{ photo.filename }}
                    </span>
                    <NButton
                      size="tiny"
                      text
                      @click="downloadPhoto(photo)"
                      title="下载原图"
                    >
                      <template #icon>
                        <NIcon size="14"><DownloadOutline /></NIcon>
                      </template>
                    </NButton>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 加载指示器 -->
          <div v-if="isLoading" class="message-row message-row--assistant">
            <div class="message-bubble message-bubble--assistant">
              <NSpin size="small" />
            </div>
          </div>
        </div>
      </div>
    </NLayoutContent>

    <!-- 底部输入区 -->
    <div class="chat-footer">
      <!-- 检索粒度：会话内保持，切换后对后续提问生效 -->
      <div class="granularity-bar">
        <NRadioGroup v-model:value="granularity" size="small">
          <NRadioButton
            v-for="opt in granularityOptions"
            :key="opt.value"
            :value="opt.value"
          >
            {{ opt.label }}
          </NRadioButton>
        </NRadioGroup>
      </div>
      <div class="input-wrapper">
        <NInput
          v-model:value="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          :disabled="isLoading"
          @keydown="handleKeydown"
        />
        <NButton
          type="primary"
          :disabled="!inputText.trim() || isLoading"
          @click="handleSend"
        >
          <template #icon>
            <NIcon><SendOutline /></NIcon>
          </template>
        </NButton>
      </div>
    </div>

    <!-- 保存为黄金用例弹窗 -->
    <NModal
      v-model:show="goldenModalVisible"
      preset="card"
      title="保存为黄金用例"
      style="width: 520px; max-width: 90vw;"
    >
      <div class="golden-form">
        <div class="golden-field">
          <label class="golden-label">查询文本</label>
          <NInput
            v-model:value="goldenQueryText"
            type="text"
            placeholder="输入查询文本"
          />
        </div>
        <div class="golden-field">
          <label class="golden-label">关联照片（{{ goldenPhotoIds.length }} 张）</label>
          <div class="photo-id-tags">
            <NTag
              v-for="(p, idx) in goldenPhotoIds"
              :key="p.photo_id"
              :bordered="false"
              size="small"
              closable
              @close="goldenPhotoIds.splice(idx, 1)"
            >
              <span class="photo-tag-name">{{ p.filename }}</span>
            </NTag>
          </div>
        </div>
        <div class="golden-field">
          <label class="golden-label">分类（可选）</label>
          <NInput
            v-model:value="goldenCategory"
            type="text"
            placeholder="物体 / 场景 / 光线 / 情绪 / 组合查询"
          />
        </div>
        <div class="golden-field">
          <label class="golden-label">备注（可选）</label>
          <NInput
            v-model:value="goldenNotes"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            placeholder="可填写备注信息"
          />
        </div>
        <div class="golden-actions">
          <NButton @click="goldenModalVisible = false">取消</NButton>
          <NButton
            type="primary"
            :loading="goldenSaving"
            :disabled="!goldenQueryText.trim() || goldenPhotoIds.length === 0"
            @click="handleGoldenSave"
          >
            保存
          </NButton>
        </div>
      </div>
    </NModal>

    <!-- 图片预览弹窗 -->
    <PhotoPreviewModal
      v-model:show="previewVisible"
      :image-url="previewUrl"
      :show-download="true"
      :download-filename="'photo'"
    />

    <!-- 连拍组展开弹窗（只浏览，不带封面/精选操作） -->
    <BurstGroupModal
      :show="groupModalVisible"
      :group-id="groupModalId"
      :members="groupModalMembers"
      :cover-id="groupModalCoverId"
      :loading="groupModalLoading"
      mode="browse"
      @close="closeGroupModal"
      @view-detail="viewGroupPhotoDetail"
    />
  </NLayout>
</template>

<style scoped>
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.chat-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.chat-title {
  margin: 0;
  font-size: 16px;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-content {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 74px); /* header 56px + footer 74px */
}
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}
.message-row {
  display: flex;
  margin-bottom: 16px;
}
.message-row--user {
  justify-content: flex-end;
}
.message-row--assistant {
  justify-content: flex-start;
}
.message-bubble {
  max-width: 75%;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.message-bubble--user {
  background: var(--n-color-primary, #2080f0);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.message-bubble--assistant {
  background: var(--n-color-embedded);
  border-bottom-left-radius: 4px;
}
.message-text {
  font-size: 14px;
}
.message-meta {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.chat-footer {
  padding: 12px 24px;
  border-top: 1px solid var(--n-border-color);
  background: var(--n-color-body);
}
.granularity-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}
.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.input-wrapper > :first-child {
  flex: 1;
}

/* ── Markdown 渲染样式 ── */
.markdown-body :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
  margin: 8px 0;
}
.markdown-body :deep(p) {
  margin: 4px 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 4px 0;
  padding-left: 20px;
}

/* ── 附件列表样式 ── */
.photo-attachments {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--n-border-color);
}
.attachments-header {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-bottom: 6px;
}
.attachments-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
/* 连拍组结果卡片：封面缩略图 + 组内张数 */
.group-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.group-card {
  width: 96px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--n-color-embedded);
  cursor: pointer;
  transition: transform 0.2s;
}
.group-card:hover {
  transform: translateY(-2px);
}
.group-card-img {
  display: block;
  width: 96px;
  height: 96px;
  object-fit: cover;
}
.group-card-caption {
  padding: 3px 6px;
  font-size: 12px;
  text-align: center;
  color: var(--n-text-color-3);
}
.attachment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
}
.attachment-item:hover {
  background: var(--n-color-hover);
}
.attachment-name {
  flex: 1;
  font-size: 13px;
  color: var(--n-color-target);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attachment-name:hover {
  text-decoration: underline;
}
.attachment-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  color: var(--n-text-color-3);
}

/* ── 黄金用例保存表单 ── */
.golden-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.golden-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.golden-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--n-text-color-2);
}
.photo-id-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 28px;
  padding: 4px 0;
}
.photo-tag-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}
.golden-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
</style>
