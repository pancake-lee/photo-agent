<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  NModal,
  NButton,
  NSpace,
  NInput,
  NForm,
  NFormItem,
  NSelect,
  useMessage,
} from 'naive-ui'
import type { PipelineStep } from '../types/suggest'
import SuggestPhotoSelector from './SuggestPhotoSelector.vue'

const props = defineProps<{
  step: PipelineStep | null
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  confirm: [overrides: Record<string, any>]
}>()

const message = useMessage()

// 根据步骤类型渲染不同的编辑器
interface PhotoItem {
  photo_id: string
  description?: string
}

const editedPhotos = ref<PhotoItem[]>([])
const editedText = ref('')
const editedJson = ref('')
const editingMode = ref<'photos' | 'text' | 'json' | 'none'>('none')

watch(() => props.step, (step) => {
  if (!step) return
  const e = step.event

  // 采样步骤 → 照片选择器
  if (e === 'suggest.stage1.sample') {
    const ids: string[] = step.data.photo_ids || []
    const descs: string[] = step.data.photo_descs || []
    editedPhotos.value = ids.map((id, i) => ({
      photo_id: id,
      description: descs[i] || '',
    }))
    editingMode.value = 'photos'
    return
  }

  // RAG 结果 / 多样性过滤 → 照片选择器
  if (e === 'suggest.stage2.rag.end' || e === 'suggest.stage2.diversity') {
    const ids: string[] = step.data.photo_ids || []
    editedPhotos.value = ids.map(id => ({ photo_id: id }))
    editingMode.value = 'photos'
    return
  }

  // LLM 输入步骤 → 文本编辑器（prompt）
  if (e === 'suggest.stage1.llm.start' || e === 'suggest.stage3.llm.start' || e === 'suggest.stage2.rag.start') {
    editedText.value = step.payload_content || step.data.query || ''
    editingMode.value = 'text'
    return
  }

  // LLM 输出 / 提案 / 直觉 → JSON 编辑器
  if (e === 'suggest.stage1.llm.end' || e === 'suggest.stage1.intuitions' ||
      e === 'suggest.stage3.llm.end' || e === 'suggest.stage3.proposal' ||
      e === 'suggest.stage3.validation') {
    editedJson.value = JSON.stringify(step.data, null, 2)
    editingMode.value = 'json'
    return
  }

  editingMode.value = 'json'
  editedJson.value = JSON.stringify(step.data, null, 2)
}, { immediate: true })

function handleConfirm() {
  if (!props.step) return

  const overrides: Record<string, any> = {}

  if (editingMode.value === 'photos') {
    overrides.photo_ids = editedPhotos.value.map(p => p.photo_id)
  } else if (editingMode.value === 'text') {
    const e = props.step.event
    if (e === 'suggest.stage2.rag.start') {
      overrides.query = editedText.value
    } else {
      overrides.prompt = editedText.value
    }
  } else if (editingMode.value === 'json') {
    try {
      const parsed = JSON.parse(editedJson.value)
      // 根据步骤类型确定 key
      if (props.step.event === 'suggest.stage1.llm.end' || props.step.event === 'suggest.stage1.intuitions') {
        overrides.intuitions = Array.isArray(parsed) ? parsed : (parsed.intuitions || [parsed])
      } else if (props.step.event === 'suggest.stage3.llm.end' || props.step.event === 'suggest.stage3.proposal') {
        overrides.proposal = parsed
      } else {
        Object.assign(overrides, parsed)
      }
    } catch {
      message.error('JSON 格式无效')
      return
    }
  }

  emit('confirm', overrides)
  emit('update:visible', false)
}

function handleClose() {
  emit('update:visible', false)
}
</script>

<template>
  <NModal
    :show="visible"
    preset="card"
    title="编辑步骤数据"
    style="width: 85vw; max-width: 1000px;"
    @update:show="(val: boolean) => emit('update:visible', val)"
  >
    <div class="editor-body">
      <!-- 照片选择器模式 -->
      <div v-if="editingMode === 'photos'" class="editor-photos">
        <span class="editor-hint">已选 {{ editedPhotos.length }} 张照片</span>
        <SuggestPhotoSelector
          v-model:selected-ids="editedPhotos"
          :compact="true"
        />
      </div>

      <!-- 文本编辑器模式 -->
      <div v-else-if="editingMode === 'text'" class="editor-text">
        <span class="editor-hint">编辑文本内容</span>
        <NInput
          v-model:value="editedText"
          type="textarea"
          :autosize="{ minRows: 8, maxRows: 24 }"
          placeholder="输入文本..."
        />
      </div>

      <!-- JSON 编辑器模式 -->
      <div v-else-if="editingMode === 'json'" class="editor-json">
        <span class="editor-hint">编辑 JSON 数据</span>
        <NInput
          v-model:value="editedJson"
          type="textarea"
          :autosize="{ minRows: 8, maxRows: 24 }"
          placeholder="输入 JSON..."
        />
      </div>
    </div>

    <template #footer>
      <NSpace justify="end">
        <NButton @click="handleClose">取消</NButton>
        <NButton type="primary" @click="handleConfirm">确认并从此步重跑</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.editor-body {
  min-height: 200px;
}
.editor-hint {
  display: block;
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-bottom: 12px;
}
.editor-photos,
.editor-text,
.editor-json {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
