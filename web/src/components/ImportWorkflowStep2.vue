<script setup lang="ts">
import { NAlert, NButton, NCard, NCollapse, NCollapseItem, NDescriptions, NDescriptionsItem, NEmpty, NSpin, NSpace } from 'naive-ui'
import type { ImportAnalysis, JpgRef, MigrateResult } from '../utils/wails'

defineProps<{
  analysis: ImportAnalysis | null
  analyzing: boolean
  migrating: boolean
  migrateResult: MigrateResult | null
  canProceed: boolean
  formatDate: (value?: string) => string
  hasWarnings: (analysis: ImportAnalysis) => boolean
  onPreview: (item: JpgRef) => void
  onBack: () => void
  onAnalyze: () => void
  onMigrate: () => void
  onNext: () => void
}>()
</script>

<template>
  <NCard title="分析报告" size="small" class="step-card">
    <NSpin :show="analyzing">
      <template v-if="analysis">
        <NDescriptions bordered :column="3" size="small" class="stats">
          <NDescriptionsItem label="full 中 JPG 总数">{{ analysis.full_jpg_count }}</NDescriptionsItem>
          <NDescriptionsItem label="收藏 JPG 总数（like）">{{ analysis.like_jpg_count }}</NDescriptionsItem>
          <NDescriptionsItem label="nef 中 NEF 总数">{{ analysis.nef_count }}</NDescriptionsItem>
          <NDescriptionsItem label="收藏照片的 NEF（将迁移）">{{ analysis.favorite_count }}</NDescriptionsItem>
          <NDescriptionsItem label="已迁移 NEF（已在 like）">{{ analysis.migrated_count }}</NDescriptionsItem>
          <NDescriptionsItem label="跳过留存照片的 NEF">{{ analysis.retained_count }}</NDescriptionsItem>
          <NDescriptionsItem label="跳过废弃照片的 NEF">{{ analysis.discarded_count }}</NDescriptionsItem>
          <NDescriptionsItem label="时间范围">{{ formatDate(analysis.time_range.min) }} 至 {{ formatDate(analysis.time_range.max) }}</NDescriptionsItem>
        </NDescriptions>
        <div v-if="hasWarnings(analysis)" class="warnings">
          <NAlert v-if="analysis.outliers.length" type="warning" :bordered="false" class="warn-item">
            发现 {{ analysis.outliers.length }} 个文件日期偏离主要范围，请确认是否混入其他活动：{{ analysis.outliers.map((item) => `${item.name}（${formatDate(item.shot_at)}）`).join('、') }}
          </NAlert>
          <NCollapse v-if="analysis.missing_nef.length" class="lists">
            <NCollapseItem :title="`${analysis.missing_nef.length} 个 JPG 缺少对应 NEF（点击展开查看）`" name="missing">
              <p class="collapse-hint">以下 JPG 在 full/like 中没有对应 NEF，请检查 NEF 是否完整复制。点击文件名预览图片。</p>
              <div class="file-list"><div v-for="file in analysis.missing_nef" :key="file.path" class="file-row clickable" @click="onPreview(file)"><span class="file-name">{{ file.name }}</span><span class="file-date">{{ file.dir }}/</span></div></div>
            </NCollapseItem>
          </NCollapse>
          <NCollapse v-if="analysis.no_date.length" class="lists">
            <NCollapseItem :title="`${analysis.no_date.length} 个文件无法读取拍摄时间（点击展开查看）`" name="nodate">
              <p class="collapse-hint">以下文件无法读取拍摄时间，点击文件名预览图片。</p>
              <div class="file-list"><div v-for="file in analysis.no_date" :key="file.path" class="file-row clickable" @click="onPreview(file)"><span class="file-name">{{ file.name }}</span><span class="file-date">{{ file.dir }}/</span></div></div>
            </NCollapseItem>
          </NCollapse>
        </div>
        <div v-if="migrateResult" class="migrate-result">
          <NAlert type="success" :bordered="false">已迁移 {{ migrateResult.migrated_count }} 个 NEF 到 like 目录<template v-if="migrateResult.failed.length">，{{ migrateResult.failed.length }} 个失败。</template></NAlert>
          <NAlert type="info" :bordered="false" class="warn-item">仅复制、未删除任何文件。nef/ 目录中的文件请自行确认后清理。</NAlert>
        </div>
      </template>
      <NEmpty v-else-if="!analyzing" description="尚未分析，请点击下方按钮" size="small" />
    </NSpin>
    <NSpace justify="end" class="step-actions">
      <NButton @click="onBack">上一步</NButton>
      <NButton :loading="analyzing" @click="onAnalyze">重新分析</NButton>
      <NButton type="primary" :loading="migrating" :disabled="!analysis || analysis.favorite_count === 0" @click="onMigrate">确认执行，迁移收藏 NEF</NButton>
      <NButton type="primary" :disabled="!canProceed" @click="onNext">进入下一步（上传）</NButton>
    </NSpace>
  </NCard>
</template>

<style scoped src="./ImportWorkflowStepShared.css"></style>
