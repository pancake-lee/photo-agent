import { afterAll, describe, expect, it } from 'vitest'
import { computeDividers, localSegmentKeyOf } from './segment'
import type { PhotoListItem } from '../types/photo'

const originalTimezone = process.env.TZ
process.env.TZ = 'Asia/Shanghai'

function photo(id: string, shotAt: string): PhotoListItem {
  return {
    id,
    filename: '',
    file_path: '',
    timeline: '',
    tags: '',
    description: '',
    shot_at: shotAt,
    width: 0,
    height: 0,
    brand: '',
    model: '',
    lens: '',
    focal_length: '',
    aperture: '',
    iso: 0,
    exposure_time: '',
    latitude: null,
    longitude: null,
    altitude: null,
    imported_at: '',
    has_description: false,
    thumbnail_url: '',
    has_nef: false,
    burst_group_id: '',
    burst_cover: false,
    burst_count: 0,
  }
}

afterAll(() => { process.env.TZ = originalTimezone })

describe('本地时区分段键', () => {
  it('东八区凌晨照片归入本地当天与当月', () => {
    const item = photo('p1', '2026-01-01T00:30:00+08:00')
    expect(localSegmentKeyOf(item, 'day')).toBe('2026-01-01')
    expect(localSegmentKeyOf(item, 'month')).toBe('2026-01')
  })

  it('跨年照片生成两个独立的月份分割线', () => {
    const dividers = computeDividers([
      photo('p1', '2026-12-31T23:30:00+08:00'),
      photo('p2', '2027-01-01T00:30:00+08:00'),
    ], 'month')
    expect(dividers.map((item) => item.key)).toEqual(['2026-12', '2027-01'])
  })
})

describe('活动归属不依赖拍摄时间', () => {
  it.each([null, '', 'invalid-date'])('缺少有效时间 %s 时保留活动分组', (shotAt) => {
    const item = { ...photo('IMG_4182', ''), shot_at: shotAt, timeline: '202608-山西旅游' }
    expect(localSegmentKeyOf(item, 'activity')).toBe('202608-山西旅游')
    expect(localSegmentKeyOf(item, 'day')).toBe('')
    expect(localSegmentKeyOf(item, 'month')).toBe('')
    expect(computeDividers([item], 'activity')).toMatchObject([
      { key: '202608-山西旅游', label: '202608-山西旅游', count: 1, segIndex: 0 },
    ])
  })

  it('同一活动中的无时间照片计入该段，只有无活动照片显示未分类', () => {
    const known = { ...photo('dated', '2026-08-01T12:00:00+08:00'), timeline: '202608-山西旅游' }
    const unknown = { ...photo('undated', ''), timeline: known.timeline }
    const unclassified = photo('loose', '')
    expect(computeDividers([known, unknown, unclassified], 'activity')).toMatchObject([
      { key: known.timeline, label: known.timeline, count: 2, segIndex: 0 },
      { key: '', label: '未分类', count: 1, segIndex: 2 },
    ])
    expect(computeDividers([unknown], 'month')).toMatchObject([
      { key: '', label: '未知时间', count: 1 },
    ])
  })
})
