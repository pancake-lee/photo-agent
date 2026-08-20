<script setup lang="ts">
/**
 * PhotoSegmentDivider — 照片流分段分割线。
 *
 * 独占一行插入网格流中，显示分段标题（日期/活动名）与该段已加载照片数。
 * 挂载/卸载时向父级上报自身 DOM 元素，供导航高亮跟随与锚点跳转使用。
 */
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps<{
  /** 分段键（导航锚点标识） */
  segKey: string
  label: string
  subLabel?: string
  count: number
}>()

const emit = defineEmits<{
  mounted: [el: HTMLElement]
  unmounted: []
}>()

const rootEl = ref<HTMLElement | null>(null)

onMounted(() => {
  if (rootEl.value) emit('mounted', rootEl.value)
})
onBeforeUnmount(() => {
  emit('unmounted')
})
</script>

<template>
  <div ref="rootEl" class="segment-divider">
    <span class="segment-line" />
    <span class="segment-label">{{ label }}</span>
    <span v-if="subLabel" class="segment-sub">{{ subLabel }}</span>
    <span class="segment-count">{{ count }} 张</span>
    <span class="segment-line" />
  </div>
</template>

<style scoped>
.segment-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  grid-column: 1 / -1; /* CSS Grid 内跨全部列 */
  padding: 16px 0 8px;
}
.segment-line {
  flex: 1;
  height: 1px;
  background: var(--n-border-color);
}
.segment-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--n-text-color);
  white-space: nowrap;
}
.segment-sub {
  font-size: 12px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
.segment-count {
  font-size: 12px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
</style>
