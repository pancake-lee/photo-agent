export interface Session {
  session_id: string
  title: string
  last_granularity: Granularity
  message_count: number
  created_at: string
  updated_at: string
}

export interface PhotoRef {
  photo_id: string
  filename: string
  image_url: string
  /** 连拍组粒度检索时才有：命中的连拍组 ID，photo_id 即该组封面 */
  burst_group_id?: string
  /** 该连拍组内的照片数 */
  burst_count?: number
}

/** 检索粒度：photo 单张照片 / fine 精细连拍组 / coarse 模糊连拍组 */
export type Granularity = 'photo' | 'fine' | 'coarse'

export interface RuntimeStep {
  step: number
  title: string
  status: string
  decision: string
  result: string
  facts: string[]
  details: Record<string, string | number>
}

export interface ChatMessage {
  id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  query_type?: string
  /** 请求执行轨迹编号，旧历史消息未记录时为空 */
  trace_id?: string
  /** AI 回复实际使用的检索粒度；旧历史消息未记录时为空 */
  granularity?: Granularity
  photos?: PhotoRef[]
  /** Runtime 多步执行的用户过程快照，旧消息为空数组。 */
  runtime_steps?: RuntimeStep[]
  input_tokens?: number
  output_tokens?: number
  cost?: number
  created_at: string
}

export interface ChatSessionDetail extends Session {
  messages: ChatMessage[]
}

export interface SendMessageResponse {
  message_id: number
  answer: string
  query_type: string
  granularity: Granularity
  photos?: PhotoRef[]
  trace_id: string
  runtime_steps?: RuntimeStep[]
}
