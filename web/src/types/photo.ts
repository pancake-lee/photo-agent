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
  burst_group_id: string
  burst_cover: boolean
  burst_count: number
}

// 照片详情响应
export interface PhotoDetail extends Photo {
  has_description: boolean
  thumbnail_url: string
  image_url: string
  description_model: string
  description_time: string
  ai_health_status: string
  ai_health_reason: string
  vlm_status: string
  vlm_reason: string
  embedding_status: string
  embedding_description_time: string
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

// 连拍分组重算状态
export interface BurstGroupsStatus {
  running: boolean
  processed: number
  total: number
  group_count: number        // 精细档组数
  coarse_group_count: number // 模糊档组数
}

// 连拍参数档位：fine 精细 / coarse 模糊
export type BurstProfile = 'fine' | 'coarse'

// 图片管理展示级别：全部展开 / 精细折叠 / 模糊折叠
export type BurstViewLevel = 'all' | 'fine' | 'coarse'

// 单档分组阈值
export interface BurstProfileConfig {
  time_window_sec: number
  hash_threshold: number
  ssim_threshold: number
  ssim_gray_min: number
  ssim_gray_max: number
}

// 两档分组阈值
export interface BurstConfig {
  fine: BurstProfileConfig
  coarse: BurstProfileConfig
}
