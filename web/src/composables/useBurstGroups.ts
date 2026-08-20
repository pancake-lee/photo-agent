import { ref } from 'vue'
import { photoApi } from '../backend-sdk-client'
import type { ApiEmpty } from '../../backend-sdk/api'
import type { BurstGroupsStatus } from '../types/photo'

// 连拍分组状态（全局单例，module-level ref）
const status = ref<BurstGroupsStatus>({
  running: false,
  processed: 0,
  total: 0,
  group_count: 0,
})

let pollTimer: ReturnType<typeof setInterval> | null = null

/** 查询当前重算状态（未在跑时后端返回库内实际组数） */
async function fetchStatus() {
  try {
    const resp = await photoApi.photoServiceGetBurstGroupsStatus()
    status.value = {
      running: resp.running ?? false,
      processed: resp.processed ?? 0,
      total: resp.total ?? 0,
      group_count: resp.groupCount ?? 0,
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

export function useBurstGroups() {
  /** 触发全量重算，返回后端状态（running / already_running） */
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

  return { status, rebuild, fetchStatus, stopPolling }
}
