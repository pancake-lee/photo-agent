<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  NModal,
  NButton,
  NSpace,
  NInput,
  NForm,
  NFormItem,
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
const editingMode = ref<'photos' | 'text' | 'json' | 'none' | 'intuition_form' | 'proposal_form'>('none')

// 结构化表单字段
const formTitle = ref('')
const formAngle = ref('')
const formRationale = ref('')
const formInspiredPhotos = ref<PhotoItem[]>([])
const formPhotoSequence = ref<Array<{ photo_id: string; role_in_narrative: string }>>([])

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

  // 直觉步骤 → 结构化表单
  if (e === 'suggest.stage1.intuitions' || e === 'suggest.stage1.llm.end') {
    const intuitions = step.data.intuitions
    if (Array.isArray(intuitions) && intuitions.length > 0) {
      const it = intuitions[0]
      formTitle.value = it.title || ''
      formAngle.value = it.angle || ''
      formRationale.value = it.rationale || ''
      formInspiredPhotos.value = (it.inspired_photo_ids || []).map((pid: string) => ({ photo_id: pid }))
    } else if (step.data.title) {
      formTitle.value = step.data.title || ''
      formAngle.value = step.data.angle || ''
      formRationale.value = step.data.rationale || ''
      formInspiredPhotos.value = (step.data.inspired_photo_ids || []).map((pid: string) => ({ photo_id: pid }))
    }
    editingMode.value = 'intuition_form'
    return
  }

  // 提案步骤 → 结构化表单
  if (e === 'suggest.stage3.proposal' || e === 'suggest.stage3.llm.end') {
    formTitle.value = step.data.title || ''
    formAngle.value = step.data.angle || ''
    formRationale.value = step.data.rationale || ''
    formPhotoSequence.value = (step.data.photo_sequence || []).map((s: any) => ({
      photo_id: s.photo_id || '',
      role_in_narrative: s.role_in_narrative || '',
    }))
    editingMode.value = 'proposal_form'
    return
  }

  // 校验步骤 → JSON（保留）
  if (e === 'suggest.stage3.validation') {
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
  } else if (editingMode.value === 'intuition_form') {
    if (!formTitle.value.trim()) {
      message.error('标题不能为空')
      return
    }
    overrides.intuitions = [{
      title: formTitle.value.trim(),
      angle: formAngle.value.trim(),
      rationale: formRationale.value.trim(),
      inspired_indices: [],
      inspired_photo_ids: formInspiredPhotos.value.map(p => p.photo_id),
    }]
  } else if (editingMode.value === 'proposal_form') {
    if (!formTitle.value.trim()) {
      message.error('标题不能为空')
      return
    }
    overrides.proposal = {
      title: formTitle.value.trim(),
      angle: formAngle.value.trim(),
      rationale: formRationale.value.trim(),
      photo_ids: formPhotoSequence.value.map(s => s.photo_id),
      photo_sequence: formPhotoSequence.value,
    }
  } else if (editingMode.value === 'json') {
    try {
      const parsed = JSON.parse(editedJson.value)
      if (props.step.event === 'suggest.stage3.validation') {
        Object.assign(overrides, parsed)
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

      <!-- 直觉结构化表单 -->
      <div v-else-if="editingMode === 'intuition_form'" class="editor-form">
        <NForm label-placement="top" size="small">
          <NFormItem label="标题" required>
            <NInput v-model:value="formTitle" placeholder="选题直觉标题" />
          </NFormItem>
          <NFormItem label="角度">
            <NInput
              v-model:value="formAngle"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="这个选题的独特视角和发布价值"
            />
          </NFormItem>
          <NFormItem label="理由">
            <NInput
              v-model:value="formRationale"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="这个视角为什么有意义"
            />
          </NFormItem>
          <NFormItem label="启发照片">
            <SuggestPhotoSelector
              v-model:selected-ids="formInspiredPhotos"
              :compact="true"
            />
          </NFormItem>
        </NForm>
        <span class="editor-hint">
          也可以切换到 JSON 编辑
          <NButton size="tiny" text @click="editingMode = 'json'; editedJson = JSON.stringify({ intuitions: [{ title: formTitle, angle: formAngle, rationale: formRationale, inspired_photo_ids: formInspiredPhotos.map(p => p.photo_id) }] }, null, 2)">
            切换
          </NButton>
        </span>
      </div>

      <!-- 提案结构化表单 -->
      <div v-else-if="editingMode === 'proposal_form'" class="editor-form">
        <NForm label-placement="top" size="small">
          <NFormItem label="标题" required>
            <NInput v-model:value="formTitle" placeholder="选题提案标题" />
          </NFormItem>
          <NFormItem label="角度">
            <NInput
              v-model:value="formAngle"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="叙事角度和发布价值"
            />
          </NFormItem>
          <NFormItem label="理由">
            <NInput
              v-model:value="formRationale"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="选题理由"
            />
          </NFormItem>
          <NFormItem label="照片序列（{{ formPhotoSequence.length }} 张）">
            <div v-if="formPhotoSequence.length > 0" class="seq-list">
              <div
                v-for="(item, idx) in formPhotoSequence"
                :key="idx"
                class="seq-item"
              >
                <span class="seq-idx">{{ idx + 1 }}</span>
                <span class="seq-id">{{ item.photo_id.slice(0, 16) }}...</span>
                <NInput
                  v-model:value="item.role_in_narrative"
                  size="tiny"
                  placeholder="叙事角色"
                  style="width: 160px;"
                />
              </div>
            </div>
            <span v-else class="editor-hint">无照片序列</span>
          </NFormItem>
        </NForm>
        <span class="editor-hint">
          也可切换到 JSON 编辑
          <NButton size="tiny" text @click="editingMode = 'json'; editedJson = JSON.stringify({ title: formTitle, angle: formAngle, rationale: formRationale, photo_sequence: formPhotoSequence }, null, 2)">
            切换
          </NButton>
        </span>
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
.editor-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 60vh;
  overflow-y: auto;
}
.seq-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.seq-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: var(--n-action-color);
  border-radius: 4px;
}
.seq-idx {
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  min-width: 20px;
}
.seq-id {
  font-size: 11px;
  font-family: monospace;
  color: var(--n-text-color-2);
  flex: 1;
}
</style>
