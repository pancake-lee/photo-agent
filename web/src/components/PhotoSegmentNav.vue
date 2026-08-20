<script setup lang="ts">
/**
 * PhotoSegmentNav — 照片列表右侧分段导航。
 *
 * 按当前分段方式列出跳转目标（月份或活动），滚动时高亮跟随当前段落，
 * 点击跳转：目标段落已加载时锚点滚动，未加载时由父级以筛选重置式重新拉取。
 */
import { NButton } from 'naive-ui'
import { ArrowUpOutline } from '@vicons/ionicons5'

export interface NavItem {
  /** 导航键：月份 YYYY-MM 或活动名（空串 = 未分类） */
  key: string
  label: string
  /** 该段落是否已在当前已加载照片流中（决定点击行为） */
  loaded: boolean
}

const props = defineProps<{
  items: NavItem[]
  activeKey: string
}>()

const emit = defineEmits<{
  jump: [key: string, loaded: boolean]
  backToLatest: []
}>()
</script>

<template>
  <div class="segment-nav">
    <div class="segment-nav-title">导航</div>
    <div class="segment-nav-list">
      <div
        v-for="item in items"
        :key="item.key"
        class="segment-nav-item"
        :class="{
          active: item.key === activeKey,
          unloaded: !item.loaded,
        }"
        @click="emit('jump', item.key, item.loaded)"
      >
        <span class="segment-nav-label">{{ item.label }}</span>
      </div>
      <div v-if="items.length === 0" class="segment-nav-empty">暂无导航项</div>
    </div>
    <div class="segment-nav-footer">
      <NButton size="tiny" quaternary @click="emit('backToLatest')">
        <template #icon>
          <ArrowUpOutline />
        </template>
        回到最新
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.segment-nav {
  position: sticky;
  top: 16px;
  display: flex;
  flex-direction: column;
  width: 160px;
  max-height: calc(100vh - 96px);
  flex-shrink: 0;
}
.segment-nav-title {
  font-size: 12px;
  color: var(--n-text-color-3);
  padding: 0 8px 8px;
}
.segment-nav-list {
  flex: 1;
  overflow-y: auto;
  border-left: 1px solid var(--n-border-color);
}
.segment-nav-item {
  padding: 6px 8px 6px 12px;
  font-size: 13px;
  color: var(--n-text-color-2);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-left: 2px solid transparent;
  margin-left: -1px; /* 覆盖列表 border-left，高亮时替换为强调色 */
  transition: none;
}
.segment-nav-item:hover {
  color: var(--n-text-color);
  background: var(--n-color-embedded);
}
.segment-nav-item.active {
  color: var(--n-color-primary);
  border-left-color: var(--n-color-primary);
  font-weight: 600;
}
.segment-nav-item.unloaded {
  color: var(--n-text-color-3);
}
.segment-nav-empty {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--n-text-color-3);
}
.segment-nav-footer {
  padding-top: 8px;
}
</style>
