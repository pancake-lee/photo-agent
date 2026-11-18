// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import type { App } from 'vue'
import PhotoCard from './PhotoCard.vue'

let app: App | undefined
let container: HTMLDivElement | undefined

afterEach(() => {
  app?.unmount()
  container?.remove()
  vi.useRealTimers()
})

describe('照片 EXIF 悬浮提示', () => {
  it('延迟显示，弹层不接收鼠标事件且不阻止滚轮冒泡', async () => {
    vi.useFakeTimers()
    container = document.createElement('div')
    document.body.append(container)
    app = createApp(PhotoCard, {
      photo: { id: 'photo', filename: 'test.jpg', thumbnail_url: '', has_nef: false,
        burst_group_id: '', burst_cover: false, burst_count: 0, model: 'Test Camera' },
      showDelete: false,
    })
    app.mount(container)
    const card = container.querySelector<HTMLElement>('.photo-card')!
    card.dispatchEvent(new MouseEvent('mouseenter'))
    await vi.advanceTimersByTimeAsync(799)
    expect(container.querySelector('.n-tooltip')).toBeNull()
    await vi.advanceTimersByTimeAsync(1)
    await nextTick()
    const tooltip = container.querySelector<HTMLElement>('.n-tooltip')!
    expect(tooltip.textContent).toContain('Test Camera')
    expect(tooltip.style.pointerEvents).toBe('none')
    expect(card.style.pointerEvents).not.toBe('none')
    const scroll = vi.fn()
    container.addEventListener('wheel', scroll)
    const wheel = new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 100 })
    expect(card.dispatchEvent(wheel)).toBe(true)
    expect(wheel.defaultPrevented).toBe(false)
    expect(scroll).toHaveBeenCalledOnce()
    card.dispatchEvent(new MouseEvent('mouseleave'))
    await vi.advanceTimersByTimeAsync(300)
    expect(container.querySelector('.n-tooltip')).toBeNull()
  })
})
