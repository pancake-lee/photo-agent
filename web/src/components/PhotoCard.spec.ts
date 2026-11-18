// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
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

describe('照片列表收藏角标', () => {
  it('单张、选择模式和折叠组展示对应收藏状态，NEF 标识共存', async () => {
    const item = ref({ id: 'favorite', filename: 'favorite.jpg', thumbnail_url: '', has_nef: true,
      burst_group_id: 'group', burst_cover: false, burst_count: 3, favorite: false, group_favorite_count: 0 })
    const expanded = ref(false)
    container = document.createElement('div')
    document.body.append(container)
    app = createApp({ render: () => h(PhotoCard, { photo: item.value,
      selectionMode: true, showDelete: false, showTooltip: false, viewLevel: expanded.value ? 'all' : 'coarse' }) })
    app.mount(container)
    expect(container.querySelector('.photo-favorite-badge')).toBeNull()
    item.value.favorite = true
    await nextTick()
    expect(container.querySelector('.photo-favorite-badge')?.textContent).toContain('已收藏')
    expect(container.querySelector('.n-checkbox')).not.toBeNull()
    expect(container.querySelector('.photo-badge')?.textContent).toBe('NEF')
    item.value = { ...item.value, favorite: false, burst_cover: true, group_favorite_count: 1 }
    await nextTick()
    expect(container.querySelector('.photo-favorite-badge')?.textContent).toContain('部分收藏')
    expect(container.querySelector('.photo-favorite-badge')?.getAttribute('title')).toContain('1 张')
    item.value.group_favorite_count = 3
    await nextTick()
    expect(container.querySelector('.photo-favorite-badge')?.textContent).toContain('全组收藏')
    expanded.value = true
    await nextTick()
    expect(container.querySelector('.photo-favorite-badge')).toBeNull()
  })
})
