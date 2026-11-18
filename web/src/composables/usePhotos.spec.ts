// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'
import type { App } from 'vue'
import { NMessageProvider } from 'naive-ui'
import { usePhotos } from './usePhotos'
import { settings } from '../stores/settings'
import PhotoFavoriteButton from '../components/PhotoFavoriteButton.vue'

const search = vi.hoisted(() => vi.fn())
vi.mock('../backend-sdk-client', () => ({
  photoApi: { photoServiceSearchPhotos: search }, timelineApi: {},
}))

let app: App | undefined
let container: HTMLDivElement | undefined
const previousLevel = settings.burstViewLevel

afterEach(() => {
  app?.unmount()
  container?.remove()
  settings.burstViewLevel = previousLevel
  vi.unstubAllGlobals()
})

describe('图片列表收藏状态', () => {
  it('读取收藏和组计数，详情操作即时同步已加载列表与组成员', async () => {
    settings.burstViewLevel = 'coarse'
    search.mockResolvedValue({ total: '3', items: [
      { id: 'cover', favorite: false, burstGroupId: 'group', groupFavoriteCount: 1, burstCount: 3, burstCover: true },
      { id: 'member', favorite: false, burstGroupId: 'group', groupFavoriteCount: 1, burstCount: 3 },
      { id: 'other', favorite: true, burstGroupId: 'other-group', groupFavoriteCount: 1 },
    ] })
    const store = usePhotos()
    await store.relocateTo(0)
    expect(store.error.value).toBeNull()
    expect(store.photos.value[0]).toMatchObject({ favorite: false, group_favorite_count: 1 })
    expect(store.photos.value[2]?.favorite).toBe(true)
    store.burstModalMembers.value = store.photos.value.slice(0, 2)
    const fetchMock = vi.fn().mockImplementation(async (_url, init) => ({
      ok: true, json: async () => ({ favorite: init?.body ? JSON.parse(init.body).favorite : false }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    container = document.createElement('div')
    document.body.append(container)
    app = createApp({ render: () => h(NMessageProvider, null, {
      default: () => h(PhotoFavoriteButton, { id: 'member',
        onChanged: (favorite: boolean) => store.updatePhotoFavorite('member', favorite) }),
    }) })
    app.mount(container)
    await vi.waitFor(() => expect(container!.querySelector('button')!.disabled).toBe(false))
    container.querySelector('button')!.click()
    await vi.waitFor(() => expect(store.photos.value[1]?.favorite).toBe(true))
    expect(store.photos.value[0]?.group_favorite_count).toBe(2)
    expect(store.burstModalMembers.value[0]?.group_favorite_count).toBe(2)
    expect(store.photos.value[2]?.group_favorite_count).toBe(1)
    store.updatePhotoFavorite('member', true)
    expect(store.photos.value[0]?.group_favorite_count).toBe(2)
    await vi.waitFor(() => expect(container!.querySelector('button')!.disabled).toBe(false))
    container.querySelector('button')!.click()
    await vi.waitFor(() => expect(store.photos.value[1]?.favorite).toBe(false))
    expect(store.photos.value[0]?.group_favorite_count).toBe(1)
    expect(store.burstModalMembers.value[1]?.favorite).toBe(false)
  })
})
