<script setup lang="ts">
import { NLayoutSider, NMenu, NIcon } from 'naive-ui'
import { ImageOutline } from '@vicons/ionicons5'
import type { MenuOption } from 'naive-ui'
import { h, type Component } from 'vue'

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions: MenuOption[] = [
  {
    label: '图片管理',
    key: 'photos',
    icon: renderIcon(ImageOutline),
  },
]
</script>

<template>
  <NLayoutSider
    bordered
    :width="200"
    collapse-mode="transform"
    :collapsed-width="64"
  >
    <div class="sider-header">
      <span class="sider-title">Photo Agent</span>
    </div>
    <NMenu
      :options="menuOptions"
      :default-value="'photos'"
      :collapsed-width="64"
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
