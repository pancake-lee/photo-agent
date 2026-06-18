<script setup lang="ts">
import {
  NDrawer,
  NDrawerContent,
  NDescriptions,
  NDescriptionsItem,
  NButton,
  NSpin,
  NSpace,
  NDivider,
  NEmpty,
} from 'naive-ui'
import type { PhotoDetail } from '../types/photo'

defineProps<{
  show: boolean
  photo: PhotoDetail | null
  loading: boolean
}>()

const emit = defineEmits<{
  close: []
  triggerDescribe: [photoId: string]
  viewDescription: []
}>()

function formatDate(d: string | null): string {
  if (!d) return '未知'
  return new Date(d).toLocaleString('zh-CN')
}
</script>

<template>
  <NDrawer :show="show" :width="480" @update:show="(v) => !v && $emit('close')">
    <NDrawerContent title="照片详情" closable>
      <template v-if="loading">
        <div class="detail-loading">
          <NSpin size="medium" />
        </div>
      </template>

      <template v-else-if="photo">
        <!-- 完整图片 -->
        <img
          v-if="photo.image_url"
          :src="photo.image_url"
          :alt="photo.filename"
          class="detail-image"
        />

        <!-- EXIF 信息 -->
        <NDescriptions label-placement="left" :column="1" size="small" bordered>
          <NDescriptionsItem label="文件名">{{ photo.filename }}</NDescriptionsItem>
          <NDescriptionsItem label="拍摄时间">
            {{ formatDate(photo.shot_at) }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.brand" label="相机品牌">
            {{ photo.brand }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.model" label="相机型号">
            {{ photo.model }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.lens" label="镜头">
            {{ photo.lens }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.focal_length" label="焦距">
            {{ photo.focal_length }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.aperture" label="光圈">
            {{ photo.aperture }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.iso" label="ISO">
            {{ photo.iso }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.exposure_time" label="快门">
            {{ photo.exposure_time }}
          </NDescriptionsItem>
          <NDescriptionsItem label="尺寸">
            {{ photo.width }} × {{ photo.height }}
          </NDescriptionsItem>
          <NDescriptionsItem v-if="photo.timeline" label="活动">
            {{ photo.timeline }}
          </NDescriptionsItem>
        </NDescriptions>

        <NDivider />

        <!-- VLM 描述 -->
        <div class="desc-section">
          <h4>AI 描述</h4>
          <template v-if="photo.has_description">
            <p class="desc-text">{{ photo.description }}</p>
            <NSpace>
              <NButton
                size="small"
                type="info"
                @click="$emit('viewDescription')"
              >
                查看详情
              </NButton>
              <NButton
                size="small"
                @click="$emit('triggerDescribe', photo.id)"
              >
                重新生成
              </NButton>
            </NSpace>
          </template>
          <template v-else>
            <NEmpty description="暂无描述" size="small" />
            <NButton
              size="small"
              type="primary"
              style="margin-top: 8px"
              @click="$emit('triggerDescribe', photo.id)"
            >
              生成描述
            </NButton>
          </template>
        </div>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
.detail-loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}
.detail-image {
  width: 100%;
  border-radius: 8px;
  margin-bottom: 16px;
}
.desc-section {
  margin-top: 8px;
}
.desc-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: var(--n-text-color-2);
}
.desc-text {
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  margin: 0 0 12px 0;
  max-height: 200px;
  overflow-y: auto;
}
</style>
