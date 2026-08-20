import { reactive, watch } from 'vue'
import type { BurstViewLevel } from '../types/photo'
import type { SegmentMode } from '../utils/segment'

const STORAGE_KEY = 'photo-agent-settings'

export interface AppSettings {
  backendUrl: string
  agentUrl: string
  /** 图片管理连拍展示级别：全部展开 / 精细折叠 / 模糊折叠 */
  burstViewLevel: BurstViewLevel
  /** 图片管理分段浏览方式：按天 / 按月 / 按活动 */
  segmentMode: SegmentMode
}

const defaults: AppSettings = {
  backendUrl: 'http://localhost:10004',
  agentUrl: 'http://localhost:10005',
  burstViewLevel: 'fine',
  segmentMode: 'month',
}

function load(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      return { ...defaults, ...parsed }
    }
  } catch {
    // 解析失败，使用默认值
  }
  return { ...defaults }
}

export const settings = reactive<AppSettings>(load())

// 自动持久化到 localStorage
watch(
  () => ({ ...settings }),
  (val) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(val))
  },
  { deep: true }
)

/** 重置为默认值 */
export function resetSettings() {
  Object.assign(settings, defaults)
}
