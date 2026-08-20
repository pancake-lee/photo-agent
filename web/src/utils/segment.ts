/**
 * 照片流分段分组计算（按天 / 按月 / 按活动）。
 *
 * 分段基于已加载照片流计算：照片已按拍摄时间升/降序排序，
 * 遍历时相邻照片分段键变化处即分割线位置。
 * shot_at 为空的照片归「未知时间」段，跟随其在本流中的自然落位
 * （升序在最后、降序在最前，与后端 SQL 排序一致），该段不进右侧导航。
 */
import type { PhotoListItem } from '../types/photo'

// 分段方式
export type SegmentMode = 'day' | 'month' | 'activity'

// 分割线/分段节点：插入位置以 segIndex 标记（位于流中第 segIndex 张照片之前）
export interface SegmentDivider {
  /** 分段键：day/month 为 YYYY-MM-DD / YYYY-MM，activity 为活动名（空串表示未分类） */
  key: string
  /** 分割线标题 */
  label: string
  /** 副标题（按天显示星期几，其余为空） */
  subLabel?: string
  /** 该分段内照片数（按已加载照片计算，随滚动加载递增） */
  count: number
  /** 分段内首张照片在流中的下标（即分割线插入位置） */
  segIndex: number
}

const UNKNOWN_LABEL = '未知时间'

/** 单张照片的分段键 */
function segKeyOf(photo: PhotoListItem, mode: SegmentMode): string {
  if (!photo.shot_at) return ''
  const d = new Date(photo.shot_at)
  if (Number.isNaN(d.getTime())) return ''
  if (mode === 'day') return d.toISOString().slice(0, 10)
  return d.toISOString().slice(0, 7)
}

/** 分段键转分割线标题 */
export function segLabelOf(key: string, mode: SegmentMode): string {
  if (key === '') return UNKNOWN_LABEL
  if (mode === 'day') return formatDayLabel(key)
  return formatMonthLabel(key)
}

function formatDayLabel(key: string): string {
  const [y, m, d] = key.split('-').map(Number)
  return `${y} 年 ${m} 月 ${d} 日`
}

function formatMonthLabel(key: string): string {
  const [y, m] = key.split('-').map(Number)
  return `${y} 年 ${m} 月`
}

/** 按天分段的副标题：星期几 */
export function segSubLabel(key: string, mode: SegmentMode): string {
  if (mode !== 'day' || key === '') return ''
  const [y, m, d] = key.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  const weekday = ['日', '一', '二', '三', '四', '五', '六'][date.getUTCDay()]
  return `星期${weekday}`
}

/**
 * 计算照片流的分段分割线列表。
 *
 * 按活动分段时活动段落在前（照片流顺序），无活动标签的散图归「未分类」段，
 * 若散图与活动照片在流中交错（理论上按 shot_at 排序不会，但筛选后可能），
 * 相同分段键的多个区间会各自产生分割线，segIndex 均指向该区间首张。
 */
export function computeDividers(
  photos: PhotoListItem[],
  mode: SegmentMode,
): SegmentDivider[] {
  const dividers: SegmentDivider[] = []

  let prevKey: string | null = null
  for (let i = 0; i < photos.length; i++) {
    const key =
      mode === 'activity' ? photos[i].timeline || '' : segKeyOf(photos[i], mode)
    if (key !== prevKey) {
      dividers.push({
        key,
        label: mode === 'activity' ? (key === '' ? '未分类' : key) : segLabelOf(key, mode),
        subLabel: mode === 'activity' ? undefined : segSubLabel(key, mode),
        count: 1,
        segIndex: i,
      })
      prevKey = key
    } else {
      dividers[dividers.length - 1].count++
    }
  }
  return dividers
}

/**
 * 分段键 → 导航高亮键。
 * 按天/按月导航都以月份为粒度（按天时天数过多，导航降为月份）。
 */
export function navKeyOfDivider(d: SegmentDivider, mode: SegmentMode): string {
  if (mode === 'activity') return d.key
  return d.key.slice(0, 7)
}
