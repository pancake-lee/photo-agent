<script setup lang="ts">
import { NAlert, NButton, NCard, NForm, NFormItem, NInput, NSpace } from 'naive-ui'
import type { DirRow } from '../types/importWorkflow'

defineProps<{
  yearMonth: string
  activityName: string
  stagingPath: string
  stagingCreated: boolean
  folderName: string
  dirRows: DirRow[]
  creating: boolean
  refreshing: boolean
  onChooseDir: () => void
  onCreate: () => void
  onRefresh: () => void
  onBack: () => void
  onNext: () => void
}>()

const emit = defineEmits<{
  'update:yearMonth': [value: string]
  'update:activityName': [value: string]
  'update:stagingPath': [value: string]
}>()
</script>

<template>
  <NCard title="新建拍摄活动" size="small" class="step-card">
    <template v-if="!stagingCreated">
      <NForm label-placement="top" :show-feedback="false">
        <NFormItem label="日期（YYYYMM）">
          <NInput :value="yearMonth" placeholder="202608" style="max-width: 240px" @update:value="emit('update:yearMonth', $event)" />
        </NFormItem>
        <NFormItem label="活动名称（可选，留空表示随手拍）">
          <NInput :value="activityName" placeholder="如：山西旅游" style="max-width: 360px" @update:value="emit('update:activityName', $event)" />
        </NFormItem>
        <NFormItem label="中转目录路径（full/like/nef 所在位置）">
          <NSpace align="center">
            <NInput :value="stagingPath" placeholder="如：D:\照片中转\" style="width: 420px" @update:value="emit('update:stagingPath', $event)" />
            <NButton @click="onChooseDir">选择文件夹</NButton>
          </NSpace>
        </NFormItem>
        <NFormItem>
          <NButton type="primary" :loading="creating" @click="onCreate">确认，创建中转目录</NButton>
        </NFormItem>
      </NForm>
    </template>

    <template v-else>
      <div class="guide-block">
        <p class="guide-intro">中转目录已就绪，请把文件放入对应文件夹（可用任意应用、任意方式）：</p>
        <ul class="guide-list">
          <li>全部照片（JPG）放入 <code>full/</code> 文件夹</li>
          <li>个人收藏的照片（JPG）放入 <code>like/</code> 文件夹</li>
          <li>本次拍摄对应的 NEF 原始文件放入 <code>nef/</code> 文件夹</li>
        </ul>
        <div class="dir-status">
          <div v-for="dir in dirRows" :key="dir.name" class="dir-row">
            <span class="dir-name">{{ dir.name }}/{{ folderName }}/</span>
            <span class="dir-state" :class="`state-${dir.state}`">{{ dir.stateText }}</span>
            <span class="dir-meta">{{ dir.count }} 个文件</span>
            <span class="dir-meta">日期：{{ dir.latest }}</span>
          </div>
        </div>
        <NAlert type="info" :bordered="false" class="guide-alert">归档目录将命名为 <b>{{ folderName }}</b>。</NAlert>
      </div>
      <NSpace justify="end" class="step-actions">
        <NButton :loading="refreshing" @click="onRefresh">刷新状态</NButton>
        <NButton @click="onBack">上一步</NButton>
        <NButton type="primary" @click="onNext">我已准备好，进入下一步</NButton>
      </NSpace>
    </template>
  </NCard>
</template>

<style scoped src="./ImportWorkflowStepShared.css"></style>
