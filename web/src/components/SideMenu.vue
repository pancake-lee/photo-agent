<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayoutSider, NMenu, NIcon, NCheckbox, NModal, NButton, NSpace, useMessage } from 'naive-ui'
import {
  ImageOutline,
  AddOutline,
  BookmarkOutline,
  GitNetworkOutline,
  BulbOutline,
  SettingsOutline,
  ChatbubblesOutline,
  CloudUploadOutline,
  CalendarOutline,
} from '@vicons/ionicons5'
import type { MenuOption } from 'naive-ui'
import { h, type Component } from 'vue'
import { useChat } from '../composables/useChat'
import { isWails } from '../utils/env'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { sessions, fetchSessions, createSession, deleteSessions } = useChat()

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

// ── 获取会话列表 ──

onMounted(() => fetchSessions())

watch(
  () => route.fullPath,
  () => fetchSessions()
)

// ── 菜单点击 ──

async function handleMenuClick(key: string) {
  if (key === '/chat/new') {
    try {
      const id = await createSession()
      router.push(`/chat/${id}`)
    } catch {
      // 静默失败
    }
    return
  }
  router.push(key)
}

// ── 顶部固定菜单选项 ──

const topMenuOptions = computed<MenuOption[]>(() => {
  const options: MenuOption[] = [
    {
      label: '图片管理',
      key: '/photos',
      icon: renderIcon(ImageOutline),
    },
    {
      label: '时间线',
      key: '/timelines',
      icon: renderIcon(CalendarOutline),
    },
    {
      label: '黄金用例',
      key: '/golden-queries',
      icon: renderIcon(BookmarkOutline),
    },
    {
      label: '组图发现',
      key: '/cluster',
      icon: renderIcon(GitNetworkOutline),
    },
    {
      label: '主题发现',
      key: '/suggest',
      icon: renderIcon(BulbOutline),
    },
  ]

  // 导入工作流仅在 Wails 桌面环境可用（依赖客户端本地文件操作）
  if (isWails()) {
    options.push({
      label: '导入',
      key: '/import',
      icon: renderIcon(CloudUploadOutline),
    })
  }

  options.push({
    label: '新建对话',
    key: '/chat/new',
    icon: renderIcon(AddOutline),
  })
  return options
})

// ── 当前选中 key ──

const selectedKey = computed(() => {
  const path = route.path
  if (path.startsWith('/chat/')) return path
  if (path === '/photos') return '/photos'
  if (path === '/timelines') return '/timelines'
  if (path === '/golden-queries') return '/golden-queries'
  if (path === '/cluster') return '/cluster'
  if (path === '/suggest') return '/suggest'
  if (path === '/import') return '/import'
  if (path === '/settings') return '/settings'
  return '/photos'
})

// ── 聊天项点击 ──

function goChat(sessionId: string) {
  router.push(`/chat/${sessionId}`)
}

// ── 多选模式：批量删除会话 ──

const multiSelectMode = ref(false)
const selectedIds = ref(new Set<string>())
const showDeleteConfirm = ref(false)
const isDeleting = ref(false)

const selectedCount = computed(() => selectedIds.value.size)

function toggleMultiSelectMode() {
  multiSelectMode.value = !multiSelectMode.value
  selectedIds.value = new Set()
}

function exitMultiSelectMode() {
  multiSelectMode.value = false
  selectedIds.value = new Set()
}

function toggleSelected(sessionId: string) {
  const next = new Set(selectedIds.value)
  if (next.has(sessionId)) {
    next.delete(sessionId)
  } else {
    next.add(sessionId)
  }
  selectedIds.value = next
}

async function confirmDelete() {
  const ids = [...selectedIds.value]
  isDeleting.value = true
  try {
    const { ok, fail } = await deleteSessions(ids)
    if (fail > 0) {
      message.error(`删除完成：成功 ${ok} 个，失败 ${fail} 个`)
    } else {
      message.success(`已删除 ${ok} 个对话`)
    }
    // 当前打开的会话被删时重定向到图片管理页
    if (ids.includes(route.params.sessionId as string)) {
      router.push('/photos')
    }
    showDeleteConfirm.value = false
    exitMultiSelectMode()
    fetchSessions()
  } finally {
    isDeleting.value = false
  }
}

// Esc 退出多选模式
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && multiSelectMode.value) {
    exitMultiSelectMode()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
</script>

<template>
  <NLayoutSider
    bordered
    :width="220"
    collapse-mode="transform"
    :collapsed-width="64"
  >
    <div class="sider-content">
      <!-- ═══ 顶部：Logo + 固定功能菜单 ═══ -->
      <div class="sider-header">
        <span class="sider-title">Photo Agent</span>
      </div>

      <div class="top-menu">
        <NMenu
          :options="topMenuOptions"
          :value="selectedKey"
          @update:value="handleMenuClick"
        />
      </div>

      <div class="menu-divider" />

      <!-- ═══ 中部：聊天会话列表（可滚动） ═══ -->
      <div class="chat-area" :class="{ 'multi-select-mode': multiSelectMode }">
        <div class="chat-area-header">
          <NIcon size="14"><ChatbubblesOutline /></NIcon>
          <span class="chat-area-title" @click="multiSelectMode && exitMultiSelectMode()">
            对话
          </span>
          <button
            class="multi-select-btn"
            :class="{ danger: multiSelectMode }"
            :disabled="multiSelectMode && selectedCount === 0"
            @click="multiSelectMode ? (showDeleteConfirm = true) : toggleMultiSelectMode()"
          >
            {{ multiSelectMode ? `删除${selectedCount > 0 ? `(${selectedCount})` : ''}` : '多选' }}
          </button>
        </div>

        <div class="chat-list">
          <div
            v-for="s in sessions"
            :key="s.session_id"
            class="chat-item"
            :class="{
              active: selectedKey === `/chat/${s.session_id}`,
              checked: multiSelectMode && selectedIds.has(s.session_id),
            }"
            @click="multiSelectMode ? toggleSelected(s.session_id) : goChat(s.session_id)"
          >
            <NCheckbox
              v-if="multiSelectMode"
              :checked="selectedIds.has(s.session_id)"
              class="chat-item-checkbox"
              @click.stop
              @update:checked="toggleSelected(s.session_id)"
            />
            <span class="chat-item-text">{{ s.title }}</span>
          </div>

          <div v-if="sessions.length === 0" class="chat-empty">
            暂无对话
          </div>
        </div>
      </div>

      <!-- ═══ 批量删除确认弹窗 ═══ -->
      <NModal
        v-model:show="showDeleteConfirm"
        preset="card"
        title="删除确认"
        style="width: min(90vw, 400px)"
      >
        <div class="delete-confirm-body">
          确定删除 {{ selectedCount }} 个对话？删除后不可恢复。
        </div>
        <template #footer>
          <NSpace justify="end">
            <NButton :disabled="isDeleting" @click="showDeleteConfirm = false">取消</NButton>
            <NButton type="error" :loading="isDeleting" @click="confirmDelete">删除</NButton>
          </NSpace>
        </template>
      </NModal>

      <!-- ═══ 底部：设置（固定） ═══ -->
      <div class="bottom-section">
        <div class="menu-divider" />
        <div
          class="bottom-item"
          :class="{ active: selectedKey === '/settings' }"
          @click="router.push('/settings')"
        >
          <NIcon size="18"><SettingsOutline /></NIcon>
          <span class="bottom-item-text">设置</span>
        </div>
      </div>
    </div>
  </NLayoutSider>
</template>

<style scoped>
/* ── 整体布局 ── */

.sider-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto; /* 窗口极小时整体滚动 */
}

/* ── 头部 ── */

.sider-header {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  padding: 16px 20px;
  font-size: 18px;
  font-weight: 600;
  color: var(--n-text-color);
  border-bottom: 1px solid var(--n-border-color);
}

.sider-title {
  white-space: nowrap;
  overflow: hidden;
}

/* ── 顶部菜单 ── */

.top-menu {
  flex-shrink: 0;
}

/* ── 分割线 ── */

.menu-divider {
  height: 1px;
  margin: 4px 12px;
  background: var(--n-border-color);
  flex-shrink: 0;
}

/* ── 中部：聊天区域 ── */

.chat-area {
  flex: 1 1 0;
  min-height: 192px; /* 5 项 × 38px + header */
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-area-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  flex-shrink: 0;
}

/* 多选模式下"对话"标题可点击退出 */
.chat-area-title {
  cursor: inherit;
}

.multi-select-mode .chat-area-title {
  cursor: pointer;
}

/* ── 多选/删除按钮（对话标题右侧靠右） ── */

.multi-select-btn {
  margin-left: auto;
  padding: 2px 8px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--n-text-color-3);
  font-size: 11px;
  font-weight: 600;
  font-family: inherit;
  letter-spacing: 0.05em;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.multi-select-btn:hover {
  color: var(--n-text-color);
  background: rgba(255, 255, 255, 0.08);
}

/* 删除态：红色语义色（危险操作） */
.multi-select-btn.danger {
  color: #e5484d;
}

.multi-select-btn.danger:hover {
  color: #ff6369;
  background: rgba(229, 72, 77, 0.12);
}

.multi-select-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.multi-select-btn:disabled:hover {
  color: #e5484d;
  background: transparent;
}

.chat-list {
  flex: 1 1 0;
  overflow-y: auto;
  padding: 2px 8px;
}

/* ── 聊天项 ── */

.chat-item {
  display: flex;
  align-items: center;
  height: 36px;
  padding: 0 12px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--n-text-color-2);
  font-size: 13px;
  transition: background 0.15s, color 0.15s;
}

.chat-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.chat-item.active {
  color: var(--n-text-color);
  background: rgba(99, 132, 255, 0.15);
}

.chat-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 多选模式下选中项高亮（与路由 active 同样式） */
.chat-item.checked {
  color: var(--n-text-color);
  background: rgba(99, 132, 255, 0.15);
}

.chat-item-checkbox {
  flex-shrink: 0;
  margin-right: 8px;
}

.delete-confirm-body {
  font-size: 14px;
  line-height: 1.6;
  color: var(--n-text-color-2);
}

.chat-empty {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--n-text-color-3);
}

/* ── 底部设置 ── */

.bottom-section {
  flex-shrink: 0;
}

.bottom-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 38px;
  margin: 2px 8px 8px;
  padding: 0 12px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--n-text-color-2);
  font-size: 14px;
  transition: background 0.15s, color 0.15s;
}

.bottom-item:hover {
  background: rgba(255, 255, 255, 0.06);
}

.bottom-item.active {
  color: var(--n-text-color);
  background: rgba(99, 132, 255, 0.15);
}

.bottom-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 滚动条（暗色主题） ── */

.sider-content::-webkit-scrollbar,
.chat-list::-webkit-scrollbar {
  width: 4px;
}

.sider-content::-webkit-scrollbar-track,
.chat-list::-webkit-scrollbar-track {
  background: transparent;
}

.sider-content::-webkit-scrollbar-thumb,
.chat-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 2px;
}

.sider-content::-webkit-scrollbar-thumb:hover,
.chat-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.24);
}

/* Firefox */
.sider-content,
.chat-list {
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.12) transparent;
}
</style>
