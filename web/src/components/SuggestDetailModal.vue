<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  NModal,
  NButton,
  NIcon,
  NTag,
  NSpin,
  NEmpty,
  NDivider,
  NProgress,
  NTooltip,
  useMessage,
} from 'naive-ui'
import { AlertCircleOutline } from '@vicons/ionicons5'
import { useSuggestDetail } from '../composables/useSuggestDetail'
import { STEP_GROUP_LABELS } from '../types/suggest'
import type { PipelineStep } from '../types/suggest'
import { getApiBase } from '../config'
import SuggestStepCard from './SuggestStepCard.vue'
import SuggestStepEditor from './SuggestStepEditor.vue'

const props = defineProps<{
  itemId: string | null
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  refreshed: []
}>()

const message = useMessage()
const {
  detailLoading,
  detail,
  detailError,
  rerunLoading,
  rerunProgress,
  currentVersion,
  stepGroups,
  loadDetail,
  rerunFromStepStream,
} = useSuggestDetail()

// 编辑状态
const editingStep = ref<PipelineStep | null>(null)
const editorVisible = ref(false)

// 当 modal 打开时加载详情
watch(() => [props.itemId, props.visible], ([id, vis]) => {
  if (vis && id) {
    loadDetail(id as string)
  }
})

function handleStepEdit(step: PipelineStep) {
  editingStep.value = step
  editorVisible.value = true
}

async function handleEditorConfirm(overrides: Record<string, any>) {
  if (!props.itemId || !editingStep.value) return
  const result = await rerunFromStepStream(props.itemId, editingStep.value.event, overrides)
  if (result) {
    message.success('重跑完成，已生成新版本')
    emit('refreshed')
  } else if (detailError.value) {
    message.error(detailError.value)
  }
}

const CATEGORY_COLORS: Record<string, string> = {
  editorial_proposal: '#7c3aed',
}

const CATEGORY_LABELS: Record<string, string> = {
  editorial_proposal: '编辑提案',
}
</script>

<template>
  <NModal
    :show="visible"
    preset="card"
    style="width: 95vw; max-width: 1400px; height: 90vh;"
    :title="detail?.title || '选题详情'"
    @update:show="(val: boolean) => emit('update:visible', val)"
  >
    <template #header>
      <div class="modal-header">
        <span class="modal-title">{{ detail?.title || '选题详情' }}</span>
        <NTag
          v-if="detail"
          size="tiny"
          :bordered="false"
          :color="{ color: CATEGORY_COLORS[detail.category] || '#999', textColor: '#fff' }"
        >
          {{ CATEGORY_LABELS[detail.category] || detail.category }}
        </NTag>
      </div>
    </template>

    <!-- 加载中 -->
    <div v-if="detailLoading" class="modal-loading">
      <NSpin size="large" />
      <span>加载管线详情...</span>
    </div>

    <!-- 错误 -->
    <div v-else-if="detailError" class="modal-error">
      <NEmpty :description="detailError">
        <template #extra>
          <NButton size="small" @click="props.itemId && loadDetail(props.itemId)">
            重试
          </NButton>
        </template>
      </NEmpty>
    </div>

    <!-- 详情内容：单栏布局 -->
    <div v-else-if="detail" class="modal-body">
      <!-- trace 过期提示 -->
      <div v-if="currentVersion?.trace_expired" class="trace-expired-banner">
        <NIcon size="14"><AlertCircleOutline /></NIcon>
        追踪数据已过期，仅展示最终结果
      </div>

      <!-- 重跑中（含阶段进度） -->
      <div v-if="rerunLoading" class="rerun-loading">
        <NSpin size="small" />
        <div class="rerun-progress-info">
          <span class="rerun-label">正在重跑管线...</span>
          <span v-if="rerunProgress" class="rerun-stage">
            {{ rerunProgress.label }}
            <template v-if="rerunProgress.status === 'done'"> ✅</template>
            <template v-else> 🔄</template>
          </span>
        </div>
        <NProgress
          v-if="rerunProgress"
          :percentage="Math.round((rerunProgress.stage / 3) * 100)"
          :height="4"
          :border-radius="2"
          :show-indicator="false"
          style="width: 100%; margin-top: 6px;"
        />
      </div>

      <!-- 按 group 分组展示步骤 -->
      <div v-if="stepGroups.length > 0">
        <div v-for="group in stepGroups" :key="group.group" class="step-group">
          <NDivider title-placement="left">
            {{ STEP_GROUP_LABELS[group.group] || group.group }}
          </NDivider>
          <SuggestStepCard
            v-for="step in group.steps"
            :key="step.event + step.timestamp"
            :step="step"
            :editable="true"
            @edit="handleStepEdit"
          />
        </div>
      </div>

      <!-- 空步骤（trace 过期或无痕数据） -->
      <div v-else class="no-steps">
        <NEmpty description="暂无管线步骤数据" size="small" />
      </div>

      <!-- 最终结果摘要 -->
      <NDivider title-placement="left">最终结果</NDivider>
      <div class="final-result">
          <div class="result-field">
            <span class="field-label">发布角度</span>
            <p>{{ detail.angle }}</p>
          </div>
          <div class="result-field">
            <span class="field-label">选题理由</span>
            <p>{{ detail.rationale }}</p>
          </div>
          <div class="result-field">
            <span class="field-label">推荐照片（{{ detail.photo_ids.length }} 张）</span>
            <div class="photo-thumb-grid">
              <NTooltip
                v-for="pid in detail.photo_ids"
                :key="pid"
                trigger="hover"
              >
                <template #trigger>
                  <div class="thumb-item">
                    <img
                      :src="`${getApiBase()}/photos/${pid}/image`"
                      :alt="pid.slice(0, 8)"
                      loading="lazy"
                      @error="(e: Event) => { (e.target as HTMLImageElement).style.display = 'none' }"
                    />
                  </div>
                </template>
                {{ pid }}
              </NTooltip>
            </div>
          </div>
        </div>
    </div>

    <!-- 编辑器弹窗 -->
    <SuggestStepEditor
      :step="editingStep"
      :visible="editorVisible"
      @update:visible="editorVisible = $event"
      @confirm="handleEditorConfirm"
    />
  </NModal>
</template>

<style scoped>
.modal-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.modal-title {
  font-size: 16px;
  font-weight: 600;
}
.modal-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 300px;
  color: var(--n-text-color-2);
}
.modal-error {
  display: flex;
  justify-content: center;
  padding: 60px 0;
}
.modal-body {
  height: calc(90vh - 120px);
  overflow-y: auto;
  padding-right: 8px;
}
.trace-expired-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: var(--n-warning-color-suppl);
  border-radius: 6px;
  font-size: 12px;
  color: var(--n-warning-color);
  margin-bottom: 12px;
}
.rerun-loading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 12px;
  color: var(--n-text-color-2);
  font-size: 13px;
}
.rerun-progress-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.rerun-label {
  font-size: 13px;
}
.rerun-stage {
  font-size: 12px;
  color: var(--n-text-color-3);
}
.step-group {
  margin-bottom: 8px;
}
.no-steps {
  padding: 40px 0;
}
.final-result {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.result-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.result-field p {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
}
.field-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
}
.photo-thumb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  gap: 4px;
  margin-top: 6px;
}
.thumb-item {
  width: 80px;
  height: 80px;
  overflow: hidden;
  border-radius: 4px;
  border: 1px solid var(--n-border-color);
  background: var(--n-action-color);
}
.thumb-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.photo-id-more {
  font-size: 11px;
  color: var(--n-text-color-3);
  margin-top: 4px;
  display: block;
}
</style>
