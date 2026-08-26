<script setup lang="ts">
import { NAlert, NButton, NCard, NCollapse, NCollapseItem, NDescriptions, NDescriptionsItem, NForm, NFormItem, NInput, NModal, NProgress, NSpace } from 'naive-ui'
import type { ConflictCheck, StorageInfo, SyncProgress, SyncResult } from '../utils/wails'
import type { CleanupAdviceRow } from '../types/importWorkflow'

defineProps<{
  serverUrl: string
  storageInfo: StorageInfo | null
  fetchingInfo: boolean
  syncing: boolean
  checkingConflicts: boolean
  syncProgress: SyncProgress | null
  progressPercent: number
  syncResult: SyncResult | null
  folderName: string
  folderExists: boolean
  uploadJpgCount: number
  uploadNefCount: number
  cleanupAdviceRows: CleanupAdviceRow[]
  showConfirm: boolean
  conflictCheck: ConflictCheck | null
  hasConflicts: boolean
  formatDate: (value?: string) => string
  formatElapsed: (value: number) => string
  onFetchInfo: () => void
  onBack: () => void
  onSync: () => void
  onConfirm: (resolution: 'skip' | 'overwrite') => void
}>()

const emit = defineEmits<{ 'update:serverUrl': [value: string]; 'update:showConfirm': [value: boolean] }>()
</script>

<template>
  <NCard title="上传同步" size="small" class="step-card">
    <NForm label-placement="top" :show-feedback="false"><NFormItem label="服务器地址"><NSpace align="center"><NInput :value="serverUrl" placeholder="http://192.168.1.100:10004" style="width: 360px" @update:value="emit('update:serverUrl', $event)" /><NButton :loading="fetchingInfo" @click="onFetchInfo">连接并验证</NButton></NSpace></NFormItem></NForm>
    <template v-if="storageInfo">
      <NDescriptions bordered :column="2" size="small" class="stats storage-info">
        <NDescriptionsItem label="存储根路径">{{ storageInfo.root }}</NDescriptionsItem><NDescriptionsItem label="总文件数">{{ storageInfo.jpg_count }} 张 JPG，{{ storageInfo.nef_count }} 张 NEF</NDescriptionsItem><NDescriptionsItem label="已有月份文件夹">{{ storageInfo.months.join('、') || '—' }}</NDescriptionsItem><NDescriptionsItem label="已有活动文件夹">{{ storageInfo.activities.join('、') || '—' }}</NDescriptionsItem><NDescriptionsItem label="上次同步时间">{{ storageInfo.last_sync ? formatDate(storageInfo.last_sync) : '—' }}</NDescriptionsItem>
      </NDescriptions>
      <NAlert v-if="storageInfo.warning" type="warning" :bordered="false" class="warn-item">{{ storageInfo.warning }}</NAlert>
      <NAlert :type="folderExists ? 'warning' : 'info'" :bordered="false" class="warn-item"><template v-if="folderExists">目录 <b>{{ folderName }}</b> 已存在，本次将追加到该目录。</template><template v-else>本次将新增目录 <b>{{ folderName }}</b>（{{ uploadJpgCount }} 张 JPG，{{ uploadNefCount }} 张 NEF）。</template></NAlert>
    </template>
    <div v-if="syncing" class="sync-progress"><NProgress type="line" :percentage="progressPercent" :height="8" :border-radius="4" /><p class="sync-progress-text">已完成 {{ syncProgress?.completed ?? 0 }} / {{ syncProgress?.total ?? '—' }} 个文件</p></div>
    <div v-if="syncResult" class="sync-result">
      <NDescriptions bordered :column="4" size="small" class="stats"><NDescriptionsItem label="上传成功">{{ syncResult.succeeded }}</NDescriptionsItem><NDescriptionsItem v-if="syncResult.skipped > 0" label="跳过">{{ syncResult.skipped }}</NDescriptionsItem><NDescriptionsItem label="失败">{{ syncResult.failed }}</NDescriptionsItem><NDescriptionsItem label="耗时">{{ formatElapsed(syncResult.elapsed_ms) }}</NDescriptionsItem></NDescriptions>
      <NCollapse v-if="syncResult.failed > 0" class="lists"><NCollapseItem title="失败详情" name="failed"><div class="file-list"><div v-for="file in syncResult.files.filter((item) => item.status !== 'stored' && item.status !== 'skipped')" :key="file.name" class="file-row"><span class="file-name">{{ file.name }}</span><span class="file-date">{{ file.error }}</span></div></div></NCollapseItem></NCollapse>
      <NAlert type="info" :bordered="false" class="cleanup-title">收尾建议（本次导入完成后，以下目录仅指 <b>{{ folderName }}</b> 归档子目录，请勿删除中转根目录下其他内容）</NAlert><div class="cleanup-list"><div v-for="row in cleanupAdviceRows" :key="row.dir" class="cleanup-row"><span class="dir-name">{{ row.dir }}</span><span class="cleanup-tip" :class="row.ok ? 'tip-ok' : 'tip-warn'">{{ row.tip }}</span></div></div>
    </div>
    <NSpace justify="end" class="step-actions"><NButton @click="onBack">上一步</NButton><NButton type="primary" :loading="syncing || checkingConflicts" :disabled="!storageInfo" @click="onSync">开始同步</NButton></NSpace>
  </NCard>
  <NModal :show="showConfirm" preset="card" title="同步确认" style="width: min(90vw, 520px)" @update:show="emit('update:showConfirm', $event)">
    <template v-if="conflictCheck"><NDescriptions bordered :column="1" size="small" class="stats conflict-summary"><NDescriptionsItem label="待同步文件总数">{{ conflictCheck.total }}</NDescriptionsItem><NDescriptionsItem label="服务端已存在（重名）">{{ conflictCheck.existing.length }}</NDescriptionsItem><NDescriptionsItem label="新文件">{{ conflictCheck.new.length }}</NDescriptionsItem></NDescriptions><NAlert v-if="hasConflicts" type="warning" :bordered="false" class="warn-item">有 {{ conflictCheck.existing.length }} 个文件与服务端重名，请选择处理方式。</NAlert><NAlert v-else type="info" :bordered="false" class="warn-item">没有重名文件，将全部上传。</NAlert></template>
    <template #footer><NSpace justify="end"><NButton @click="emit('update:showConfirm', false)">取消</NButton><NButton v-if="hasConflicts" @click="onConfirm('skip')">跳过已存在文件</NButton><NButton v-if="hasConflicts" type="warning" @click="onConfirm('overwrite')">覆盖服务器现有文件</NButton><NButton v-if="!hasConflicts" type="primary" @click="onConfirm('skip')">开始上传</NButton></NSpace></template>
  </NModal>
</template>

<style scoped src="./ImportWorkflowStepShared.css"></style>
