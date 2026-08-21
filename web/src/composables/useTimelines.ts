import { ref } from 'vue'
import { timelineApi } from '../backend-sdk-client'
import type {
  ApiTimelineEventDetail,
  ApiListTimelineEventsResponse,
} from '../../backend-sdk/api'

// ------------------------------------------------------------------ #
// 类型
// ------------------------------------------------------------------ #

export interface TimelineEventItem {
  id: string
  /** 事件为 YYYY-MM-DD；散片组为 YYYY-MM */
  date: string
  event: string
  note: string
  photo_count: number
  is_scattered: boolean
}

export interface RecomputeStatus {
  running: boolean
  processed: number
  total: number
  event_count: number
  scattered_count: number
}

// ------------------------------------------------------------------ #
// 全局状态（module-level 单例）
// ------------------------------------------------------------------ #

const events = ref<TimelineEventItem[]>([])
const scattered = ref<TimelineEventItem[]>([])
const eventsLoading = ref(false)
const eventsError = ref<string | null>(null)

const recomputeStatus = ref<RecomputeStatus>({
  running: false,
  processed: 0,
  total: 0,
  event_count: 0,
  scattered_count: 0,
})

let pollTimer: ReturnType<typeof setInterval> | null = null

// SDK camelCase → 前端 snake_case
function adaptEvent(e?: ApiTimelineEventDetail): TimelineEventItem {
  return {
    id: e?.id ?? '',
    date: e?.date ?? '',
    event: e?.event ?? '',
    note: e?.note ?? '',
    photo_count: e?.photoCount ?? 0,
    is_scattered: e?.isScattered ?? false,
  }
}

export function useTimelines() {
  /** 拉取事件列表 + 散片组 */
  async function fetchEvents() {
    eventsLoading.value = true
    eventsError.value = null
    try {
      const resp: ApiListTimelineEventsResponse = await timelineApi.timelineServiceListEvents()
      events.value = (resp.events ?? []).map(adaptEvent)
      scattered.value = (resp.scattered ?? []).map(adaptEvent)
    } catch (e) {
      eventsError.value = e instanceof Error ? e.message : '获取时间线事件失败'
    } finally {
      eventsLoading.value = false
    }
  }

  /** 保存事件（新建与更新合一），返回事件 id */
  async function saveEvent(input: { id?: string; date: string; event: string; note?: string }): Promise<string> {
    const resp = await timelineApi.timelineServiceSaveEvent({
      id: input.id ?? '',
      date: input.date,
      event: input.event,
      note: input.note ?? '',
    })
    return resp.id ?? ''
  }

  /** 删除事件 */
  async function deleteEvent(id: string): Promise<void> {
    await timelineApi.timelineServiceDeleteEvent(id)
  }

  /** 查询重算进度 */
  async function fetchRecomputeStatus() {
    try {
      const resp = await timelineApi.timelineServiceGetRecomputeTimelinesStatus()
      recomputeStatus.value = {
        running: resp.running ?? false,
        processed: resp.processed ?? 0,
        total: resp.total ?? 0,
        event_count: resp.eventCount ?? 0,
        scattered_count: resp.scatteredCount ?? 0,
      }
    } catch (e) {
      console.warn('获取时间线重算状态失败', e)
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /** 触发全量重算，轮询进度，跑完调用 onComplete */
  async function recompute(onComplete?: () => void): Promise<string> {
    const resp = await timelineApi.timelineServiceRecomputeTimelines({})
    const st = (resp as { status?: string }).status ?? ''
    await fetchRecomputeStatus()
    if (st === 'running' || st === 'already_running') {
      if (!pollTimer) {
        pollTimer = setInterval(async () => {
          await fetchRecomputeStatus()
          if (!recomputeStatus.value.running) {
            stopPolling()
            onComplete?.()
          }
        }, 1500)
      }
    }
    return st
  }

  return {
    events,
    scattered,
    eventsLoading,
    eventsError,
    recomputeStatus,
    fetchEvents,
    saveEvent,
    deleteEvent,
    recompute,
    fetchRecomputeStatus,
    stopPolling,
  }
}
