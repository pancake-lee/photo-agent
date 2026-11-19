// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import type { App, PropType } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { NMessageProvider } from 'naive-ui'
import ImportRemoteReview from './ImportRemoteReview.vue'
import type { ReviewBatch, ReviewChange } from '../utils/importReview'

vi.setConfig({ testTimeout: 15000 })
const waitFor = (assertion: () => void) => vi.waitFor(assertion, { timeout: 8000 })

const api = vi.hoisted(() => ({ listImportReviews: vi.fn(), getImportReview: vi.fn(), editImportReview: vi.fn(), reviewImageURL: vi.fn() }))
vi.mock('../utils/importReview', () => api)
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
let remote: ReviewBatch
beforeEach(() => {
  remote = { batch_id: 'batch', name: '活动', activity: '活动', state: 'review', revision: 1, updated_at: '2026-11-19T12:00:00Z',
    entries: ['a', 'b'].map((id) => ({ id, name: `${id}.jpg`, sha256: id.repeat(64), decision: 'kept', origin: 'manual' })) }
  api.listImportReviews.mockReset().mockResolvedValue([{ batch_id: remote.batch_id, name: remote.name, state: 'review', count: 2 }])
  api.getImportReview.mockReset().mockImplementation(async () => structuredClone(remote))
  api.editImportReview.mockReset().mockImplementation(async (_id, changes: ReviewChange[]) => {
    remote.entries = remote.entries.map((entry) => ({ ...entry, decision: changes.find((change) => change.id === entry.id)?.decision ?? entry.decision }))
    return structuredClone(remote)
  })
  api.reviewImageURL.mockImplementation((_id, entry) => `/fixture/${entry.id}.jpg`)
})
afterEach(() => { app?.unmount(); container?.remove(); vi.restoreAllMocks() })
async function mount() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/import', component: { render: () => null } }] })
  await router.push('/import?batch=batch')
  container = document.createElement('div')
  document.body.append(container)
  app = createApp({ render: () => h(NMessageProvider, null, { default: () => h(ImportRemoteReview) }) })
  app.use(router).mount(container)
  await waitFor(() => expect(container!.querySelector('.photo-open')).not.toBeNull())
}
function click(label: string, root: ParentNode = document) {
  const button = [...root.querySelectorAll('button')].find((node) => node.textContent?.trim() === label)
  expect(button, label).toBeDefined()
  button!.click()
}
function current() { return document.querySelector('.remote-image img')?.getAttribute('alt') }

describe('手机接续选片', () => {
  it('按链接读取批次，单张提交收藏和删除，支持撤销，刷新保留当前照片', async () => {
    await mount()
    container!.querySelector<HTMLButtonElement>('[aria-label="查看 a.jpg"]')!.click()
    await nextTick()
    expect(current()).toBe('a.jpg')
    click('收藏 (L)')
    await waitFor(() => expect(api.editImportReview).toHaveBeenCalledWith('batch', [{ id: 'a', decision: 'favorite' }]))
    await waitFor(() => expect(document.querySelector('.position')?.textContent).toContain('已收藏'))
    remote.entries[1]!.decision = 'favorite'
    click('刷新选片', document.querySelector('.remote-actions')!)
    await waitFor(() => expect(api.getImportReview).toHaveBeenCalledTimes(2))
    expect(current()).toBe('a.jpg')
    await waitFor(() => expect(container!.textContent).toContain('2 张收藏'))
    click('标记删除 (D)')
    await waitFor(() => expect(current()).toBe('b.jpg'))
    expect(api.editImportReview).toHaveBeenLastCalledWith('batch', [{ id: 'a', decision: 'discarded' }])
    click('撤销 (Z)')
    await waitFor(() => expect(remote.entries[0]!.decision).toBe('favorite'))
    expect(current()).toBe('b.jpg')
  })

  it('可查看已删除范围并恢复留存，不调用文件删除接口', async () => {
    remote.entries[0]!.decision = 'discarded'
    await mount()
    const filter = container!.querySelector<HTMLSelectElement>('select[aria-label="选片范围"]')!
    filter.value = 'discarded'
    filter.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()
    container!.querySelector<HTMLButtonElement>('[aria-label="查看 a.jpg"]')!.click()
    await nextTick()
    expect(current()).toBe('a.jpg')
    click('恢复留存 (R)')
    await waitFor(() => expect(api.editImportReview).toHaveBeenCalledWith('batch', [{ id: 'a', decision: 'kept' }]))
    expect(remote.entries[0]!.decision).toBe('kept')
  })

  it('提交失败保留原决定，读取锁定状态后禁止编辑', async () => {
    await mount()
    container!.querySelector<HTMLButtonElement>('[aria-label="查看 a.jpg"]')!.click()
    await nextTick()
    api.editImportReview.mockRejectedValueOnce(new Error('网络不可用'))
    click('收藏 (L)')
    await waitFor(() => expect(container!.textContent).toContain('网络不可用'))
    expect(remote.entries[0]!.decision).toBe('kept')
    expect(current()).toBe('a.jpg')
    remote.state = 'locked'
    click('刷新选片', document.querySelector('.remote-actions')!)
    await waitFor(() => expect(container!.textContent).toContain('PC 已结束选片'))
    const favorite = [...document.querySelectorAll<HTMLButtonElement>('.remote-actions button')].find((node) => node.textContent?.trim() === '收藏 (L)')!
    expect(favorite.disabled).toBe(true)
    expect(current()).toBe('a.jpg')
  })
})
