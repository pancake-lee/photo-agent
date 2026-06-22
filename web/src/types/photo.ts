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
