<script setup lang="ts">
import { computed } from 'vue'
import { NIcon, NEmpty, NDivider } from 'naive-ui'
import { AddCircleOutline, RemoveCircleOutline, SwapHorizontalOutline } from '@vicons/ionicons5'
import type { SuggestVersion, PipelineStep } from '../types/suggest'

const props = defineProps<{
  versionA: SuggestVersion | null
  versionB: SuggestVersion | null
}>()

// 版本标签
function versionLabel(v: SuggestVersion): string {
  return v.version_id.split('-v')[1] || v.version_id
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return iso.slice(0, 16) }
}

// 从步骤中提取关键数据
function extractStepsData(steps: PipelineStep[]): Record<string, any> {
  const data: Record<string, any> = {}
  for (const s of steps) {
    if (s.event === 'suggest.stage1.intuitions') {
      data.intuitions = s.data.intuitions || []
    }
    if (s.event === 'suggest.stage3.proposal') {
      data.proposal = {
        title: s.data.title || '',
        angle: s.data.angle || '',
        rationale: s.data.rationale || '',
        photo_sequence: s.data.photo_sequence || [],
      }
    }
    if (s.event === 'suggest.stage3.validation') {
      data.validation = { final_photo_count: s.data.final_photo_count || 0 }
    }
  }
  return data
}

const diff = computed(() => {
  if (!props.versionA || !props.versionB) return null

  const dataA = extractStepsData(props.versionA.steps || [])
  const dataB = extractStepsData(props.versionB.steps || [])

  // 提案对比
  const propA = dataA.proposal || { title: '', angle: '', rationale: '', photo_sequence: [] }
  const propB = dataB.proposal || { title: '', angle: '', rationale: '', photo_sequence: [] }

  // 照片 diff
  const photosASet = new Set((propA.photo_sequence || []).map((s: any) => s.photo_id))
  const photosBSet = new Set((propB.photo_sequence || []).map((s: any) => s.photo_id))
  const addedPhotos = (propB.photo_sequence || []).filter((s: any) => !photosASet.has(s.photo_id))
  const removedPhotos = (propA.photo_sequence || []).filter((s: any) => !photosBSet.has(s.photo_id))
  const commonPhotos = (propB.photo_sequence || []).filter((s: any) => photosASet.has(s.photo_id))

  // 叙事角色变化
  const roleChanges: Array<{ photo_id: string; oldRole: string; newRole: string }> = []
  for (const pb of (propB.photo_sequence || [])) {
    const pa = (propA.photo_sequence || []).find((s: any) => s.photo_id === pb.photo_id)
    if (pa && pa.role_in_narrative !== pb.role_in_narrative) {
      roleChanges.push({
        photo_id: pb.photo_id,
        oldRole: pa.role_in_narrative || '',
        newRole: pb.role_in_narrative || '',
      })
    }
  }

  return {
    titleA: propA.title,
    titleB: propB.title,
    angleA: propA.angle,
    angleB: propB.angle,
    rationaleA: propA.rationale,
    rationaleB: propB.rationale,
    addedPhotos,
    removedPhotos,
    commonPhotos,
    roleChanges,
    totalPhotosA: (propA.photo_sequence || []).length,
    totalPhotosB: (propB.photo_sequence || []).length,
  }
})

import { getApiBase } from '../config'

function thumbUrl(photoId: string): string {
  return photoId ? `${getApiBase()}/photos/${photoId}/image` : ''
}
</script>

<template>
  <div v-if="!versionA || !versionB" class="diff-empty">
    <NEmpty description="请选择两个版本进行对比" size="small" />
  </div>

  <div v-else-if="diff" class="diff-container">
    <!-- 版本标签栏 -->
    <div class="diff-header">
      <div class="diff-version-label left">
        v{{ versionLabel(versionA) }}
        <span class="diff-time">{{ formatTime(versionA.created_at) }}</span>
      </div>
      <NIcon size="16" color="var(--n-text-color-3)"><SwapHorizontalOutline /></NIcon>
      <div class="diff-version-label right">
        v{{ versionLabel(versionB) }}
        <span class="diff-time">{{ formatTime(versionB.created_at) }}</span>
      </div>
    </div>

    <!-- 文本对比：标题 -->
    <div class="diff-section">
      <div class="diff-section-title">标题</div>
      <div class="diff-row">
        <div class="diff-cell removed" v-if="diff.titleA !== diff.titleB">
          <span class="diff-prefix">−</span>{{ diff.titleA || '（空）' }}
        </div>
        <div class="diff-cell added" v-if="diff.titleA !== diff.titleB">
          <span class="diff-prefix">+</span>{{ diff.titleB || '（空）' }}
        </div>
        <div class="diff-cell same" v-if="diff.titleA === diff.titleB">
          {{ diff.titleA }}
        </div>
      </div>
    </div>

    <!-- 文本对比：角度 -->
    <div class="diff-section">
      <div class="diff-section-title">发布角度</div>
      <div class="diff-row" v-if="diff.angleA !== diff.angleB">
        <div class="diff-cell removed">
          <span class="diff-prefix">−</span>{{ diff.angleA || '（空）' }}
        </div>
        <div class="diff-cell added">
          <span class="diff-prefix">+</span>{{ diff.angleB || '（空）' }}
        </div>
      </div>
      <div class="diff-cell same" v-else>{{ diff.angleA }}</div>
    </div>

    <!-- 文本对比：理由 -->
    <div class="diff-section">
      <div class="diff-section-title">选题理由</div>
      <div class="diff-row" v-if="diff.rationaleA !== diff.rationaleB">
        <div class="diff-cell removed">
          <span class="diff-prefix">−</span>{{ diff.rationaleA || '（空）' }}
        </div>
        <div class="diff-cell added">
          <span class="diff-prefix">+</span>{{ diff.rationaleB || '（空）' }}
        </div>
      </div>
      <div class="diff-cell same" v-else>{{ diff.rationaleA }}</div>
    </div>

    <NDivider />

    <!-- 照片序列对比 -->
    <div class="diff-section">
      <div class="diff-section-title">
        照片序列（{{ diff.totalPhotosA }} → {{ diff.totalPhotosB }} 张）
      </div>

      <!-- 新增照片 -->
      <div v-if="diff.addedPhotos.length > 0" class="photo-diff-group">
        <span class="photo-diff-label added-label">
          <NIcon size="12"><AddCircleOutline /></NIcon> 新增 {{ diff.addedPhotos.length }} 张
        </span>
        <div class="thumb-grid">
          <div
            v-for="s in diff.addedPhotos.slice(0, 12)"
            :key="s.photo_id"
            class="thumb-item added-border"
            :title="s.photo_id"
          >
            <img :src="thumbUrl(s.photo_id)" loading="lazy" />
            <span class="thumb-role">{{ s.role_in_narrative }}</span>
          </div>
        </div>
      </div>

      <!-- 移除照片 -->
      <div v-if="diff.removedPhotos.length > 0" class="photo-diff-group">
        <span class="photo-diff-label removed-label">
          <NIcon size="12"><RemoveCircleOutline /></NIcon> 移除 {{ diff.removedPhotos.length }} 张
        </span>
        <div class="thumb-grid">
          <div
            v-for="s in diff.removedPhotos.slice(0, 12)"
            :key="s.photo_id"
            class="thumb-item removed-border"
            :title="s.photo_id"
          >
            <img :src="thumbUrl(s.photo_id)" loading="lazy" />
            <span class="thumb-role">{{ s.role_in_narrative }}</span>
          </div>
        </div>
      </div>

      <!-- 叙事角色变化 -->
      <div v-if="diff.roleChanges.length > 0" class="role-changes">
        <span class="photo-diff-label">🔄 叙事角色变化</span>
        <div v-for="rc in diff.roleChanges" :key="rc.photo_id" class="role-change-item">
          <span class="rc-id">{{ rc.photo_id.slice(0, 12) }}...</span>
          <span class="rc-old">{{ rc.oldRole || '（无）' }}</span>
          <span class="rc-arrow">→</span>
          <span class="rc-new">{{ rc.newRole || '（无）' }}</span>
        </div>
      </div>

      <!-- 无变化 -->
      <div v-if="diff.addedPhotos.length === 0 && diff.removedPhotos.length === 0 && diff.roleChanges.length === 0" class="diff-cell same">
        照片序列无变化（{{ diff.commonPhotos.length }} 张）
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.diff-empty {
  padding: 40px 0;
}
.diff-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}
.diff-version-label {
  font-size: 14px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
}
.diff-version-label.left {
  background: var(--n-error-color-suppl);
  color: var(--n-error-color);
}
.diff-version-label.right {
  background: var(--n-success-color-suppl);
  color: var(--n-success-color);
}
.diff-time {
  font-size: 11px;
  font-weight: 400;
  margin-left: 8px;
  opacity: 0.7;
}
.diff-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.diff-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--n-text-color-3);
  text-transform: uppercase;
  margin-bottom: 2px;
}
.diff-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.diff-cell {
  font-size: 13px;
  padding: 6px 8px;
  border-radius: 4px;
  line-height: 1.5;
}
.diff-cell.removed {
  background: var(--n-error-color-suppl);
  color: var(--n-error-color);
}
.diff-cell.added {
  background: var(--n-success-color-suppl);
  color: var(--n-success-color);
}
.diff-cell.same {
  color: var(--n-text-color-2);
}
.diff-prefix {
  font-weight: 700;
  margin-right: 4px;
}
.photo-diff-group {
  margin-top: 8px;
}
.photo-diff-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
}
.added-label { color: var(--n-success-color); }
.removed-label { color: var(--n-error-color); }
.thumb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(64px, 1fr));
  gap: 4px;
}
.thumb-item {
  width: 64px;
  height: 64px;
  overflow: hidden;
  border-radius: 4px;
  position: relative;
  background: var(--n-action-color);
}
.thumb-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-item.added-border {
  border: 2px solid var(--n-success-color);
}
.thumb-item.removed-border {
  border: 2px solid var(--n-error-color);
  opacity: 0.6;
}
.thumb-role {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  font-size: 9px;
  padding: 1px 3px;
  background: rgba(0,0,0,0.7);
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.role-changes {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.role-change-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 8px;
  background: var(--n-action-color);
  border-radius: 4px;
}
.rc-id {
  font-family: monospace;
  font-size: 11px;
  color: var(--n-text-color-2);
}
.rc-old {
  color: var(--n-error-color);
  text-decoration: line-through;
}
.rc-arrow {
  color: var(--n-text-color-3);
}
.rc-new {
  color: var(--n-success-color);
}
</style>
