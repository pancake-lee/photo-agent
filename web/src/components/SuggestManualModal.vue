<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  NModal,
  NButton,
  NInput,
  NSteps,
  NStep,
  NIcon,
  NSpace,
  useMessage,
} from 'naive-ui'
import {
  ArrowForwardOutline,
  ArrowBackOutline,
  CheckmarkOutline,
} from '@vicons/ionicons5'
import { useSuggestDetail } from '../composables/useSuggestDetail'
import SuggestPhotoSelector from './SuggestPhotoSelector.vue'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  done: [itemId: string]
}>()

const message = useMessage()
const { manualRun, manualLoading } = useSuggestDetail()

// 向导步骤
const currentStep = ref(1)

// Step 1: 选照片
interface PhotoItem {
  photo_id: string
  description?: string
}
const selectedPhotos = ref<PhotoItem[]>([])

// Step 2: 填直觉（可选）
const intuitionTitle = ref('')
const intuitionAngle = ref('')
const intuitionRationale = ref('')

const hasIntuition = computed(() =>
  intuitionTitle.value.trim() || intuitionAngle.value.trim()
)

function handleClose() {
  emit('update:visible', false)
  resetForm()
}

function resetForm() {
  currentStep.value = 1
  selectedPhotos.value = []
  intuitionTitle.value = ''
  intuitionAngle.value = ''
  intuitionRationale.value = ''
}

function goToStep(step: number) {
  if (step === 2 && selectedPhotos.value.length === 0) {
    message.warning('请至少选择 1 张照片')
    return
  }
  currentStep.value = step
}

async function handleSubmit() {
  if (manualLoading.value) return

  let intuition = null
  if (hasIntuition.value) {
    intuition = {
      title: intuitionTitle.value.trim() || '手动选题',
      angle: intuitionAngle.value.trim() || '',
      rationale: intuitionRationale.value.trim() || '',
      inspired_indices: [],
    }
  }

  const result = await manualRun({
    photo_ids: selectedPhotos.value.map(p => p.photo_id),
    intuition,
  })

  if (result) {
    message.success('手动选题已创建')
    emit('done', result.id)
    handleClose()
  }
}
</script>

<template>
  <NModal
    :show="visible"
    preset="card"
    title="手动生成选题建议"
    style="width: 85vw; max-width: 1100px;"
    @update:show="(val: boolean) => emit('update:visible', val)"
  >
    <!-- 步骤指示器 -->
    <NSteps :current="currentStep" style="margin-bottom: 24px;">
      <NStep title="选择照片" description="从照片库中选择或随机采样" />
      <NStep title="选题直觉" description="可选：填写你的选题想法" />
    </NSteps>

    <div class="manual-body">
      <!-- Step 1: 选照片 -->
      <div v-if="currentStep === 1" class="step-content">
        <SuggestPhotoSelector
          v-model:selected-ids="selectedPhotos"
        />
      </div>

      <!-- Step 2: 填写直觉（可选） -->
      <div v-else-if="currentStep === 2" class="step-content">
        <div class="intuition-form">
          <p class="form-hint">
            已选择 {{ selectedPhotos.length }} 张照片。
            填写选题直觉（可选，留空则由 AI 自动生成）：
          </p>
          <!-- 照片+直觉同时提供时的行为说明 -->
          <div
            v-if="selectedPhotos.length > 0 && hasIntuition"
            class="photo-intuition-hint"
          >
            💡 你选择的照片将直接作为 AI 选题的候选池，AI 将在这些照片中选择最佳组合，跳过自动搜索匹配。
          </div>
          <div class="form-field">
            <span class="form-label">标题</span>
            <NInput
              v-model:value="intuitionTitle"
              placeholder="例如：城市脉搏"
              :maxlength="30"
            />
          </div>
          <div class="form-field">
            <span class="form-label">发布角度</span>
            <NInput
              v-model:value="intuitionAngle"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="例如：从高空到地面，捕捉城市不同高度的节奏与韵律"
              :maxlength="120"
            />
          </div>
          <div class="form-field">
            <span class="form-label">选题理由</span>
            <NInput
              v-model:value="intuitionRationale"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="例如：高视角与地面视角形成对比，展现城市的立体感"
              :maxlength="120"
            />
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <NSpace justify="space-between">
        <div>
          <NButton
            v-if="currentStep === 2"
            size="small"
            @click="goToStep(1)"
          >
            <template #icon>
              <NIcon><ArrowBackOutline /></NIcon>
            </template>
            上一步
          </NButton>
        </div>
        <NSpace>
          <NButton @click="handleClose">取消</NButton>
          <NButton
            v-if="currentStep === 1"
            type="primary"
            :disabled="selectedPhotos.length === 0"
            @click="goToStep(2)"
          >
            下一步
            <template #icon>
              <NIcon><ArrowForwardOutline /></NIcon>
            </template>
          </NButton>
          <NButton
            v-else
            type="primary"
            :loading="manualLoading"
            @click="handleSubmit"
          >
            <template #icon>
              <NIcon><CheckmarkOutline /></NIcon>
            </template>
            {{ hasIntuition && selectedPhotos.length > 0 ? '用我选的照片生成选题' : hasIntuition ? '生成选题' : 'AI 自动生成' }}
          </NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.manual-body {
  min-height: 300px;
}
.step-content {
  padding: 8px 0;
}
.intuition-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.form-hint {
  margin: 0;
  font-size: 13px;
  color: var(--n-text-color-2);
  line-height: 1.6;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-3);
}
.photo-intuition-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
  padding: 8px 12px;
  background: var(--n-info-color-suppl);
  border-radius: 6px;
  line-height: 1.5;
}
</style>
