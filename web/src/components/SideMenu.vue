<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NLayoutSider, NMenu, NIcon } from 'naive-ui'
import {
  ImageOutline,
  AddOutline,
  BookmarkOutline,
} from '@vicons/ionicons5'
import type { MenuOption } from 'naive-ui'
import { h, type Component } from 'vue'
import { useChat } from '../composables/useChat'

const route = useRoute()
const router = useRouter()
const { sessions, fetchSessions, createSession } = useChat()

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

// ── 获取会话列表 ──

onMounted(() => fetchSessions())

// 路由变化时刷新会话列表
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

// ── 计算菜单选项 ──

const menuOptions = computed<MenuOption[]>(() => {
  const items: MenuOption[] = [
    // 固定功能页面
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
    // 新建对话放在固定功能最后
    {
      label: '新建对话',
      key: '/chat/new',
      icon: renderIcon(AddOutline),
    },
    { type: 'divider' as const, key: 'divider-1' },
  ]

  // 动态会话列表
  for (const s of sessions.value) {
    items.push({
      label: s.title,
      key: `/chat/${s.session_id}`,
    })
  }

  return items
})

// ── 计算当前选中的 key ──

const selectedKey = computed(() => {
  const path = route.path
  if (path.startsWith('/chat/')) {
    return path
  }
  if (path === '/photos') {
    return '/photos'
  }
  if (path === '/golden-queries') {
    return '/golden-queries'
  }
  return '/photos'
})
</script>

<template>
  <NLayoutSider
    bordered
    :width="220"
    collapse-mode="transform"
    :collapsed-width="64"
  >
    <div class="sider-header">
      <span class="sider-title">Photo Agent</span>
    </div>
    <NMenu
      :options="menuOptions"
      :value="selectedKey"
      :collapsed-width="64"
      @update:value="handleMenuClick"
    />
  </NLayoutSider>
</template>

<style scoped>
.sider-header {
  display: flex;
  align-items: center;
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
</style>
