export interface Session {
  session_id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  query_type?: string
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
}
