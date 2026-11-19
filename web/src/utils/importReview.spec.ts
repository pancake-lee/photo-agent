import { describe, expect, it, vi, afterEach } from 'vitest'
import { editImportReview, getImportReview, importReviewLink } from './importReview'
vi.mock('../config', () => ({ getApiBase: () => '/api/v1' }))
afterEach(() => vi.unstubAllGlobals())
describe('跨设备选片协议', () => {
  it('链接保留部署路径，使用 hash 路由定位批次，只接受网页地址', () => {
    expect(importReviewLink('https://photos.test/app/', 'a b')).toBe('https://photos.test/app/#/import?batch=a%20b')
    expect(importReviewLink('javascript:alert(1)', 'x')).toBe('')
    expect(importReviewLink('', 'x')).toBe('')
  })
  it('提交只包含实际变更照片，刷新不带旧决定，错误保留服务器原因', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('{}')).mockResolvedValueOnce(new Response('{}'))
      .mockResolvedValueOnce(new Response('{"error":"PC 已结束选片"}', { status: 409 }))
    vi.stubGlobal('fetch', fetch)
    await editImportReview('batch', [{ id: 'one', decision: 'favorite' }])
    const options = fetch.mock.calls[0]![1]!
    expect(JSON.parse(options.body)).toEqual({ batch_id: 'batch', changes: [{ id: 'one', decision: 'favorite' }] })
    await getImportReview('batch')
    expect(fetch.mock.calls[1]![1]!.body).toBeUndefined()
    await expect(getImportReview('batch')).rejects.toThrow('PC 已结束选片')
  })
})
