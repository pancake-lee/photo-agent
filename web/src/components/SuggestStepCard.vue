<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NCard,
  NButton,
  NIcon,
  NSpace,
  NCode,
  NTooltip,
} from 'naive-ui'
import {
  ChevronDownOutline,
  ChevronUpOutline,
  CreateOutline,
  ImageOutline,
  CodeOutline,
} from '@vicons/ionicons5'
import type { PipelineStep } from '../types/suggest'
import { isStepEditable } from '../types/suggest'
import { getApiBase } from '../config'

const props = defineProps<{
  step: PipelineStep
  editable?: boolean
}>()

const emit = defineEmits<{
  edit: [step: PipelineStep]
}>()

const expanded = ref(false)

const hasPayload = computed(() => !!props.step.payload_content)

// 步骤是否有可视化内容（照片或 payload）
const hasVisualContent = computed(() => {
  if (hasPayload.value) return true
  const d = props.step.data
  return !!(d.photo_ids?.length || d.photo_sequence?.length || d.kept_photo_ids?.length)
})

// 无可视化内容的步骤，数据默认展开（数据是唯一内容）
const dataExpanded = ref(!hasVisualContent.value)

// 步骤事件类型判断
const isRagEnd = computed(() => props.step.event === 'suggest.stage2.rag.end')
const isDiversity = computed(() => props.step.event === 'suggest.stage2.diversity')
const isProposal = computed(() => props.step.event === 'suggest.stage3.proposal')

// 步骤中关联的照片 ID 列表
const stepPhotoIds = computed<string[]>(() => {
  const d = props.step.data
  if (d.photo_ids?.length > 0) return d.photo_ids
  if (d.photo_sequence?.length > 0) {
    return d.photo_sequence.map((s: any) => s.photo_id).filter(Boolean)
  }
  // diversity 步骤：使用 kept_photo_ids
  if (d.kept_photo_ids?.length > 0) return d.kept_photo_ids
  return []
})

// RAG 特有数据
const distances = computed<(number | null)[]>(() => {
  return props.step.data.distances || []
})
const ratioGaps = computed<number[]>(() => {
  return props.step.data.ratio_gaps || []
})

// 提案的 photo_sequence（含 role_in_narrative）
const photoSequence = computed<Array<{ photo_id: string; role_in_narrative: string }>>(() => {
  return props.step.data.photo_sequence || []
})

// 多样性过滤详情（仅保留有实际移除的组）
const diversityDetails = computed<Array<{
  date: string
  kept_photo_ids: string[]
  removed_photo_ids?: string[]
  reason?: string
}>>(() => {
  const details = props.step.data.diversity_details || []
  return details.filter((d: any) => d.removed_photo_ids?.length > 0)
})

// 照片缩略图 URL
function thumbUrl(photoId: string): string {
  return photoId ? `${getApiBase()}/photos/${photoId}/image` : ''
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
      <!-- ── RAG 匹配结果：全部缩略图 + distances/ratio_gaps ── -->
      <template v-if="isRagEnd && stepPhotoIds.length > 0">
        <div class="photo-section">
          <span class="field-label">
            <NIcon size="14"><ImageOutline /></NIcon>
            匹配照片（{{ stepPhotoIds.length }} 张）
          </span>
          <div class="thumb-grid">
            <NTooltip v-for="(pid, idx) in stepPhotoIds" :key="pid" trigger="hover">
              <template #trigger>
                <div class="thumb-item-with-meta">
                  <div class="thumb-item">
                    <img
                      :src="thumbUrl(pid)"
                      :alt="pid.slice(0, 8)"
                      loading="lazy"
                      @error="(e: Event) => { (e.target as HTMLImageElement).style.display = 'none' }"
                    />
                  </div>
                  <span class="photo-meta">距离 {{ distances[idx] ?? '—' }}</span>
                  <span v-if="idx < ratioGaps.length" class="photo-meta">
                    比值 {{ ratioGaps[idx] }}
                  </span>
                </div>
              </template>
              {{ pid }}
            </NTooltip>
          </div>
        </div>
      </template>

      <!-- ── 多样性过滤：展示保留/移除的因果关系 ── -->
      <template v-else-if="isDiversity && diversityDetails.length > 0">
        <div class="photo-section">
          <span class="field-label">
            <NIcon size="14"><ImageOutline /></NIcon>
            多样性过滤详情（{{ step.data.before_count || 0 }} → {{ step.data.after_count || 0 }} 张）
          </span>
          <div v-for="(detail, gi) in diversityDetails" :key="gi" class="diversity-group">
            <div class="diversity-date-label">{{ detail.date }}</div>

            <!-- 保留的照片 -->
            <div class="kept-section">
              <span class="kept-label">✓ 保留 {{ detail.kept_photo_ids.length }} 张</span>
              <div class="thumb-grid">
                <NTooltip v-for="pid in detail.kept_photo_ids" :key="pid" trigger="hover">
                  <template #trigger>
                    <div class="thumb-item kept">
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
            </div>

            <!-- 移除的照片 -->
            <div v-if="detail.removed_photo_ids?.length" class="removed-section">
              <span class="removed-label">✗ {{ detail.reason }}</span>
              <div class="thumb-grid">
                <NTooltip v-for="pid in detail.removed_photo_ids" :key="pid" trigger="hover">
                  <template #trigger>
                    <div class="thumb-item removed">
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
            </div>
          </div>
        </div>
      </template>

      <!-- ── 提案解析：缩略图 + 叙事角色 ── -->
      <template v-else-if="isProposal && photoSequence.length > 0">
        <div class="photo-section">
          <span class="field-label">
            <NIcon size="14"><ImageOutline /></NIcon>
            推荐照片序列（{{ photoSequence.length }} 张）
          </span>
          <div class="thumb-grid">
            <NTooltip v-for="seq in photoSequence" :key="seq.photo_id" trigger="hover">
              <template #trigger>
                <div class="thumb-item-with-meta">
                  <div class="thumb-item">
                    <img
                      :src="thumbUrl(seq.photo_id)"
                      :alt="seq.photo_id.slice(0, 8)"
                      loading="lazy"
                      @error="(e: Event) => { (e.target as HTMLImageElement).style.display = 'none' }"
                    />
                  </div>
                  <span class="photo-meta narrative-role">{{ seq.role_in_narrative }}</span>
                </div>
              </template>
              {{ seq.photo_id }}
            </NTooltip>
          </div>
        </div>
      </template>

      <!-- ── 通用缩略图（非 RAG/提案步骤，或多样性无移除时回退） ── -->
      <template v-else-if="stepPhotoIds.length > 0 && !isRagEnd && !isProposal">
        <div class="photo-section">
          <span class="field-label">
            <NIcon size="14"><ImageOutline /></NIcon>
            关联照片（{{ stepPhotoIds.length }} 张）
          </span>
          <div class="thumb-grid">
            <NTooltip v-for="pid in stepPhotoIds" :key="pid" trigger="hover">
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
        </div>
      </template>

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

      <!-- 数据字段（折叠态，默认收起） -->
      <div class="step-data">
        <div class="data-toggle" @click="dataExpanded = !dataExpanded">
          <NIcon size="14">
            <ChevronDownOutline v-if="!dataExpanded" />
            <ChevronUpOutline v-else />
          </NIcon>
          <NIcon size="14"><CodeOutline /></NIcon>
          <span class="data-toggle-label">原始数据</span>
        </div>
        <NCode
          v-if="dataExpanded"
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
.step-payload {
  margin-bottom: 8px;
}
.field-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
  margin-bottom: 6px;
}
.truncate-hint {
  font-size: 11px;
  color: var(--n-text-color-3);
}

/* ── 照片区域 ── */
.photo-section {
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
.thumb-item.kept {
  border-color: var(--n-color-success);
  border-width: 2px;
}
.thumb-item.removed {
  border-color: var(--n-color-error);
  border-width: 2px;
  opacity: 0.7;
}

/* ── 带元数据的缩略图项 ── */
.thumb-item-with-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.thumb-item-with-meta .thumb-item {
  margin-bottom: 2px;
}
.photo-meta {
  font-size: 10px;
  color: var(--n-text-color-3);
  text-align: center;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.3;
}
.narrative-role {
  color: var(--n-color-primary);
  font-weight: 500;
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* ── 多样性过滤 ── */
.diversity-group {
  margin-bottom: 10px;
  padding: 8px;
  background: var(--n-action-color);
  border-radius: 6px;
}
.diversity-date-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-2);
  margin-bottom: 4px;
}
.kept-section {
  margin-bottom: 6px;
}
.kept-label {
  font-size: 11px;
  color: var(--n-color-success);
  font-weight: 500;
}
.removed-section {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px dashed var(--n-border-color);
}
.removed-label {
  font-size: 11px;
  color: var(--n-color-error);
  font-weight: 500;
}

/* ── 数据折叠 ── */
.step-data {
  margin-bottom: 8px;
}
.data-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 4px 0;
  user-select: none;
}
.data-toggle-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
}
</style>
