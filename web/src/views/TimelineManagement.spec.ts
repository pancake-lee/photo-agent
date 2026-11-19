// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import type { App } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { NMessageProvider } from 'naive-ui'
import TimelineManagement from './TimelineManagement.vue'

vi.mock('../backend-sdk-client', () => ({
  timelineApi: {
    timelineServiceListEvents: vi.fn().mockResolvedValue({
      events: [
        { id: 'shanxi', event: '202608-山西旅游', photoCount: 5 },
        { id: 'empty', event: '202611-待整理 & 旅行', photoCount: 0, note: '很长的备注不会改变各行操作所在列' },
      ],
    }),
  },
}))

let app: App | undefined
let container: HTMLDivElement | undefined

afterEach(() => {
  app?.unmount()
  container?.remove()
})

describe('时间线活动图片入口', () => {
  it('活动按钮携带原始目录名跳转，包括无照片的活动', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/timelines', component: TimelineManagement },
        { path: '/photos', component: { render: () => null } },
      ],
    })
    await router.push('/timelines')
    container = document.createElement('div')
    document.body.append(container)
    app = createApp({ render: () => h(NMessageProvider, null, {
      default: () => h(TimelineManagement),
    }) })
    app.use(router).mount(container)
    await nextTick()
    await nextTick()

    const rows = container.querySelectorAll('.event-item')
    expect(rows).toHaveLength(2)
    expect(container.querySelector('.event-list > table')).not.toBeNull()
    for (const row of rows) {
      expect(row.querySelectorAll('td')).toHaveLength(4)
      expect(row.querySelector('td:last-child')?.classList.contains('event-actions')).toBe(true)
    }
    for (const [index, name] of ['202608-山西旅游', '202611-待整理 & 旅行'].entries()) {
      const button = [...rows[index]!.querySelectorAll('button')]
        .find((item) => item.textContent?.trim() === '查看图片')
      expect(button?.disabled).toBe(false)
      button!.click()
      await vi.waitFor(() => {
        expect(router.currentRoute.value.path).toBe('/photos')
        expect(router.currentRoute.value.query.activity).toBe(name)
      })
    }
  })
})
