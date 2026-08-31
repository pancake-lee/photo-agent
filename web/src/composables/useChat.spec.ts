// @vitest-environment happy-dom
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { createApp, defineComponent, h, nextTick } from 'vue'
import type { App } from 'vue'
import { useChat } from './useChat'
import RuntimeProcessPanel from '../components/RuntimeProcessPanel.vue'
import type { ChatMessage, ChatSessionDetail, RuntimeStep } from '../types/chat'

// AR8 回归测试：逐帧喂入 SSE，断言每个 runtime 事件到达后无需等待 final，
// DOM 即出现/更新过程步骤（历史上普通对象修改不触发视图更新，直到 final 才一次性重绘）。

const step1: RuntimeStep = {
  step: 1,
  title: '匹配时间线',
  status: 'done',
  decision: '确认旅行',
  result: '已确认山西旅游',
  facts: ['旅行：山西'],
  details: {},
}
const step2: RuntimeStep = {
  step: 2,
  title: '查询照片',
  status: 'done',
  decision: '',
  result: '找到 20 张候选',
  facts: [],
  details: { sql: 'SELECT id FROM photos' },
}

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

// 可控 SSE 流：测试逐帧 enqueue，模拟网络分段送达
function createSseStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  return {
    response: { ok: true, body: stream, text: async () => '' } as unknown as Response,
    send(frame: string) {
      controller.enqueue(new TextEncoder().encode(frame))
    },
    close() {
      controller.close()
    },
  }
}

// 读完一次 enqueue 到 applyEvent 写入响应式状态之间的 await 链都是微任务，排空后 nextTick 触发渲染
async function flushStream() {
  for (let i = 0; i < 10; i++) {
    await Promise.resolve()
  }
  await nextTick()
}

// 与 ChatView 相同的消息渲染条件与顺序：执行过程面板在回复内容之前
function mountMessageList(): { app: App; container: HTMLElement } {
  const { messages, activeRuntimeMsg } = useChat()
  const Harness = defineComponent({
    setup: () => () =>
      h(
        'div',
        messages.value.map((msg: ChatMessage) => {
          const children = []
          if (
            msg.role === 'assistant' &&
            msg.query_type === 'runtime' &&
            (msg.runtime_steps?.length || activeRuntimeMsg.value === msg)
          ) {
            children.push(
              h(RuntimeProcessPanel, {
                steps: msg.runtime_steps || [],
                active: activeRuntimeMsg.value === msg,
              })
            )
          }
          children.push(h('div', { class: `content-${msg.role}` }, msg.content))
          return h('div', { class: 'message-row', key: msg.id || `${msg.role}-${msg.created_at}` }, children)
        })
      ),
  })
  const app = createApp(Harness)
  const container = document.createElement('div')
  document.body.appendChild(container)
  app.mount(container)
  return { app, container }
}

describe('useChat Runtime SSE 逐帧 DOM 更新', () => {
  const chat = useChat()
  let mounted: { app: App; container: HTMLElement }

  beforeEach(() => {
    chat.messages.value = []
    chat.activeRuntimeMsg.value = null
    chat.isLoading.value = false
    chat.currentSession.value = {
      session_id: 's1',
      title: '测试会话',
      last_granularity: 'photo',
      message_count: 0,
      created_at: '2026-09-01T00:00:00Z',
      updated_at: '2026-09-01T00:00:00Z',
    } as ChatSessionDetail
    mounted = mountMessageList()
  })

  afterEach(() => {
    mounted.app.unmount()
    mounted.container.remove()
    vi.unstubAllGlobals()
  })

  it('runtime.started 立即出现自动展开的过程容器，每个 runtime.step 无需等待 final 即更新 DOM', async () => {
    const stream = createSseStream()
    const fetchMock = vi.fn(async () => stream.response)
    vi.stubGlobal('fetch', fetchMock)

    const pending = chat.sendMessage('找山西旅游第一天的照片并生成发布文案')
    await flushStream()
    expect(mounted.container.querySelectorAll('.message-row').length).toBe(1) // 用户消息

    // 首个 runtime.started：0 步也出现容器，且自动展开
    stream.send(sseFrame('runtime.started', { trace_id: 'tr-1' }))
    await flushStream()
    const panel = mounted.container.querySelector('details.runtime-process')
    expect(panel).not.toBeNull()
    expect(panel?.hasAttribute('open')).toBe(true)
    expect(panel?.textContent).toContain('执行过程（0 步）')
    expect(panel?.textContent).toContain('正在规划任务')
    expect(chat.isLoading.value).toBe(true)

    // 第一个步骤事件：不等 final，DOM 立即可见
    stream.send(sseFrame('runtime.step', { steps: [step1] }))
    await flushStream()
    expect(mounted.container.textContent).toContain('第 1 步：匹配时间线')
    expect(mounted.container.textContent).toContain('已确认山西旅游')
    expect(mounted.container.textContent).toContain('执行过程（1 步）')
    expect(chat.isLoading.value).toBe(true)

    // 第二个步骤事件：新步骤与执行细节增量出现
    stream.send(sseFrame('runtime.step', { steps: [step1, step2] }))
    await flushStream()
    expect(mounted.container.textContent).toContain('第 2 步：查询照片')
    expect(mounted.container.textContent).toContain('找到 20 张候选')
    expect(mounted.container.textContent).toContain('SELECT id FROM photos')
    expect(mounted.container.textContent).toContain('执行过程（2 步）')

    // final：答案落位，面板恢复默认收起，执行状态清空
    stream.send(
      sseFrame('final', {
        message_id: 7,
        answer: '已完成文案',
        query_type: 'runtime',
        granularity: 'photo',
        photos: [],
        trace_id: 'tr-1',
        runtime_steps: [step1, step2],
      })
    )
    stream.close()
    const result = await pending
    await nextTick()
    expect(result.message_id).toBe(7)
    expect(mounted.container.textContent).toContain('已完成文案')
    const panelAfter = mounted.container.querySelector('details.runtime-process')
    expect(panelAfter).not.toBeNull()
    expect(panelAfter?.hasAttribute('open')).toBe(false)
    // 执行过程面板排在回复内容之前
    const assistantRow = mounted.container.querySelectorAll('.message-row')[1]
    expect(assistantRow.firstElementChild).toBe(panelAfter)
    expect(chat.activeRuntimeMsg.value).toBeNull()
  })

  it('非 Runtime 查询只接收 final，不出现过程面板', async () => {
    const stream = createSseStream()
    vi.stubGlobal('fetch', vi.fn(async () => stream.response))

    const pending = chat.sendMessage('今天的照片有哪些')
    await flushStream()
    stream.send(
      sseFrame('final', {
        message_id: 8,
        answer: '普通回答',
        query_type: 'rag',
        granularity: 'photo',
        trace_id: 'tr-2',
      })
    )
    stream.close()
    await pending
    await nextTick()
    expect(mounted.container.querySelector('details.runtime-process')).toBeNull()
    expect(mounted.container.textContent).toContain('普通回答')
    expect(chat.activeRuntimeMsg.value).toBeNull()
  })
})
