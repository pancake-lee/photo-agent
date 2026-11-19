// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'
import type { App } from 'vue'
import { NMessageProvider } from 'naive-ui'
import PhotoArchiveActions from './PhotoArchiveActions.vue'

let app: App | undefined
let container: HTMLDivElement | undefined

afterEach(() => {
  app?.unmount()
  container?.remove()
  vi.unstubAllGlobals()
})

describe('活动 NEF 清理', () => {
  it('按准确活动名预览，确认后只提交预览中的 NEF 并告知 30 天恢复期', async () => {
    const files = [{ id: 'unfavorite', path: '旅行 & 2026/one.NEF', bytes: 1024, sha256: 'digest' }]
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ files }) })
      .mockResolvedValueOnce({ ok: true, json: async () => [{ id: 'unfavorite', status: 'deleted' }] })
    vi.stubGlobal('fetch', fetch)
    const changed = vi.fn()
    container = document.createElement('div')
    document.body.append(container)
    app = createApp({ render: () => h(NMessageProvider, null, { default: () =>
      h(PhotoArchiveActions, { activity: '旅行 & 2026', onChanged: changed }),
    }) })
    app.mount(container)
    container.querySelector('button')!.click()
    await vi.waitFor(() => expect(document.body.textContent).toContain('one.NEF'))
    expect(fetch.mock.calls[0]![0]).toContain(`activity=${encodeURIComponent('旅行 & 2026')}`)
    expect(document.body.textContent).toContain('保留期为 30 天')
    const confirm = [...document.body.querySelectorAll('button')]
      .find((button) => button.textContent?.trim() === '确认移入最近删除')!
    confirm.click()
    await vi.waitFor(() => expect(changed).toHaveBeenCalledOnce())
    expect(fetch.mock.calls[1]![1]).toMatchObject({ method: 'POST', body: JSON.stringify(files) })
  })
})
