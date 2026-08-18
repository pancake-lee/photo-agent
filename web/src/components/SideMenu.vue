<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayoutSider, NMenu, NIcon } from 'naive-ui'
import {
  ImageOutline,
  AddOutline,
  BookmarkOutline,
  GitNetworkOutline,
  BulbOutline,
  SettingsOutline,
  ChatbubblesOutline,
  CloudUploadOutline,
} from '@vicons/ionicons5'
import type { MenuOption } from 'naive-ui'
import { h, type Component } from 'vue'
import { useChat } from '../composables/useChat'
import { isWails } from '../utils/env'

const route = useRoute()
const router = useRouter()
const { sessions, fetchSessions, createSession } = useChat()

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
      <div class="chat-area">
        <div class="chat-area-header">
          <NIcon size="14"><ChatbubblesOutline /></NIcon>
          <span>对话</span>
        </div>

        <div class="chat-list">
          <div
            v-for="s in sessions"
            :key="s.session_id"
            class="chat-item"
            :class="{ active: selectedKey === `/chat/${s.session_id}` }"
            @click="goChat(s.session_id)"
          >
            <span class="chat-item-text">{{ s.title }}</span>
          </div>

          <div v-if="sessions.length === 0" class="chat-empty">
            暂无对话
          </div>
        </div>
      </div>

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
