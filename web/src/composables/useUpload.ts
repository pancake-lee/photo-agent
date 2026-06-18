import { ref } from 'vue'
import { API_BASE } from '../config'
import type {
  UploadFile,
  UploadResponse,
  ConflictInfo,
  ConflictResolution,
} from '../types/upload'

// 上传弹窗状态
const showUploadModal = ref(false)
const files = ref<UploadFile[]>([])
const uploading = ref(false)

// 冲突队列
interface ConflictItem {
  file: UploadFile
  conflict: ConflictInfo
}
const conflictQueue = ref<ConflictItem[]>([])
const currentConflict = ref<ConflictItem | null>(null)

// 生成临时 ID
let idCounter = 0
function nextId(): string {
  return `upload_${Date.now()}_${++idCounter}`
}

export function useUpload() {
  function addFiles(rawFiles: FileList | File[]) {
    const arr = Array.from(rawFiles)
    for (const f of arr) {
      // 基本格式校验
      if (!f.type.startsWith('image/')) continue

      files.value.push({
        id: nextId(),
        originalFile: f,
        originalName: f.name,
        originalSize: f.size,
        compressedBlob: null,
        compressedSize: null,
        compressStatus: 'pending',
        uploadStatus: 'pending',
        shotAt: null,
      })
    }

    // 触发压缩
    for (const uf of files.value) {
      if (uf.compressStatus === 'pending') {
        compressFile(uf)
      }
    }
  }

  function removeFile(id: string) {
    files.value = files.value.filter((f) => f.id !== id)
  }

  async function compressFile(uf: UploadFile) {
    uf.compressStatus = 'compressing'
    try {
      // 动态导入压缩库（按需加载）
      const imageCompression = await import('browser-image-compression')
      const compressed = await imageCompression.default(uf.originalFile, {
        maxSizeMB: 0.5,
        maxWidthOrHeight: 2048,
        useWebWorker: true,
        fileType: 'image/jpeg',
        initialQuality: 0.85,
      })
      uf.compressedBlob = compressed
      uf.compressedSize = compressed.size
      uf.compressStatus = 'done'
    } catch {
      // 压缩失败：使用原文件上传
      uf.compressedBlob = uf.originalFile
      uf.compressedSize = uf.originalSize
      uf.compressStatus = 'done'
    }
  }

  async function readExif(file: File): Promise<string | null> {
    try {
      const exifr = await import('exifr')
      const data = await exifr.default.parse(file, ['DateTimeOriginal'])
      if (data?.DateTimeOriginal) {
        return new Date(data.DateTimeOriginal).toISOString()
      }
    } catch {
      // EXIF 读取失败静默
    }
    return null
  }

  async function uploadFile(
    uf: UploadFile,
    resolution?: ConflictResolution
  ): Promise<UploadResponse> {
    uf.uploadStatus = 'uploading'

    const formData = new FormData()
    const blob = uf.compressedBlob || uf.originalFile
    formData.append('file', blob, uf.originalName)
    formData.append('original_name', uf.originalName)

    if (uf.shotAt) {
      formData.append('original_shot_at', uf.shotAt)
    }
    if (resolution) {
      formData.append('conflict_resolution', resolution)
    }

    const resp = await fetch(`${API_BASE}/photos/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }

    return resp.json()
  }

  async function startUpload(onConflict: (item: ConflictItem) => Promise<ConflictResolution>) {
    uploading.value = true
    const pending = files.value.filter(
      (f) => f.uploadStatus === 'pending' && f.compressStatus === 'done'
    )

    for (const uf of pending) {
      try {
        // 读取 EXIF
        if (!uf.shotAt) {
          uf.shotAt = await readExif(uf.originalFile)
        }

        const result = await uploadFile(uf)

        if (result.status === 'conflict' && result.conflict) {
          uf.uploadStatus = 'conflict'
          const item: ConflictItem = { file: uf, conflict: result.conflict }
          conflictQueue.value.push(item)
          currentConflict.value = item

          // 等待用户选择
          const resolution = await onConflict(item)
          const retryResult = await uploadFile(uf, resolution)
          if (retryResult.status === 'stored') {
            uf.uploadStatus = 'done'
          } else if (retryResult.status === 'skipped') {
            uf.uploadStatus = 'done'
          }
        } else {
          uf.uploadStatus = 'done'
        }
      } catch {
        uf.uploadStatus = 'error'
      }
    }

    uploading.value = false
  }

  function openUploadModal() {
    files.value = []
    conflictQueue.value = []
    currentConflict.value = null
    showUploadModal.value = true
  }

  function closeUploadModal() {
    showUploadModal.value = false
  }

  return {
    showUploadModal,
    files,
    uploading,
    conflictQueue,
    currentConflict,
    addFiles,
    removeFile,
    startUpload,
    openUploadModal,
    closeUploadModal,
  }
}
