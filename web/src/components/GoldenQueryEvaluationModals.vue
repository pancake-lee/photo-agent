<script setup lang="ts">
import { NButton, NDataTable, NIcon, NModal, NSpin, type DataTableColumns } from 'naive-ui'
import { EyeOutline } from '@vicons/ionicons5'
import PhotoThumbList from './PhotoThumbList.vue'
import type { EvalDetail, EvalResult } from '../types/goldenQuery'

defineProps<{
  resultVisible: boolean
  evaluating: boolean
  result: EvalResult | null
  itemCount: number
  columns: DataTableColumns<EvalDetail>
  detailVisible: boolean
  detail: EvalDetail | null
  appending: boolean
  appendSelected: string[]
  imageBase: string
}>()

const emit = defineEmits<{
  'update:resultVisible': [value: boolean]
  'update:detailVisible': [value: boolean]
  showDetail: [detail: EvalDetail]
  preview: [uuid: string]
  toggleAppend: [photoId: string]
  append: []
}>()
</script>

<template>
  <NModal :show="resultVisible" preset="card" title="黄金用例评估结果" style="width: 820px; max-width: 95vw;" :mask-closable="!evaluating" @update:show="emit('update:resultVisible', $event)">
    <div class="eval-table-hint">随着时间推移，图库的变化，用例评估结果也会变化，主要表现为分数下降，是相关的照片增加导致的。<br>请点击条目查看详情，确认遗漏/未命中的具体照片。<br>遗漏：可能因为新照片得分更高，把目标照片挤出输出列表了。<br>未命中：可能是新照片被检索到了，但“当初”目标集合没有记录，程序误以为是错误照片。</div>
    <div v-if="evaluating" class="eval-loading"><NSpin size="large" /><p>正在运行 {{ itemCount }} 条黄金用例评估...</p></div>
    <div v-else-if="result" class="eval-result">
      <div class="eval-summary">
        <div class="eval-metric"><span class="eval-metric-value">{{ (result.precision_at_k * 100).toFixed(1) }}%</span><span class="eval-metric-label">P@{{ result.precision_k }}</span></div>
        <div class="eval-metric"><span class="eval-metric-value">{{ (result.recall_at_k * 100).toFixed(1) }}%</span><span class="eval-metric-label">Recall</span></div>
        <div class="eval-metric"><span class="eval-metric-value">{{ (result.mrr * 100).toFixed(1) }}%</span><span class="eval-metric-label">MRR</span></div>
        <div class="eval-metric"><span class="eval-metric-value">{{ result.total }}</span><span class="eval-metric-label">用例数</span></div>
      </div>
      <div class="eval-table-hint">点击查询名称查看命中/遗漏详情</div>
      <NDataTable :columns="columns" :data="result.details" :row-key="(row: EvalDetail) => row.question" :single-line="false" size="small" :max-height="400" :row-props="(row: EvalDetail) => ({ style: 'cursor: pointer;', onClick: () => emit('showDetail', row) })" style="margin-top: 8px;" />
    </div>
  </NModal>

  <NModal :show="detailVisible" preset="card" :title="detail?.question || '评估明细'" style="width: 720px; max-width: 95vw;" @update:show="emit('update:detailVisible', $event)">
    <div v-if="detail" class="eval-detail-body">
      <div class="eval-detail-metrics"><span class="eval-detail-badge">P@{{ detail.effective_k || 10 }}: {{ (detail.precision * 100).toFixed(0) }}%</span><span class="eval-detail-badge">Recall: {{ (detail.recall * 100).toFixed(0) }}%</span><span class="eval-detail-badge">MRR: {{ (detail.mrr * 100).toFixed(0) }}%</span><span class="eval-detail-badge">检索 {{ detail.retrieved }} / 相关 {{ detail.relevant }}</span></div>
      <div class="eval-section"><div class="eval-section-title">✅ 命中 ({{ detail.hits }} 张)<span class="eval-section-sub">检索结果中属于正确答案的照片</span></div><PhotoThumbList :photos="detail.hit_ids" empty-text="无命中" @preview="emit('preview', $event)" /></div>
      <div class="eval-section"><div class="eval-section-title">❌ 遗漏 ({{ detail.remaining_ids.length }} 张)<span class="eval-section-sub">标注为相关但未检索到的照片</span></div><PhotoThumbList :photos="detail.remaining_ids" empty-text="无遗漏" @preview="emit('preview', $event)" /></div>
      <div class="eval-section"><div class="eval-section-title">⬜ 未命中 ({{ detail.miss_ids.length }} 张)<span class="eval-section-sub">检索到了但用例未标注的照片，确认正确后可加入用例</span></div>
        <PhotoThumbList v-if="!detail.golden_id || detail.miss_ids.length === 0" :photos="detail.miss_ids" empty-text="无多余" @preview="emit('preview', $event)" />
        <template v-else><div class="miss-grid"><div v-for="photo in detail.miss_ids" :key="photo.photo_id" class="miss-item" :class="{ selected: appendSelected.includes(photo.photo_id) }" @click="emit('toggleAppend', photo.photo_id)"><img class="miss-thumb" :src="`${imageBase}/photos/${photo.uuid}/image`"><span class="miss-preview" title="查看大图" @click.stop="emit('preview', photo.uuid)"><NIcon size="12"><EyeOutline /></NIcon></span><span v-if="appendSelected.includes(photo.photo_id)" class="miss-check">✓</span><div class="miss-label">{{ photo.filename }}</div></div></div><div class="miss-actions"><NButton size="small" type="primary" :loading="appending" :disabled="appendSelected.length === 0" @click="emit('append')">加入用例（{{ appendSelected.length }}）</NButton><span class="miss-hint">点击缩略图选择，加入后自动复评</span></div></template>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
.eval-loading, .eval-detail-body, .eval-section { display: flex; flex-direction: column; }
.eval-loading { align-items: center; gap: 16px; padding: 32px; color: var(--n-text-color-3); }
.eval-summary { display: flex; gap: 24px; padding: 16px 0; border-bottom: 1px solid var(--n-border-color); }
.eval-metric { display: flex; flex-direction: column; align-items: center; gap: 4px; }.eval-metric-value { font-size: 24px; font-weight: 700; color: var(--n-color-primary); }.eval-metric-label, .eval-table-hint, .eval-section-sub, .miss-hint { font-size: 12px; color: var(--n-text-color-3); }.eval-table-hint { margin-top: 12px; }
.eval-detail-body { gap: 20px; }.eval-detail-metrics { display: flex; gap: 12px; flex-wrap: wrap; }.eval-detail-badge { padding: 4px 12px; border-radius: 4px; background: var(--n-color-embedded); font-size: 13px; font-weight: 500; }.eval-section { gap: 8px; }.eval-section-title { font-size: 14px; font-weight: 600; }.eval-section-sub { font-weight: 400; margin-left: 8px; }
.miss-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 8px; max-height: 240px; overflow-y: auto; }.miss-item { position: relative; cursor: pointer; border: 2px solid transparent; border-radius: 6px; overflow: hidden; transition: border-color .15s; }.miss-item.selected { border-color: var(--n-color-target); }.miss-thumb { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }.miss-preview, .miss-check { position: absolute; top: 4px; width: 20px; height: 20px; border-radius: 50%; color: #fff; display: flex; align-items: center; justify-content: center; }.miss-preview { left: 4px; background: rgba(0,0,0,.45); }.miss-check { right: 4px; background: var(--n-color-target); font-size: 12px; font-weight: 700; }.miss-label { font-size: 10px; color: var(--n-text-color-3); text-align: center; padding: 2px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.miss-actions { display: flex; align-items: center; gap: 12px; }
</style>
