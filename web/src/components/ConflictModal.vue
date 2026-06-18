<script setup lang="ts">
import { NModal, NButton, NRadio, NSpace } from 'naive-ui'
import { ref } from 'vue'
import type { ConflictInfo, ConflictResolution } from '../types/upload'

const props = defineProps<{
  show: boolean
  conflict: ConflictInfo | null
  newFilename: string
  newShotAt: string
}>()

const emit = defineEmits<{
  close: []
  resolve: [resolution: ConflictResolution]
}>()

const selected = ref<ConflictResolution>('keep_both')
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="文件名冲突"
    style="max-width: 560px"
    @close="$emit('close')"
  >
    <template v-if="conflict">
      <div class="conflict-compare">
        <div class="compare-side">
          <h4>已有图片</h4>
          <img
            v-if="conflict.existing_thumbnail_url"
            :src="conflict.existing_thumbnail_url"
            class="compare-thumb"
          />
          <p class="compare-name">{{ conflict.existing_filename }}</p>
          <p v-if="conflict.existing_shot_at" class="compare-meta">
            拍摄: {{ new Date(conflict.existing_shot_at).toLocaleString('zh-CN') }}
          </p>
        </div>
        <div class="compare-side">
          <h4>新上传图片</h4>
          <p class="compare-name">{{ newFilename }}</p>
          <p v-if="newShotAt" class="compare-meta">
            拍摄: {{ new Date(newShotAt).toLocaleString('zh-CN') }}
          </p>
        </div>
      </div>

      <p class="conflict-hint">
        两张图片的文件名相同，可能是重复文件。
      </p>

      <div class="conflict-options">
        <NRadio
          :checked="selected === 'overwrite'"
          value="overwrite"
          @change="selected = 'overwrite'"
        >
          覆盖已有图片（删除旧图，保留新图）
        </NRadio>
        <NRadio
          :checked="selected === 'skip'"
          value="skip"
          @change="selected = 'skip'"
        >
          跳过（保留旧图，丢弃新图）
        </NRadio>
        <NRadio
          :checked="selected === 'keep_both'"
          value="keep_both"
          @change="selected = 'keep_both'"
        >
          保留两者（新图加序号后缀另存）
        </NRadio>
      </div>

      <NSpace justify="end" style="margin-top: 20px">
        <NButton
          type="primary"
          @click="$emit('resolve', selected)"
        >
          确认
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.conflict-compare {
  display: flex;
  gap: 20px;
}
.compare-side {
  flex: 1;
  text-align: center;
}
.compare-side h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--n-text-color-2);
}
.compare-thumb {
  width: 100%;
  max-height: 160px;
  object-fit: cover;
  border-radius: 6px;
}
.compare-name {
  font-size: 12px;
  margin: 4px 0;
}
.compare-meta {
  font-size: 11px;
  color: var(--n-text-color-3);
  margin: 0;
}
.conflict-hint {
  color: var(--n-text-color-2);
  font-size: 13px;
  margin: 12px 0 8px;
}
.conflict-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
</style>
