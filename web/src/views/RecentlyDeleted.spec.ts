// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'
import type { App } from 'vue'
import { NMessageProvider } from 'naive-ui'
import RecentlyDeleted from './RecentlyDeleted.vue'
import SideMenu from '../components/SideMenu.vue'
import { createMemoryHistory, createRouter } from 'vue-router'

vi.mock('../composables/useChat', async () => {
  const { ref } = await import('vue')
  return { useChat: () => ({ sessions: ref([]), fetchSessions: vi.fn(),
    createSession: vi.fn(), deleteSessions: vi.fn() }) }
})

let app: App | undefined
let container: HTMLDivElement | undefined

afterEach(() => {
  app?.unmount()
  container?.remove()
  vi.unstubAllGlobals()
})

function mountPage() {
  container = document.createElement('div')
  document.body.append(container)
  app = createApp({ render: () => h(NMessageProvider, null, {
    default: () => h(RecentlyDeleted),
  }) })
  app.mount(container)
}

const items = [
  { id: 'nef', photo_id: 'photo', kind: 'nef', state: 'deleted',
    activity: '旅行', name: 'one.NEF', expires_at: '2099-01-01T00:00:00Z' },
  { id: 'expired', photo_id: 'old', kind: 'photo', state: 'deleted',
    activity: '旧活动', name: 'old.JPG', expires_at: '2000-01-01T00:00:00Z' },
]
const response = (value: unknown) => ({ ok: true, json: async () => value })

describe('独立最近删除页面', () => {
  it('列出仅 NEF 与整张照片，过期项不可恢复，恢复后刷新列表', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(items))
      .mockResolvedValueOnce(response([{ id: 'nef', status: 'restored' }]))
      .mockResolvedValueOnce(response([]))
    vi.stubGlobal('fetch', fetch)
    mountPage()
    await vi.waitFor(() => expect(container!.querySelectorAll('.recent-items li')).toHaveLength(2))
    expect(container!.textContent).toContain('仅 NEF')
    expect(container!.textContent).toContain('30 天')
    const buttons = container!.querySelectorAll<HTMLButtonElement>('.recent-items button')
    expect(buttons[0]!.disabled).toBe(false)
    expect(buttons[1]!.disabled).toBe(true)
    buttons[0]!.click()
    await vi.waitFor(() => expect(container!.textContent).toContain('已恢复 1 条'))
    expect(fetch.mock.calls[1]![0]).toMatch(/photo-recycle\/restore$/)
    expect(fetch.mock.calls[1]![1]).toMatchObject({ method: 'POST', body: '["nef"]' })
    expect(container!.querySelectorAll('.recent-items li')).toHaveLength(0)
  })

  it('加载失败显示原因，可刷新重试', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error('连接失败'))
      .mockResolvedValueOnce(response([]))
    vi.stubGlobal('fetch', fetch)
    mountPage()
    await vi.waitFor(() => expect(container!.textContent).toContain('连接失败'))
    const refresh = [...container!.querySelectorAll('button')].find((button) => button.textContent?.trim() === '刷新')!
    refresh.click()
    await vi.waitFor(() => expect(container!.textContent).toContain('暂无最近删除的照片'))
  })
})


describe('最近删除导航', () => {
  it('位于组图发现和设置之间，点击后路由与选中状态一致', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes:
      ['/cluster', '/recently-deleted', '/settings'].map((path) => ({ path, component: { render: () => null } })),
    })
    await router.push('/cluster')
    container = document.createElement('div')
    document.body.append(container)
    app = createApp({ render: () => h(NMessageProvider, null, { default: () => h(SideMenu) }) })
    app.use(router).mount(container)
    const entries = [...container.querySelectorAll<HTMLElement>('.bottom-item')]
    expect(entries.slice(-3).map((entry) => entry.textContent?.trim())).toEqual(['组图发现', '最近删除', '设置'])
    entries.at(-2)!.click()
    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe('/recently-deleted')
      expect(container!.querySelector('.bottom-item.active')?.textContent?.trim()).toBe('最近删除')
    })
  })
})
