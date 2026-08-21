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
