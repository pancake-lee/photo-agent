<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NCard,
  NButton,
  NIcon,
  NTag,
  NSpace,
  NCode,
  NTooltip,
} from 'naive-ui'
import {
  ChevronDownOutline,
  ChevronUpOutline,
  CreateOutline,
  ImageOutline,
} from '@vicons/ionicons5'
import type { PipelineStep } from '../types/suggest'
import { isStepEditable } from '../types/suggest'

const props = defineProps<{
  step: PipelineStep
  editable?: boolean
}>()

const emit = defineEmits<{
  edit: [step: PipelineStep]
}>()

const expanded = ref(false)
const editing = ref(false)

const hasPayload = computed(() => !!props.step.payload_content)
const hasPhotoData = computed(() => {
  const d = props.step.data
  return (d.photo_ids?.length > 0) || (d.photo_sequence?.length > 0)
})

// 步骤中关联的照片 ID 列表
const stepPhotoIds = computed<string[]>(() => {
  const d = props.step.data
  if (d.photo_ids?.length > 0) return d.photo_ids
  if (d.photo_sequence?.length > 0) {
    return d.photo_sequence.map((s: any) => s.photo_id).filter(Boolean)
  }
  return []
})

// 照片缩略图 URL
function thumbUrl(photoId: string): string {
  return photoId ? `/api/v1/photos/${photoId}/image` : ''
}

function summaryText(): string {
  const d = props.step.data
  const e = props.step.event

  switch (e) {
    case 'suggest.stage1.sample':
      return `随机采样：${d.sample_size || 0} 张照片，覆盖 ${d.date_count || 0} 个日期`
    case 'suggest.stage1.llm.start':
      return `LLM 调用（模型: ${d.model || 'unknown'}，温度: ${d.temperature || '—'}，prompt ${d.prompt_chars || 0} 字符）`
    case 'suggest.stage1.llm.end':
      return `LLM 响应（耗时 ${d.duration_ms || 0}ms，输出 ${d.response_chars || 0} 字符）`
    case 'suggest.stage1.intuitions':
      return `生成 ${d.count || 0} 个主题直觉`
    case 'suggest.stage2.rag.start':
      return `RAG 检索：「${d.query || ''}」，Top ${d.n_results || 0}`
    case 'suggest.stage2.rag.end':
      return `RAG 匹配 ${d.matched_count || 0}/${d.total_retrieved || 0} 张照片`
    case 'suggest.stage2.diversity':
      return `多样性过滤：${d.before_count || 0} → ${d.after_count || 0} 张（${d.date_count || 0} 个日期）`
    case 'suggest.stage3.llm.start':
      return `LLM 调用（候选 ${d.candidate_count || 0} 张，prompt ${d.prompt_chars || 0} 字符）`
    case 'suggest.stage3.llm.end':
      return `LLM 响应（耗时 ${d.duration_ms || 0}ms，输出 ${d.response_chars || 0} 字符）`
    case 'suggest.stage3.proposal':
      return `提案「${d.title || ''}」`
    case 'suggest.stage3.validation':
      return `校验: ${d.hallucinated_count || 0} 个无效 ID，最终 ${d.final_photo_count || 0} 张`
    case 'suggest.stage3.time_span':
      return `时间跨度 ${d.span_days || 0} 天（${d.photo_count || 0} 张照片，${d.dated_count || 0} 张有日期）`
    case 'suggest.complete':
      return `管线完成：共 ${d.total_suggestions || 0} 个建议，耗时 ${d.total_duration_ms || 0}ms`
    case 'suggest.decision.pipeline':
      return `管线选择：${d.pipeline || d.reason || ''}`
    default:
      return d.reason || d.query || JSON.stringify(d).slice(0, 80)
  }
}

function handleEdit() {
  emit('edit', props.step)
}
</script>

<template>
  <NCard size="small" :bordered="true" class="step-card">
    <!-- 折叠态头部 -->
    <div class="step-header" @click="expanded = !expanded">
      <div class="step-header-left">
        <NIcon size="16">
          <ChevronDownOutline v-if="!expanded" />
          <ChevronUpOutline v-else />
        </NIcon>
        <span class="step-label">{{ step.label }}</span>
        <span class="step-summary">{{ summaryText() }}</span>
      </div>
      <NSpace v-if="editable && isStepEditable(step.event)" size="small" @click.stop>
        <NButton size="tiny" text @click="handleEdit">
          <template #icon>
            <NIcon size="14"><CreateOutline /></NIcon>
          </template>
          编辑
        </NButton>
      </NSpace>
    </div>

    <!-- 展开态：显示完整数据 -->
    <div v-if="expanded" class="step-body">
      <!-- 照片缩略图网格 -->
      <div v-if="stepPhotoIds.length > 0" class="photo-thumb-grid">
        <span class="field-label">
          <NIcon size="14"><ImageOutline /></NIcon>
          关联照片（{{ stepPhotoIds.length }} 张）
        </span>
        <div class="thumb-grid">
          <NTooltip
            v-for="pid in stepPhotoIds.slice(0, 24)"
            :key="pid"
            trigger="hover"
          >
            <template #trigger>
              <div class="thumb-item">
                <img
                  :src="thumbUrl(pid)"
                  :alt="pid.slice(0, 8)"
                  loading="lazy"
                  @error="(e: Event) => { (e.target as HTMLImageElement).style.display = 'none' }"
                />
              </div>
            </template>
            {{ pid }}
          </NTooltip>
        </div>
        <span v-if="stepPhotoIds.length > 24" class="thumb-more">
          还有 {{ stepPhotoIds.length - 24 }} 张...
        </span>
      </div>
      <!-- payload 内容（prompt/response 文本） -->
      <div v-if="hasPayload" class="step-payload">
        <span class="field-label">Payload</span>
        <NCode
          :code="step.payload_content.slice(0, 3000)"
          language="text"
          word-wrap
        />
        <span v-if="step.payload_content.length > 3000" class="truncate-hint">
          已截断，共 {{ step.payload_content.length }} 字符
        </span>
      </div>

      <!-- 数据字段（格式化 JSON） -->
      <div class="step-data">
        <span class="field-label">数据</span>
        <NCode
          :code="JSON.stringify(step.data, null, 2)"
          language="json"
          word-wrap
        />
      </div>
    </div>
  </NCard>
</template>

<style scoped>
.step-card {
  margin-bottom: 8px;
}
.step-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
}
.step-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.step-label {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.step-summary {
  font-size: 12px;
  color: var(--n-text-color-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.step-body {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--n-border-color);
}
.step-payload,
.step-data {
  margin-bottom: 8px;
}
.field-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
  margin-bottom: 4px;
}
.truncate-hint {
  font-size: 11px;
  color: var(--n-text-color-3);
}
.photo-thumb-grid {
  margin-bottom: 12px;
}
.thumb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  gap: 4px;
  margin-top: 6px;
}
.thumb-item {
  width: 80px;
  height: 80px;
  overflow: hidden;
  border-radius: 4px;
  border: 1px solid var(--n-border-color);
  background: var(--n-action-color);
}
.thumb-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-more {
  font-size: 11px;
  color: var(--n-text-color-3);
  margin-top: 4px;
  display: block;
}
</style>
