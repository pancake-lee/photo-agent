// 上传相关类型

export type CompressStatus = 'pending' | 'compressing' | 'done' | 'error'
export type UploadStatus = 'pending' | 'uploading' | 'done' | 'conflict' | 'error'

export interface UploadFile {
  id: string
  originalFile: File
  originalName: string
  originalSize: number
  compressedBlob: Blob | null
  compressedSize: number | null
  compressStatus: CompressStatus
  uploadStatus: UploadStatus
  shotAt: string | null
}

export interface ConflictInfo {
  existing_photo_id: string
  existing_filename: string
  existing_thumbnail_url: string
  existing_shot_at: string
  new_shot_at: string
}

export interface UploadResponse {
  status: 'stored' | 'conflict' | 'skipped'
  photo_id: string
  conflict?: ConflictInfo
}

export type ConflictResolution = 'overwrite' | 'skip' | 'keep_both'
