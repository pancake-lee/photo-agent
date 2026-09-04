import { describe, expect, it, vi } from 'vitest'
import { downloadPhotos } from './downloadPhotos'

describe('downloadPhotos', () => {
  it('posts the selected IDs and surfaces the API error', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: vi.fn().mockResolvedValue({ error: '存在找不到的照片' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(downloadPhotos(['a', 'b'])).rejects.toThrow('存在找不到的照片')
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/photos\/download$/), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ photo_ids: ['a', 'b'] }),
    }))
  })
})
