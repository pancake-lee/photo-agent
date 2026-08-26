export interface GoldenPhotoRef {
  photo_id: string
  filename: string
  uuid: string
  granularity?: 'photo' | 'fine' | 'coarse'
  burst_group_id?: string
  burst_count?: number
}

export interface GoldenQuery {
  id: string
  query_text: string
  relevant_photos: GoldenPhotoRef[]
  category: string
  notes: string
  created_at: string
}

export interface EvalPhotoItem {
  photo_id: string
  filename: string
  uuid: string
}

export interface EvalDetail {
  golden_id: string
  question: string
  precision: number
  recall: number
  mrr: number
  hits: number
  retrieved: number
  relevant: number
  effective_k: number
  hit_ids: EvalPhotoItem[]
  miss_ids: EvalPhotoItem[]
  remaining_ids: EvalPhotoItem[]
}

export interface EvalResult {
  precision_at_k: number
  recall_at_k: number
  mrr: number
  total: number
  precision_k: number
  details: EvalDetail[]
}
