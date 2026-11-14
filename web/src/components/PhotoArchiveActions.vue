<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NCheckbox, NEmpty, NModal, NSpace, NSpin, NTag, useMessage } from 'naive-ui'
import { getApiBase } from '../config'

const props = defineProps<{ activity: string }>()
const emit = defineEmits<{ changed: [] }>()
const message = useMessage()

interface RecycledPhoto {
  id: string
  photo_id: string
  kind: 'photo' | 'nef'
  state: string
  activity: string
  name: string
  deleted_at?: string
  expires_at?: string
  error?: string
}

interface NEFFile {
  id: string
  path: string
  bytes: number
  sha256: string
}

interface OperationResult {
  id: string
  path?: string
  status: string
  error?: string
}

const recent = ref(false)
const cleaning = ref(false)
const pending = ref(false)
const error = ref('')
const items = ref<RecycledPhoto[]>([])
const chosen = ref<string[]>([])
const cleanActivity = ref('')
const candidates = ref<NEFFile[]>([])
const issues = ref<string[]>([])
const outcomes = ref<OperationResult[]>([])
const bytes = computed(() => candidates.value.reduce((sum, file) => sum + file.bytes, 0))

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${getApiBase()}/photo-recycle${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`)
  return payload
}

async function perform(fn: () => Promise<void>) {
  if (pending.value) return
  pending.value = true
  error.value = ''
  try { await fn() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { pending.value = false }
}

async function refreshRecent() {
  items.value = await request<RecycledPhoto[]>('')
  chosen.value = chosen.value.filter((id) => items.value.some((item) => item.id === id && canRestore(item)))
}

function openRecent() {
  items.value = []
  chosen.value = []
  outcomes.value = []
  recent.value = true
  void perform(refreshRecent)
}

function openCleanup() {
  cleanActivity.value = props.activity
  candidates.value = []
  issues.value = []
  outcomes.value = []
  cleaning.value = true
  void perform(async () => {
    const payload = await request<{ files: NEFFile[]; issues?: string[] }>(
      `/activity-nef?activity=${encodeURIComponent(cleanActivity.value)}`,
    )
    candidates.value = payload.files
    issues.value = payload.issues ?? []
  })
}

function confirmCleanup() {
  void perform(async () => {
    outcomes.value = await request<OperationResult[]>(
      `/activity-nef?activity=${encodeURIComponent(cleanActivity.value)}`, candidates.value,
    )
    candidates.value = []
    message.info(`已回收 ${outcomes.value.filter((row) => row.status === 'deleted').length} 个 NEF`)
    emit('changed')
  })
}

function canRestore(item: RecycledPhoto): boolean {
  return item.state === 'restoring' || item.state === 'deleted' &&
    !!item.expires_at && Date.parse(item.expires_at) > Date.now()
}

function remaining(item: RecycledPhoto): string {
  if (item.state === 'moving') return '回收处理中'
  if (item.state === 'restoring') return '恢复处理中'
  if (!item.expires_at) return '—'
  const days = Math.max(0, Math.ceil((Date.parse(item.expires_at) - Date.now()) / 86_400_000))
  return days ? `剩余 ${days} 天` : '已到期'
}

function restore(ids: string[]) {
  void perform(async () => {
    outcomes.value = await request<OperationResult[]>('/restore', ids)
    await refreshRecent()
    emit('changed')
  })
}

watch(() => props.activity, (activity) => { if (activity !== cleanActivity.value && !pending.value) cleaning.value = false })
</script>

<template>
  <NSpace>
    <NButton size="small" :disabled="!activity || activity === 'none' || pending" @click="openCleanup">删除非收藏图片的 NEF</NButton>
    <NButton size="small" :disabled="pending" @click="openRecent">最近删除</NButton>
  </NSpace>
  <NModal v-model:show="cleaning" preset="card" :title="`删除非收藏图片的 NEF · ${cleanActivity}`" class="archive-modal" :mask-closable="!pending">
    <NSpin :show="pending">
      <NAlert v-if="error" type="error">{{ error }}</NAlert>
      <template v-if="candidates.length">
        <p>{{ candidates.length }} 个 NEF · 到期后可释放 {{ (bytes / 1024 / 1024).toFixed(1) }} MiB</p>
        <ul class="file-paths"><li v-for="file in candidates" :key="file.id">{{ file.path }}</li></ul>
        <p>清理后可在「最近删除」中恢复，保留期为 30 天。</p>
        <NButton type="warning" :loading="pending" @click="confirmCleanup">确认移入最近删除</NButton>
      </template>
      <NEmpty v-else-if="!pending && !outcomes.length && !error" description="该活动暂无可清理的 NEF" />
      <NAlert v-for="issue in issues" :key="issue" type="warning">{{ issue }}</NAlert>
      <ul v-if="outcomes.length" class="file-paths">
        <li v-for="row in outcomes" :key="row.id">{{ row.path }} · {{ ({ deleted: '已回收', skipped: '状态已变，已跳过', failed: '失败' } as Record<string, string>)[row.status] }} {{ row.error }}</li>
      </ul>
    </NSpin>
  </NModal>

  <NModal v-model:show="recent" preset="card" title="最近删除" class="archive-modal" :mask-closable="!pending">
    <NSpin :show="pending">
      <NAlert v-if="error" type="error">{{ error }}</NAlert>
      <NEmpty v-if="!items.length && !pending && !error" description="暂无最近删除的照片" />
      <NSpace v-if="items.length">
        <NButton size="small" :disabled="pending" @click="perform(refreshRecent)">刷新</NButton>
        <NButton size="small" type="primary" :disabled="!chosen.length || pending" @click="restore(chosen)">恢复所选（{{ chosen.length }}）</NButton>
      </NSpace>
      <ul v-if="items.length" class="recent-items">
        <li v-for="item in items" :key="item.id">
          <NCheckbox :checked="chosen.includes(item.id)" :disabled="!canRestore(item) || pending" :aria-label="`选择 ${item.name}`"
            @update:checked="(value) => { chosen = value ? [...chosen, item.id] : chosen.filter((id) => id !== item.id) }" />
          <img :src="`${getApiBase()}/photo-recycle/${item.id}/image`" :alt="item.name" loading="lazy" />
          <div class="recent-info">
            <div>{{ item.name }}</div>
            <NSpace size="small" align="center"><NTag size="small">{{ item.kind === 'nef' ? '仅 NEF' : '整张照片' }}</NTag>
              <span>{{ item.activity || '未分类' }}</span><span>{{ remaining(item) }}</span>
            </NSpace>
            <div v-if="item.error">{{ item.error }}</div>
          </div>
          <NButton size="small" :disabled="!canRestore(item) || pending" @click="restore([item.id])">恢复</NButton>
        </li>
      </ul>
      <NAlert v-if="outcomes.length" :type="outcomes.some((row) => row.error) ? 'warning' : 'success'">
        <div>已恢复 {{ outcomes.filter((row) => row.status === 'restored').length }} 条。</div>
        <div v-for="row in outcomes.filter((item) => item.error)" :key="row.id">{{ row.error }}</div>
      </NAlert>
    </NSpin>
  </NModal>
</template>

<style scoped>
.archive-modal { width: min(760px, 92vw); }
.file-paths, .recent-items { max-height: 52vh; overflow: auto; padding: 0; list-style: none; overflow-wrap: anywhere; }
.file-paths li { padding: 4px 0; }
.recent-items li { display: flex; align-items: center; gap: 8px; padding: 8px 0; }
.recent-items img { width: 72px; height: 56px; object-fit: cover; border-radius: 4px; }
.recent-info { flex: 1; min-width: 0; }
</style>
