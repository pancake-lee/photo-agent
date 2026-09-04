<script setup lang="ts">
import { ref, watch, onMounted, nextTick, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NLayout,
  NLayoutHeader,
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
import { TrashOutline, SendOutline, BookmarkOutline, DownloadOutline } from '@vicons/ionicons5'
import { marked } from 'marked'
import { useChat } from '../composables/useChat'
import { getAgentBase, getApiBase } from '../config'
import type { PhotoRef, Granularity } from '../types/chat'
import PhotoPreviewModal from '../components/PhotoPreviewModal.vue'
import BurstGroupModal from '../components/BurstGroupModal.vue'
import PhotoThumbList from '../components/PhotoThumbList.vue'
import RuntimeProcessPanel from '../components/RuntimeProcessPanel.vue'
import { photoApi } from '../backend-sdk-client'
import type { ApiSearchPhotosResponse } from '../../backend-sdk/api'
import { canSaveAsGoldenQuery } from '../utils/goldenQuery'
import { downloadPhotos } from '../utils/downloadPhotos'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const downloadLoading = ref(false)

async function downloadChatPhotos(photos: PhotoRef[]) {
  const ids = photos.map((photo) => photo.photo_id).filter(Boolean)
  downloadLoading.value = true
  try {
    await downloadPhotos(ids)
    message.success(`已开始下载 ${ids.length} 张照片的 ZIP`)
  } catch (e) {
    message.error(e instanceof Error ? e.message : '照片打包下载失败')
  } finally {
    downloadLoading.value = false
  }
}

const {
  currentSession,
  messages,
  isLoading,
  activeRuntimeMsg,
  fetchSessions,
  createSession,
  loadSession,
  sendMessage,
  updateLastGranularity,
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
  combined: '组合查询',
  runtime: 'Runtime 多步',
  error: '错误',
}

const granularityLabel: Record<Granularity, string> = {
  photo: '精确检索',
  fine: '精细连拍组',
  coarse: '模糊连拍组',
}

// ── 路由监听 ──

watch(
  () => route.params.sessionId,
  async (newId) => {
    if (newId && typeof newId === 'string') {
      await loadSession(newId)
      granularity.value = currentSession.value?.last_granularity || 'photo'
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

function handleGranularityChange(value: Granularity) {
  granularity.value = value
  updateLastGranularity(value).catch((e) => {
    message.warning(e instanceof Error ? e.message : '保存检索粒度失败')
  })
}

function openTrace(traceId: string) {
  window.open(`${getAgentBase()}/api/chat/traces/${encodeURIComponent(traceId)}`, '_blank', 'noopener')
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
  // Agent 服务运行在服务端，返回的 127.0.0.1 图片地址对远程浏览器不可达。
  // 统一替换为当前运行环境的图片地址，兼容已持久化的历史消息。
  const normalizedText = text.replace(
    /https?:\/\/[^)\s]+\/api\/v1\/photos\/([^/?\s)]+)\/image(?:\?[^)\s]*)?/g,
    (_match, photoId: string) => `${getApiBase()}/photos/${photoId}/image`,
  )
  const result = marked.parse(normalizedText)
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

function previewPhotoById(photoId: string) {
  previewUrl.value = `${getApiBase()}/photos/${photoId}/image`
  previewVisible.value = true
}

// ── 连拍组结果浏览 ──

const groupModalVisible = ref(false)
const groupModalId = ref('')
const groupModalCoverId = ref('')
const groupModalLoading = ref(false)
const groupModalMembers = ref<{ id: string; thumbnail_url: string; filename: string }[]>([])

async function openGroupModal(photo: { photo_id: string; burst_group_id?: string }) {
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
  <NLayout class="chat-layout" :content-style="{ display: 'flex', flexDirection: 'column', height: '100%' }">
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
    <div class="chat-body">
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
              <!-- Runtime 消息：执行过程在前，回复与照片在后，与流式展示顺序一致 -->
              <RuntimeProcessPanel
                v-if="msg.role === 'assistant' && msg.query_type === 'runtime' && (msg.runtime_steps?.length || activeRuntimeMsg === msg)"
                :steps="msg.runtime_steps || []"
                :active="activeRuntimeMsg === msg"
              />
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
                <NTag :bordered="false" size="tiny" type="info">
                  {{ msg.granularity ? granularityLabel[msg.granularity] : '粒度未记录' }}
                </NTag>
                <NTag v-if="msg.trace_id" :bordered="false" size="tiny" type="default">
                  轨迹 {{ msg.trace_id }}
                </NTag>
                <NButton
                  v-if="msg.trace_id"
                  size="tiny"
                  text
                  title="查看完整诊断记录"
                  @click="openTrace(msg.trace_id)"
                >查看诊断</NButton>
                <NButton
                  v-if="canSaveAsGoldenQuery(msg)"
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
                <div class="attachments-header">📎 相关照片 ({{ msg.photos.length }}) <NButton size="tiny" :loading="downloadLoading" @click="downloadChatPhotos(msg.photos)"><template #icon><NIcon><DownloadOutline /></NIcon></template>下载 ZIP</NButton></div>

                <PhotoThumbList
                  :photos="msg.photos"
                  :max-preview="0"
                  @preview="previewPhotoById"
                  @open-group="openGroupModal"
                />
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
    </div>

    <!-- 底部输入区 -->
    <div class="chat-footer">
      <!-- 检索粒度：会话内保持，切换后对后续提问生效 -->
      <div class="granularity-bar">
        <NRadioGroup v-model:value="granularity" size="small" @update:value="handleGranularityChange">
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
.chat-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.chat-layout :deep(.n-layout-scroll-container) {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.chat-layout :deep(.n-layout-header) {
  flex: 0 0 auto;
}
.chat-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.chat-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
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
  flex: 0 0 auto;
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
  display: block;
  width: auto;
  max-width: min(100%, 200px);
  max-height: 280px;
  object-fit: contain;
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
