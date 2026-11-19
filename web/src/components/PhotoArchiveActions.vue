<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NModal, NSpace, NSpin, useMessage } from 'naive-ui'
import { getApiBase } from '../config'

const props = defineProps<{ activity: string; disabled?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const message = useMessage()

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

const cleaning = ref(false)
const pending = ref(false)
const error = ref('')
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

watch(() => props.activity, (activity) => { if (activity !== cleanActivity.value && !pending.value) cleaning.value = false })
</script>

<template>
  <NSpace>
    <NButton size="small" :disabled="disabled || !activity || activity === 'none' || pending" @click="openCleanup">清理未收藏 NEF</NButton>
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

</template>

<style scoped>
.archive-modal { width: min(760px, 92vw); }
.file-paths { max-height: 52vh; overflow: auto; padding: 0; list-style: none; overflow-wrap: anywhere; }
.file-paths li { padding: 4px 0; }
</style>
