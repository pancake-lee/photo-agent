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
  useMessage,
} from 'naive-ui'
import { CloseOutline, RefreshOutline, AlertCircleOutline } from '@vicons/ionicons5'
import { useSuggestDetail } from '../composables/useSuggestDetail'
import { STEP_GROUP_LABELS } from '../types/suggest'
import type { PipelineStep } from '../types/suggest'
import SuggestStepCard from './SuggestStepCard.vue'
import SuggestStepEditor from './SuggestStepEditor.vue'
import SuggestVersionTimeline from './SuggestVersionTimeline.vue'

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
  currentVersion,
  stepGroups,
  sortedVersions,
  loadDetail,
  switchVersion,
  rerunFromStep,
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

function handleClose() {
  emit('update:visible', false)
}

async function handleVersionSwitch(versionId: string) {
  if (!props.itemId) return
  const ok = await switchVersion(props.itemId, versionId)
  if (!ok) {
    message.error('版本切换失败')
  }
}

function handleStepEdit(step: PipelineStep) {
  editingStep.value = step
  editorVisible.value = true
}

async function handleEditorConfirm(overrides: Record<string, any>) {
  if (!props.itemId || !editingStep.value) return
  const result = await rerunFromStep(props.itemId, editingStep.value.event, overrides)
  if (result) {
    message.success('重跑完成，已生成新版本')
    emit('refreshed')
  }
}

const CATEGORY_COLORS: Record<string, string> = {
  editorial_proposal: '#7c3aed',
  high_freq_ungrouped: '#f0a020',
  temporal_pattern: '#2080f0',
  scarce_quality: '#18a058',
}

const CATEGORY_LABELS: Record<string, string> = {
  editorial_proposal: '编辑提案',
  high_freq_ungrouped: '高频未成组',
  temporal_pattern: '时间线规律',
  scarce_quality: '稀缺优质',
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

    <!-- 详情内容：双栏布局 -->
    <div v-else-if="detail" class="modal-body">
      <!-- 左侧版本时间线 -->
      <div class="modal-left">
        <SuggestVersionTimeline
          :versions="sortedVersions"
          :current-version-id="detail.current_version_id"
          @switch="handleVersionSwitch"
        />
      </div>

      <!-- 右侧步骤列表 -->
      <div class="modal-right">
        <!-- trace 过期提示 -->
        <div v-if="currentVersion?.trace_expired" class="trace-expired-banner">
          <NIcon size="14"><AlertCircleOutline /></NIcon>
          追踪数据已过期，仅展示最终结果
        </div>

        <!-- 重跑中 -->
        <div v-if="rerunLoading" class="rerun-loading">
          <NSpin size="small" />
          <span>正在重跑管线...</span>
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
            <div class="photo-id-list">
              <span v-for="pid in detail.photo_ids.slice(0, 12)" :key="pid" class="photo-id-tag">
                {{ pid.slice(0, 16) }}
              </span>
              <span v-if="detail.photo_ids.length > 12" class="photo-id-more">
                还有 {{ detail.photo_ids.length - 12 }} 张...
              </span>
            </div>
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
  display: flex;
  gap: 24px;
  height: calc(90vh - 120px);
  overflow: hidden;
}
.modal-left {
  width: 200px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid var(--n-border-color);
  padding-right: 16px;
}
.modal-right {
  flex: 1;
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
  align-items: center;
  gap: 8px;
  padding: 12px;
  color: var(--n-text-color-2);
  font-size: 13px;
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
.photo-id-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.photo-id-tag {
  font-size: 11px;
  font-family: monospace;
  padding: 2px 6px;
  background: var(--n-action-color);
  border-radius: 4px;
  color: var(--n-text-color-2);
}
.photo-id-more {
  font-size: 11px;
  color: var(--n-text-color-3);
}
</style>
