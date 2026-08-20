import { ref } from 'vue'
import { photoApi } from '../backend-sdk-client'
import type { ApiEmpty } from '../../backend-sdk/api'
import type { BurstGroupsStatus, BurstConfig, BurstProfileConfig } from '../types/photo'

// 连拍分组状态（全局单例，module-level ref）
const status = ref<BurstGroupsStatus>({
  running: false,
  processed: 0,
  total: 0,
  group_count: 0,
  coarse_group_count: 0,
})

let pollTimer: ReturnType<typeof setInterval> | null = null

/** 查询当前重算状态（未在跑时后端返回库内两档实际组数） */
async function fetchStatus() {
  try {
    const resp = await photoApi.photoServiceGetBurstGroupsStatus()
    status.value = {
      running: resp.running ?? false,
      processed: resp.processed ?? 0,
      total: resp.total ?? 0,
      group_count: resp.groupCount ?? 0,
      coarse_group_count: resp.coarseGroupCount ?? 0,
    }
  } catch (e) {
    console.warn('获取连拍分组状态失败', e)
  }
}

/** 轮询进度（已在跑时启动；跑完自动停止） */
function ensurePolling(onComplete?: () => void) {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await fetchStatus()
    if (!status.value.running) {
      stopPolling()
      onComplete?.()
    }
  }, 1500)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// SDK camelCase → 前端 snake_case
function adaptProfileConfig(c?: {
  timeWindowSec?: number
  hashThreshold?: number
  ssimThreshold?: number
  ssimGrayMin?: number
  ssimGrayMax?: number
}): BurstProfileConfig {
  return {
    time_window_sec: c?.timeWindowSec ?? 0,
    hash_threshold: c?.hashThreshold ?? 0,
    ssim_threshold: c?.ssimThreshold ?? 0,
    ssim_gray_min: c?.ssimGrayMin ?? 0,
    ssim_gray_max: c?.ssimGrayMax ?? 0,
  }
}

export function useBurstGroups() {
  /** 触发全量重算（一次算两档），返回后端状态（running / already_running） */
  async function rebuild(onComplete?: () => void): Promise<string> {
    const body: ApiEmpty = {}
    const resp = await photoApi.photoServiceRebuildBurstGroups(body)

    const st = (resp as { status?: string }).status ?? ''
    await fetchStatus()
    if (st === 'running' || st === 'already_running') {
      ensurePolling(onComplete)
    }
    return st
  }

  /** 读取两档阈值（后端在 DB 无记录时返回配置默认值） */
  async function fetchConfig(): Promise<BurstConfig> {
    const resp = await photoApi.photoServiceGetBurstGroupsConfig()
    return {
      fine: adaptProfileConfig(resp.fine),
      coarse: adaptProfileConfig(resp.coarse),
    }
  }

  /** 保存两档阈值（下次重算生效） */
  async function saveConfig(cfg: BurstConfig): Promise<void> {
    await photoApi.photoServiceUpdateBurstGroupsConfig({
      fine: {
        timeWindowSec: cfg.fine.time_window_sec,
        hashThreshold: cfg.fine.hash_threshold,
        ssimThreshold: cfg.fine.ssim_threshold,
        ssimGrayMin: cfg.fine.ssim_gray_min,
        ssimGrayMax: cfg.fine.ssim_gray_max,
      },
      coarse: {
        timeWindowSec: cfg.coarse.time_window_sec,
        hashThreshold: cfg.coarse.hash_threshold,
        ssimThreshold: cfg.coarse.ssim_threshold,
        ssimGrayMin: cfg.coarse.ssim_gray_min,
        ssimGrayMax: cfg.coarse.ssim_gray_max,
      },
    })
  }

  /** 设置组封面 */
  async function setCover(groupId: string, photoId: string): Promise<void> {
    await photoApi.photoServiceSetBurstGroupCover({ photoId }, groupId)
  }

  return { status, rebuild, fetchStatus, stopPolling, fetchConfig, saveConfig, setCover }
}
