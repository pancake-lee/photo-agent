<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NFormItem, NInput, NModal, NRadioButton, NRadioGroup,
  NSelect, NSpace, useMessage } from 'naive-ui'
import { useTimelines } from '../composables/useTimelines'
import { getApiBase } from '../config'
import type { BurstViewLevel } from '../types/photo'

const props = defineProps<{ photoIds: string[]; burstProfile: BurstViewLevel }>()
const show = defineModel<boolean>('show', { required: true })
const emit = defineEmits<{ changed: [] }>()
const { events, eventsError, fetchEvents, saveEvent } = useTimelines()
const message = useMessage()
const mode = ref<'existing' | 'new'>('existing')
const activityId = ref<string | null>(null)
const newName = ref('')
const pending = ref(false)
const error = ref('')
const preview = ref<MovePreview | null>(null)
const selection = ref<string[]>([])
const profile = ref<BurstViewLevel>('all')
const options = computed(() => events.value.map((event) => ({ label: event.event, value: event.id })))
const validTarget = computed(() => mode.value === 'existing' ? !!activityId.value : !!newName.value.trim())

interface MovePreview {
  activity: string
  total: number
  moving: number
  unchanged: number
  renamed: number
  photo_ids: string[]
  items: { photo_id: string; filename: string; to_filename: string; from_activity: string }[]
  warning?: string
}

watch(show, async (value) => {
  if (!value) return
  selection.value = [...props.photoIds]
  profile.value = props.burstProfile
  mode.value = 'existing'
  activityId.value = null
  newName.value = ''
  preview.value = null
  error.value = ''
  await fetchEvents()
}, { immediate: true })
watch([mode, activityId, newName], () => {
  if (pending.value) return
  preview.value = null
  error.value = ''
})

async function request(previewOnly: boolean, targetId?: string, confirmedIds?: string[]): Promise<MovePreview> {
  const response = await fetch(`${getApiBase()}/photos/activity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      photo_ids: selection.value,
      burst_profile: profile.value,
      activity_id: targetId ?? (mode.value === 'existing' ? activityId.value : undefined),
      new_activity: targetId ? undefined : (mode.value === 'new' ? newName.value.trim() : undefined),
      confirmed_photo_ids: confirmedIds,
      preview: previewOnly,
    }),
  })
  const body = await response.json()
  if (!response.ok) throw new Error(body.error || '修改活动失败')
  return body
}

async function previewMove() {
  if (pending.value || !validTarget.value) return
  pending.value = true
  error.value = ''
  preview.value = null
  try { preview.value = await request(true) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { pending.value = false }
}

async function confirmMove() {
  const confirmed = preview.value
  if (pending.value || !confirmed) return
  pending.value = true
  error.value = ''
  try {
    let targetId = activityId.value ?? undefined
    if (mode.value === 'new') {
      targetId = await saveEvent({ event: newName.value.trim(), date: '' })
      // Keep the created target selected if moving fails, so retry won't recreate it.
      await fetchEvents()
      activityId.value = targetId
      mode.value = 'existing'
    }
    const result = await request(false, targetId, confirmed.photo_ids)
    message.success(`已将 ${result.moving} 张照片移入“${result.activity}”`)
    if (result.warning) message.warning(result.warning)
    show.value = false
    emit('changed')
  } catch (reason) {
    preview.value = null
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally { pending.value = false }
}
</script>

<template>
  <NModal :show="show" preset="card" title="修改活动" class="move-activity-modal"
    style="width: 560px; max-width: calc(100vw - 32px)"
    :mask-closable="!pending" :close-on-esc="!pending" :closable="!pending" @update:show="show = $event">
    <div class="move-form">
      <p class="move-hint">已选 {{ selection.length }} 个条目。折叠的连拍组将整组移动，请先预览实际照片数。</p>
      <NRadioGroup v-model:value="mode" :disabled="pending">
        <NRadioButton value="existing">已有活动</NRadioButton>
        <NRadioButton value="new">新建活动</NRadioButton>
      </NRadioGroup>
      <NFormItem v-if="mode === 'existing'" label="目标活动">
        <NSelect v-model:value="activityId" :options="options" filterable :disabled="pending" placeholder="选择已有活动" />
      </NFormItem>
      <NFormItem v-else label="活动目录名">
        <NInput v-model:value="newName" :disabled="pending" maxlength="180" placeholder="如：202608-山西旅游" />
      </NFormItem>
      <NAlert v-if="error || eventsError" type="error">{{ error || eventsError }}</NAlert>
      <NAlert v-if="preview" type="info" title="移动预览">
        <div>共 {{ preview.total }} 张照片，将移动 {{ preview.moving }} 张至“{{ preview.activity }}”。</div>
        <div v-if="preview.unchanged">{{ preview.unchanged }} 张已在目标活动，保持原位。</div>
        <div v-if="preview.renamed">{{ preview.renamed }} 张存在同名冲突，将自动加序号，原有文件保留。</div>
        <ul v-if="preview.renamed" class="renamed-list">
          <li v-for="item in preview.items.filter((item) => item.filename !== item.to_filename).slice(0, 10)" :key="item.photo_id">
            {{ item.filename }} → {{ item.to_filename }}
          </li>
        </ul>
      </NAlert>
      <p class="move-hint">原片、预览与配对 NEF 一起移动，收藏和已有 AI 结果保留。</p>
    </div>
    <template #footer>
      <NSpace justify="end" :wrap="true">
        <NButton :disabled="pending" @click="show = false">取消</NButton>
        <NButton :disabled="pending || !validTarget" :loading="pending && !preview" @click="previewMove">预览移动</NButton>
        <NButton type="primary" :disabled="pending || !preview || preview.moving === 0" :loading="pending && !!preview" @click="confirmMove">确认移动</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.move-form { display: flex; flex-direction: column; gap: 16px; }
.move-hint { margin: 0; color: var(--n-text-color-3); font-size: 13px; }
.move-form :deep(.n-form-item) { margin: 0; }
.renamed-list { margin: 8px 0 0; padding-left: 24px; overflow-wrap: anywhere; }
</style>
