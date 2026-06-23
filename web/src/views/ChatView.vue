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
  useMessage,
} from 'naive-ui'
import { TrashOutline, SendOutline } from '@vicons/ionicons5'
import { useChat } from '../composables/useChat'

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
    await sendMessage(text)
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
            v-for="msg in messages"
            :key="msg.id || `${msg.role}-${msg.created_at}`"
            class="message-row"
            :class="msg.role === 'user' ? 'message-row--user' : 'message-row--assistant'"
          >
            <div class="message-bubble" :class="`message-bubble--${msg.role}`">
              <div class="message-text">{{ msg.content }}</div>
              <div v-if="msg.role === 'assistant' && msg.query_type" class="message-meta">
                <NTag :bordered="false" size="tiny">
                  {{ routeLabel[msg.query_type] || msg.query_type }}
                </NTag>
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
.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.input-wrapper > :first-child {
  flex: 1;
}
</style>
