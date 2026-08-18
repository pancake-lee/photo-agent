// 照片相关类型

export interface Photo {
  id: string
  filename: string
  file_path: string
  timeline: string
  tags: string
  description: string
  shot_at: string | null
  width: number
  height: number
  brand: string
  model: string
  lens: string
  focal_length: string
  aperture: string
  iso: number
  exposure_time: string
  latitude: number | null
  longitude: number | null
  altitude: number | null
  imported_at: string
}

// 照片列表响应中的单项
export interface PhotoListItem extends Photo {
  has_description: boolean
  thumbnail_url: string
  has_nef: boolean
}

// 照片详情响应
export interface PhotoDetail extends Photo {
  has_description: boolean
  thumbnail_url: string
  image_url: string
  description_model: string
  description_time: string
}

// 列表响应
export interface PhotoListResponse {
  items: PhotoListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// 综合统计
export interface PhotoStats {
  total: number
  with_description: number
  without_description: number
  brands: { name: string; count: number }[]
  lens: { name: string; count: number }[]
  focal_ranges: { range: string; label: string; count: number }[]
  gps: { with_gps: number; without_gps: number }
  monthly: { month: string; count: number }[]
  hourly: { hour: number; count: number }[]
}

// VLM 队列状态
export interface VlmQueueStatus {
  running: boolean
  total: number
  completed: number
  failed: number
  current_file?: string
}

// Embedding 统计（Python Agent 交叉比对 Go 照片列表后返回）
export interface EmbedStats {
  with_embedding: number   // Go 中存在且已嵌入的照片数
  total_documents: number  // 有效文档数（已剔除孤立文档）
  total_photos: number     // Go 后端照片总数
  error?: string           // 获取失败时的错误信息
}

// Embedding 详情（单张照片）
export interface EmbedInfo {
  photo_id: string
  chunks: number
  model: string | null
  embedded_at: string | null
  chunk_info: Array<{
    id: string
    chunk_index: number
    preview: string
  }>
}

// Embed 队列状态
export interface EmbedQueueStatus {
  running: boolean
  total: number
  completed: number
  failed: number
  current_file?: string
}
