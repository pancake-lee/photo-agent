// 主题发现相关的类型定义

// ── 基础类型（与 SuggestView 现有类型兼容） ──

export interface HistoryItem {
  id: string
  generated_at: string
  total_photos: number
  cluster_count: number
  pipeline: string
  rating: number
  title: string
  angle: string
  rationale: string
  category: string
  photo_ids: string[]
  photo_sequence: Array<{ photo_id: string; role_in_narrative: string }>
  trace_id: string
  intuition_source: string[]
  error: string
}

// ── 管线步骤 ──

export interface PipelineStep {
  event: string
  label: string
  group: string
  stage: number
  timestamp: string
  data: Record<string, any>
  payload_content: string
  payload_ref: string
}

// ── 版本管理 ──

export interface SuggestVersion {
  version_id: string
  parent_version_id: string | null
  created_at: string
  created_from: 'auto' | 'manual' | 'rerun'
  modified_step: string | null
  trace_id: string
  trace_expired: boolean
  steps: PipelineStep[]
}

// ── 详情响应 ──

export interface SuggestHistoryDetail extends HistoryItem {
  versions: SuggestVersion[]
  current_version_id: string
}

// ── API 请求体 ──

export interface RerunRequest {
  from_step: string
  overrides: Record<string, any>
}

export interface ManualSuggestRequest {
  photo_ids: string[]
  intuition?: {
    title: string
    angle: string
    rationale: string
    inspired_indices: number[]
  } | null
}

export interface RandomSampleResult {
  photo_ids: string[]
  photos: Array<{ photo_id: string; description: string }>
  count: number
}

export interface RerunProgress {
  stage: number
  label: string
  status: 'running' | 'done'
}

// ── 步骤标签常量 ──

export const STEP_GROUP_LABELS: Record<string, string> = {
  'Stage 1 灵感发现': '💡 Stage 1 灵感发现',
  'Stage 2 扩展选片': '🔍 Stage 2 扩展选片',
  'Stage 3 选题提案': '📝 Stage 3 选题提案',
  '决策': '⚙️ 管线决策',
  '汇总': '✅ 汇总',
}

export const EDITABLE_STEPS = [
  'suggest.stage1.sample',      // 可编辑采样照片列表
  'suggest.stage1.llm.start',   // 可编辑 prompt 文本
  'suggest.stage1.llm.end',     // 可编辑直觉 JSON
  'suggest.stage2.rag.start',   // 可编辑查询文本
  'suggest.stage2.rag.end',     // 可编辑匹配照片列表
  'suggest.stage2.diversity',   // 可编辑过滤后照片列表
  'suggest.stage3.llm.start',   // 可编辑 prompt 文本
  'suggest.stage3.llm.end',     // 可编辑提案 JSON
  'suggest.stage3.proposal',    // 可编辑提案数据
  'suggest.stage3.validation',  // 可编辑最终照片序列
]

// 步骤是否可编辑
export function isStepEditable(event: string): boolean {
  return EDITABLE_STEPS.includes(event)
}
