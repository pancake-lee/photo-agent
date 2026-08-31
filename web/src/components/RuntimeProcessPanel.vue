<script setup lang="ts">
import { NTag } from 'naive-ui'
import type { RuntimeStep } from '../types/chat'

// Runtime 多步执行过程面板。active 表示该消息正在流式执行：面板出现即自动展开，
// 终态后恢复默认收起；历史消息与普通查询不展开。
defineProps<{
  steps: RuntimeStep[]
  active?: boolean
}>()
</script>

<template>
  <details class="runtime-process" :open="active || undefined">
    <summary>执行过程（{{ steps.length }} 步）</summary>
    <div v-if="active && !steps.length" class="runtime-step-text">正在规划任务...</div>
    <div v-for="step in steps" :key="step.step" class="runtime-step">
      <div class="runtime-step-title">
        <strong>第 {{ step.step }} 步：{{ step.title }}</strong>
        <NTag size="tiny" :bordered="false" type="info">{{ step.status }}</NTag>
      </div>
      <div v-if="step.decision" class="runtime-step-text">{{ step.decision }}</div>
      <div v-if="step.result" class="runtime-step-text">{{ step.result }}</div>
      <div v-for="fact in step.facts" :key="fact" class="runtime-step-fact">{{ fact }}</div>
      <details v-if="Object.keys(step.details).length" class="runtime-details">
        <summary>执行细节</summary>
        <div v-for="(value, key) in step.details" :key="key" class="runtime-detail-row">
          <span>{{ key }}</span><code>{{ value }}</code>
        </div>
      </details>
    </div>
  </details>
</template>

<style scoped>
.runtime-process {
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--n-border-color);
  font-size: 13px;
}
.runtime-process > summary,
.runtime-details > summary {
  cursor: pointer;
  color: var(--n-text-color-2);
  font-weight: 500;
}
.runtime-step {
  margin-top: 12px;
  padding-left: 12px;
  border-left: 2px solid var(--n-border-color);
}
.runtime-step-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.runtime-step-text,
.runtime-step-fact {
  margin-top: 4px;
  color: var(--n-text-color-2);
}
.runtime-step-fact {
  color: var(--n-color-info);
}
.runtime-details {
  margin-top: 8px;
}
.runtime-detail-row {
  display: flex;
  gap: 8px;
  margin-top: 4px;
  color: var(--n-text-color-3);
}
.runtime-detail-row code {
  overflow-x: auto;
  white-space: pre-wrap;
}
</style>
