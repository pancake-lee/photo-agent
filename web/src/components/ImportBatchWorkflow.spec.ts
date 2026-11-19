// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import type { App, PropType } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { NMessageProvider } from 'naive-ui'
import ImportBatchWorkflow from './ImportBatchWorkflow.vue'
import { settings } from '../stores/settings'
import type { ImportBatch, ImportDecision } from '../utils/importBatch'

const api = vi.hoisted(() => ({ ListImportBatches: vi.fn(), GetImportBatch: vi.fn(),
  DecideImportBatch: vi.fn(), UndoImportBatch: vi.fn() }))
vi.mock('../utils/importBatch', () => ({ getImportBatchApp: () => api }))
vi.mock('../utils/wails', () => ({ onWailsEvent: () => () => {},
  wailsApi: {}, wailsError: (error: unknown) => String(error) }))
vi.mock('naive-ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('naive-ui')>()
  const { defineComponent, h } = await import('vue')
  return { ...actual, NSelect: defineComponent({
    props: { value: String, disabled: Boolean,
      options: { type: Array as PropType<{ label: string; value: string }[]>, default: () => [] } },
    emits: ['update:value'],
    setup: (props, { emit }) => () => h('select', { value: props.value, disabled: props.disabled,
      onChange: (event: Event) => emit('update:value', (event.target as HTMLSelectElement).value),
    }, props.options.map((option) => h('option', { value: option.value }, option.label))),
  }) }
})

let app: App | undefined
let container: HTMLDivElement | undefined
let batch: ImportBatch
const originalServer = settings.backendUrl
const scrollIntoView = HTMLElement.prototype.scrollIntoView

beforeEach(() => {
  settings.backendUrl = 'http://review.test'
  HTMLElement.prototype.scrollIntoView = vi.fn()
  batch = { id: 'batch', activity: '活动', name: '活动', step: 'review', sources: [], complete: false, issues: [],
    bursts: { server: settings.backendUrl, fine: [['a', 'b']], coarse: [['a', 'b']] },
    entries: ['a', 'b', 'c'].map((id, i) => ({ id, pair: 'jpg_only', decision: 'kept', origin: 'manual',
      jpg: { path: `${id}.jpg`, sha256: id.repeat(64), size: 100 }, staged_server: settings.backendUrl,
      shot_at: `2026-11-19T12:00:0${i}Z` })) }
  api.ListImportBatches.mockReset().mockResolvedValue([{ id: 'batch', name: '活动', activity: '活动', step: 'review' }])
  api.GetImportBatch.mockReset().mockImplementation(async () => structuredClone(batch))
  api.DecideImportBatch.mockReset().mockImplementation(async (_id, ids: string[], value: ImportDecision) => {
    batch.undo = batch.entries.filter((entry) => ids.includes(entry.id)).map((entry) => ({ ...entry }))
    batch.entries = batch.entries.map((entry) => ids.includes(entry.id) ? { ...entry, decision: value } : entry)
    return structuredClone(batch)
  })
  api.UndoImportBatch.mockReset().mockImplementation(async () => {
    const previous = batch.undo as typeof batch.entries
    batch.entries = batch.entries.map((entry) => previous.find((old) => old.id === entry.id) ?? entry)
    batch.undo = []
    return structuredClone(batch)
  })
})
afterEach(() => {
  app?.unmount()
  container?.remove()
  settings.backendUrl = originalServer
  HTMLElement.prototype.scrollIntoView = scrollIntoView
  vi.restoreAllMocks()
})

async function mountReview() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
  await router.push('/')
  container = document.createElement('div')
  document.body.append(container)
  app = createApp({ render: () => h(NMessageProvider, null, { default: () => h(ImportBatchWorkflow) }) })
  app.use(router).mount(container)
  await vi.waitFor(() => expect(container!.querySelector('select option')?.textContent).toBe('活动'))
  const select = container.querySelector('select')!
  select.value = 'batch'
  select.dispatchEvent(new Event('change', { bubbles: true }))
  await vi.waitFor(() => expect(container!.querySelector('.photo-card[data-photo-id="a"]')).not.toBeNull())
  container.querySelector<HTMLElement>('.photo-card[data-photo-id="a"]')!.click()
  await vi.waitFor(() => expect(current()).toBe('a.jpg'))
}

function current() { return document.querySelector('.preview-frame img[alt]:not([alt=""])')?.getAttribute('alt') }
function key(value: string, shiftKey = false) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true }))
}

describe('导入大图选片交互', () => {
  it('按钮提示快捷键，单张/整组操作和撤销使用同一决定入口', async () => {
    await mountReview()
    const buttons = [...document.querySelectorAll('.preview-actions button')]
    expect(buttons.every((button) => /\([A-Z]|\(Shift\+/.test(button.textContent ?? ''))).toBe(true)
    key('l')
    await vi.waitFor(() => expect(batch.entries[0]?.decision).toBe('favorite'))
    await nextTick()
    key('L', true)
    await vi.waitFor(() => expect(batch.entries[1]?.decision).toBe('favorite'))
    await nextTick()
    key('D', true)
    await vi.waitFor(() => expect(current()).toBe('c.jpg'))
    key('z')
    await vi.waitFor(() => expect(api.UndoImportBatch).toHaveBeenCalledOnce())
    expect(batch.entries.slice(0, 2).every((entry) => entry.decision === 'favorite')).toBe(true)
  })

  it('滚轮单次连续动作只换一张，跨组需要新的动作确认，缩放不换图', async () => {
    await mountReview()
    let now = 1000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    const wheel = (deltaY: number, ctrlKey = false) => {
      const event = new WheelEvent('wheel', { deltaY, ctrlKey, bubbles: true, cancelable: true })
      Object.defineProperty(event, 'ctrlKey', { value: ctrlKey })
      document.querySelector('.preview-frame')!.dispatchEvent(event)
      return event
    }
    wheel(100)
    await nextTick()
    expect(current()).toBe('b.jpg')
    now += 40
    wheel(100)
    await nextTick()
    expect(current()).toBe('b.jpg')
    now += 250
    wheel(100)
    await nextTick()
    expect(current()).toBe('b.jpg')
    expect(document.querySelector('.preview-boundary')).not.toBeNull()
    now += 250
    wheel(100)
    await nextTick()
    expect(current()).toBe('c.jpg')
    wheel(-100, true)
    await nextTick()
    expect(current()).toBe('c.jpg')
  })

  it('填写时间时不触发选片快捷键', async () => {
    await mountReview()
    key('t')
    await vi.waitFor(() => expect(document.body.textContent).toContain('修正拍摄时间'))
    key('d')
    expect(api.DecideImportBatch).not.toHaveBeenCalled()
  })
})
