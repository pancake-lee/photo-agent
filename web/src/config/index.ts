// API 地址和上传配置常量

export const API_BASE = '/api/v1'

// 前端压缩参数
export const COMPRESS_CONFIG = {
  maxWidthOrHeight: 2048,
  quality: 0.85,
  maxSizeKB: 500,
  fileType: 'image/jpeg',
} as const

// VLM 队列轮询间隔（ms）
export const VLM_POLL_INTERVAL = 1500

// 照片列表默认分页
export const DEFAULT_PAGE_SIZE = 24
