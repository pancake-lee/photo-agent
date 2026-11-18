// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
import type { App, PropType } from 'vue'
import { NMessageProvider } from 'naive-ui'
import PhotoActivityMoveModal from './PhotoActivityMoveModal.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), save: vi.fn() }))
vi.mock('../backend-sdk-client', () => ({ timelineApi: {
  timelineServiceListEvents: api.list,
  timelineServiceSaveEvent: api.save,
} }))
// Test our dialog flow without depending on the select menu's virtual viewport.
vi.mock('naive-ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('naive-ui')>()
  const { defineComponent, h } = await import('vue')
  return { ...actual, NSelect: defineComponent({
    props: { value: String, disabled: Boolean,
      options: { type: Array as PropType<{ label: string; value: string }[]>, default: () => [] } },
    emits: ['update:value'],
    setup: (props, { emit }) => () => h('select', {
      value: props.value, disabled: props.disabled,
      onChange: (event: Event) => emit('update:value', (event.target as HTMLSelectElement).value),
    }, props.options.map((option) => h('option', { value: option.value }, option.label))),
  }) }
})

let app: App | undefined
let container: HTMLDivElement | undefined
const changed = vi.fn()
const plan = { activity: '目标活动', total: 3, moving: 3, unchanged: 0, renamed: 1,
  photo_ids: ['cover', 'member-1', 'member-2'],
  items: [{ photo_id: 'cover', filename: 'same.JPG', to_filename: 'same (2).JPG', from_activity: '来源' }] }

beforeEach(() => {
  api.list.mockReset().mockResolvedValue({ events: [
    { id: 'target', event: '目标活动', photoCount: 0 },
    { id: 'new-target', event: '新活动', photoCount: 0 },
  ] })
  api.save.mockReset().mockResolvedValue({ id: 'new-target' })
  changed.mockReset()
})
afterEach(() => {
  app?.unmount()
  container?.remove()
  vi.unstubAllGlobals()
})

async function mountModal() {
  const show = ref(true)
  container = document.createElement('div')
  document.body.append(container)
  app = createApp({ render: () => h(NMessageProvider, null, {
    default: () => h(PhotoActivityMoveModal, { show: show.value,
      'onUpdate:show': (value: boolean) => { show.value = value },
      photoIds: ['cover'], burstProfile: 'coarse', onChanged: changed }),
  }) })
  app.mount(container)
  await vi.waitFor(() => expect(document.querySelector('.move-activity-modal')).not.toBeNull())
  await nextTick()
  return show
}

function button(label: string): HTMLButtonElement {
  return [...document.querySelectorAll<HTMLButtonElement>('.move-activity-modal button')]
    .find((element) => element.textContent?.trim() === label)!
}

async function selectTarget() {
  await vi.waitFor(() => expect(document.querySelectorAll('.move-activity-modal select option')).toHaveLength(2))
  const select = document.querySelector<HTMLSelectElement>('.move-activity-modal select')!
  select.value = 'target'
  select.dispatchEvent(new Event('change', { bubbles: true }))
  await nextTick()
}

describe('批量修改活动弹窗', () => {
  it('已有活动先预览整组实际张数，再提交确认成员并刷新', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => plan })
    vi.stubGlobal('fetch', fetchMock)
    const show = await mountModal()
    expect(button('确认移动').disabled).toBe(true)
    await selectTarget()
    button('预览移动').click()
    await vi.waitFor(() => expect(document.body.textContent).toContain('共 3 张照片'))
    expect(document.body.textContent).toContain('same (2).JPG')
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toMatchObject({
      photo_ids: ['cover'], activity_id: 'target', burst_profile: 'coarse', preview: true,
    })
    button('确认移动').click()
    await vi.waitFor(() => expect(changed).toHaveBeenCalledOnce())
    expect(show.value).toBe(false)
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).toMatchObject({
      activity_id: 'target', confirmed_photo_ids: plan.photo_ids, preview: false,
    })
    expect(api.save).not.toHaveBeenCalled()
  })

  it('新建活动先预览，创建后移动失败保留目标以便重试', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...plan, activity: '新活动' }) })
      .mockResolvedValueOnce({ ok: false, json: async () => ({ error: '文件暂不可用' }) })
      .mockResolvedValue({ ok: true, json: async () => ({ ...plan, activity: '新活动' }) })
    vi.stubGlobal('fetch', fetchMock)
    await mountModal()
    const radio = [...document.querySelectorAll<HTMLElement>('.n-radio-button')]
      .find((element) => element.textContent?.includes('新建活动'))!
    radio.querySelector<HTMLInputElement>('input')!.click()
    await nextTick()
    const input = document.querySelector<HTMLInputElement>('.move-activity-modal .n-input input')!
    input.value = '新活动'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    button('预览移动').click()
    await vi.waitFor(() => expect(button('确认移动').disabled).toBe(false))
    expect(api.save).not.toHaveBeenCalled()
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body).new_activity).toBe('新活动')
    button('确认移动').click()
    await vi.waitFor(() => expect(document.body.textContent).toContain('文件暂不可用'))
    expect(changed).not.toHaveBeenCalled()
    expect(api.save).toHaveBeenCalledOnce()
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).toMatchObject({ activity_id: 'new-target', preview: false })
    button('预览移动').click()
    await vi.waitFor(() => expect(button('确认移动').disabled).toBe(false))
    button('确认移动').click()
    await vi.waitFor(() => expect(changed).toHaveBeenCalledOnce())
    expect(api.save).toHaveBeenCalledOnce()
  })
})
