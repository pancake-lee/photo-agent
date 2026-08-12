<script setup lang="ts">
import { computed } from 'vue'
import { NTag, NIcon, NButton, NCheckbox } from 'naive-ui'
import { CheckmarkCircleOutline, GitBranchOutline, GitCompareOutline, CloseOutline } from '@vicons/ionicons5'
import type { SuggestVersion } from '../types/suggest'

const props = defineProps<{
  versions: SuggestVersion[]
  currentVersionId: string
  compareMode?: boolean
  selectedCompareVersions?: string[]
  canCompare?: boolean
}>()

const emit = defineEmits<{
  switch: [versionId: string]
  'toggle-compare': []
  'toggle-version': [versionId: string]
}>()

const sorted = computed(() =>
  [...props.versions].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  )
)

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso.slice(0, 16)
  }
}

function createdFromLabel(from: string): string {
  switch (from) {
    case 'auto': return '自动生成'
    case 'manual': return '手动选题'
    case 'rerun': return '重跑'
    default: return from
  }
}

function createdFromColor(from: string): string {
  switch (from) {
    case 'auto': return '#7c3aed'
    case 'manual': return '#2080f0'
    case 'rerun': return '#f0a020'
    default: return '#999'
  }
}

const STEP_LABEL_MAP: Record<string, string> = {
  'suggest.stage1.sample': '采样',
  'suggest.stage1.llm.start': 'Stage 1 Prompt',
  'suggest.stage1.llm.end': 'Stage 1 直觉',
  'suggest.stage2.rag.start': 'RAG 查询',
  'suggest.stage2.rag.end': 'RAG 结果',
  'suggest.stage2.diversity': '多样性',
  'suggest.stage3.llm.start': 'Stage 3 Prompt',
  'suggest.stage3.llm.end': 'Stage 3 提案',
  'suggest.stage3.proposal': '提案数据',
  'suggest.stage3.validation': '照片序列',
}

function modifiedStepLabel(event: string | null): string {
  if (!event) return ''
  return STEP_LABEL_MAP[event] || event.split('.').pop() || event
}

function isCurrent(versionId: string): boolean {
  return versionId === props.currentVersionId
}
</script>

<template>
  <div class="version-timeline">
    <!-- 对比按钮 -->
    <div v-if="canCompare" class="compare-toggle">
      <NButton
        size="tiny"
        :type="compareMode ? 'primary' : 'default'"
        @click="emit('toggle-compare')"
      >
        <template #icon>
          <NIcon size="14">
            <GitCompareOutline v-if="!compareMode" />
            <CloseOutline v-else />
          </NIcon>
        </template>
        {{ compareMode ? '退出对比' : '对比' }}
      </NButton>
      <span v-if="compareMode" class="compare-hint">
        勾选 2 个版本
      </span>
    </div>

    <div
      v-for="ver in sorted"
      :key="ver.version_id"
      class="version-item"
      :class="{ current: isCurrent(ver.version_id) }"
      @click="compareMode ? emit('toggle-version', ver.version_id) : emit('switch', ver.version_id)"
    >
      <!-- 时间线连接线 -->
      <div class="timeline-line">
        <div class="timeline-dot" :class="{ active: isCurrent(ver.version_id) }">
          <NIcon v-if="isCurrent(ver.version_id)" size="12" color="#fff">
            <CheckmarkCircleOutline />
          </NIcon>
        </div>
        <div class="timeline-connector"></div>
      </div>

      <!-- 版本信息 -->
      <div class="version-info">
        <div class="version-header">
          <NCheckbox
            v-if="compareMode"
            :checked="selectedCompareVersions?.includes(ver.version_id)"
            size="small"
            @click.stop
          />
          <span class="version-id">{{ ver.version_id.split('-v')[1] || ver.version_id }}</span>
          <NTag
            size="tiny"
            :bordered="false"
            :color="{ color: createdFromColor(ver.created_from), textColor: '#fff' }"
          >
            {{ createdFromLabel(ver.created_from) }}
          </NTag>
        </div>
        <div class="version-time">{{ formatTime(ver.created_at) }}</div>
        <div v-if="ver.modified_step" class="version-modified">
          <NIcon size="12"><GitBranchOutline /></NIcon>
          修改了「{{ modifiedStepLabel(ver.modified_step) }}」
        </div>
        <div v-if="ver.trace_expired" class="version-expired">
          追踪数据已过期
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.version-timeline {
  display: flex;
  flex-direction: column;
}
.compare-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}
.compare-hint {
  font-size: 11px;
  color: var(--n-text-color-3);
}
.version-item {
  display: flex;
  gap: 12px;
  cursor: pointer;
  padding: 8px 4px;
  border-radius: 6px;
  transition: background 0.15s;
}
.version-item:hover {
  background: var(--n-action-color);
}
.version-item.current {
  background: var(--n-color-primary-pressed);
}
/* 时间线连接线 */
.timeline-line {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
  flex-shrink: 0;
}
.timeline-dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--n-border-color);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.timeline-dot.active {
  background: var(--n-color-primary);
}
.timeline-connector {
  width: 2px;
  flex: 1;
  min-height: 12px;
  background: var(--n-border-color);
}
.version-item:last-child .timeline-connector {
  display: none;
}
.version-item:last-child .version-info {
  padding-bottom: 0;
}
/* 版本信息 */
.version-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding-bottom: 8px;
}
.version-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.version-id {
  font-weight: 700;
  font-size: 14px;
  text-transform: uppercase;
}
.version-time {
  font-size: 11px;
  color: var(--n-text-color-3);
}
.version-modified {
  font-size: 11px;
  color: var(--n-text-color-2);
  display: flex;
  align-items: center;
  gap: 4px;
}
.version-expired {
  font-size: 11px;
  color: var(--n-warning-color);
}
</style>
