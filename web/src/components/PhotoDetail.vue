<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import {
  NDescriptions,
  NDescriptionsItem,
  NButton,
  NSpin,
  NSpace,
  NDivider,
  NEmpty,
  NTag,
  NDatePicker,
  NIcon,
  useMessage,
} from 'naive-ui'
import { CloseOutline, ChevronBackOutline, ChevronForwardOutline } from '@vicons/ionicons5'
import type { PhotoDetail, EmbedInfo } from '../types/photo'
import { formatDate } from '../utils/format'
import { useEmbedStatus } from '../composables/useEmbedStatus'
import { usePhotos } from '../composables/usePhotos'

const { fetchEmbedInfo } = useEmbedStatus()
const { updatePhotoShotAt } = usePhotos()
const message = useMessage()

// 上/下一张导航列表项：只关心 id（用于定位与切换），label 仅备用
export interface NavItem {
  id: string
  label?: string
}

const props = defineProps<{
  show: boolean
  photo: PhotoDetail | null
  loading: boolean
  describeProcessing: boolean
  embedProcessing: boolean
  vlmBatchRunning?: boolean
  embedBatchRunning?: boolean
  /** 用于上/下一张切换的有序列表，图片管理与图文工坊各自传入不同的列表 */
  navList?: NavItem[]
  /** 是否展示 VLM/Embed 处理按钮，图文工坊传 false（只展示信息，不提供处理入口） */
  showVlmActions?: boolean
}>()

const emit = defineEmits<{
  close: []
  triggerDescribe: [photoId: string]
  triggerEmbed: [photoId: string]
  viewDescription: []
  navigate: [photoId: string]
}>()

const showActions = computed(() => props.showVlmActions !== false)

// embed 详情（按 photo 变化自动拉取）
const embedInfo = ref<EmbedInfo | null>(null)
const embedLoading = ref(false)

// 拍摄时间编辑状态
const shotAtEditing = ref(false)
const shotAtSaving = ref(false)
const shotAtValue = ref<number | null>(null)

// ── 上/下一张导航 ──
const navIndex = computed(() => {
  if (!props.photo || !props.navList?.length) return -1
  return props.navList.findIndex((n) => n.id === props.photo!.id)
})
const navTotal = computed(() => props.navList?.length ?? 0)
const canPrev = computed(() => navIndex.value > 0)
const canNext = computed(() => navIndex.value >= 0 && navIndex.value < navTotal.value - 1)
const prevId = computed(() => (canPrev.value && props.navList ? props.navList[navIndex.value - 1].id : ''))
const nextId = computed(() => (canNext.value && props.navList ? props.navList[navIndex.value + 1].id : ''))

function goPrev() { if (canPrev.value) emit('navigate', prevId.value) }
function goNext() { if (canNext.value) emit('navigate', nextId.value) }

// 键盘导航：左右切图、Esc 关闭
function onKeydown(e: KeyboardEvent) {
  if (!props.show) return
  if (e.key === 'Escape') { emit('close'); return }
  if (e.key === 'ArrowLeft') { goPrev(); return }
  if (e.key === 'ArrowRight') { goNext() }
}
watch(
  () => props.show,
  (v) => {
    if (v) document.addEventListener('keydown', onKeydown)
    else document.removeEventListener('keydown', onKeydown)
  },
)
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

watch(
  () => props.photo?.id,
  async (photoId) => {
    embedInfo.value = null
    shotAtEditing.value = false
    if (!photoId) return
    // 无描述的照片不可能有 embedding，直接跳过
    if (!props.photo?.has_description) return
    embedLoading.value = true
    embedInfo.value = await fetchEmbedInfo(photoId)
    embedLoading.value = false
  },
)

// Embed 处理完成后自动刷新 embed 详情
watch(
  () => props.embedProcessing,
  async (processing, wasProcessing) => {
    if (wasProcessing && !processing && props.photo?.id) {
      embedLoading.value = true
      embedInfo.value = await fetchEmbedInfo(props.photo.id)
      embedLoading.value = false
    }
  },
)

function formatDateLocal(d: string | null): string {
  if (!d) return '未知'
  return formatDate(d)
}

function startEditShotAt() {
  shotAtValue.value = props.photo?.shot_at
    ? new Date(props.photo.shot_at).getTime()
    : Date.now()
  shotAtEditing.value = true
}

function cancelEditShotAt() {
  shotAtEditing.value = false
  shotAtValue.value = null
}

async function saveShotAt() {
  if (!props.photo || shotAtValue.value == null) return
  shotAtSaving.value = true
  try {
    await updatePhotoShotAt(props.photo.id, new Date(shotAtValue.value))
    message.success('拍摄时间已更新')
    shotAtEditing.value = false
    shotAtValue.value = null
  } catch (e) {
    message.error(e instanceof Error ? e.message : '更新失败')
  } finally {
    shotAtSaving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="lightbox-fade">
      <div v-if="show" class="photo-lightbox">
        <!-- 半透明遮罩 -->
        <div class="lightbox-mask" @click="$emit('close')"></div>

        <!-- 左侧大图舞台 -->
        <div class="lightbox-stage">
          <img
            v-if="photo"
            :src="photo.image_url"
            :alt="photo.filename"
            class="lightbox-image"
            @click.stop
          />
          <div v-else-if="loading" class="stage-loading">
            <NSpin size="large" />
          </div>
          <div v-else class="stage-loading">
            <NEmpty description="无照片" />
          </div>

          <!-- 加载遮罩（导航切换时保留旧图并叠加 spinner） -->
          <div v-if="loading && photo" class="stage-loading">
            <NSpin size="large" />
          </div>

          <!-- 上/下一张 -->
          <button
            v-if="canPrev"
            class="lightbox-nav prev"
            title="上一张"
            @click="goPrev"
          >
            <NIcon :size="24"><ChevronBackOutline /></NIcon>
          </button>
          <button
            v-if="canNext"
            class="lightbox-nav next"
            title="下一张"
            @click="goNext"
          >
            <NIcon :size="24"><ChevronForwardOutline /></NIcon>
          </button>

          <!-- 计数 -->
          <div v-if="navTotal > 1 && navIndex >= 0" class="lightbox-counter">
            {{ navIndex + 1 }} / {{ navTotal }}
          </div>

          <!-- 文件名 -->
          <div v-if="photo" class="lightbox-caption">{{ photo.filename }}</div>
        </div>

        <!-- 右侧详情面板 -->
        <div class="lightbox-panel">
          <div class="panel-header">
            <span class="panel-title">照片详情</span>
            <NButton size="small" @click="$emit('close')">
              <template #icon><NIcon :size="16"><CloseOutline /></NIcon></template>
              退出
            </NButton>
          </div>

          <div class="panel-body">
            <template v-if="loading && !photo">
              <div class="detail-loading">
                <NSpin size="medium" />
              </div>
            </template>

            <template v-else-if="photo">
              <!-- EXIF 信息 -->
              <NDescriptions label-placement="left" :column="1" size="small" bordered>
                <NDescriptionsItem label="文件名">{{ photo.filename }}</NDescriptionsItem>
                <NDescriptionsItem label="拍摄时间">
                  <NSpace v-if="!shotAtEditing" align="center" :size="8">
                    <span>{{ formatDateLocal(photo.shot_at) }}</span>
                    <NButton size="tiny" quaternary @click="startEditShotAt">编辑</NButton>
                  </NSpace>
                  <NSpace v-else vertical :size="8" style="width: 100%">
                    <NDatePicker
                      v-model:value="shotAtValue"
                      type="datetime"
                      size="small"
                      style="width: 100%"
                    />
                    <NSpace :size="8">
                      <NButton
                        size="tiny"
                        type="primary"
                        :loading="shotAtSaving"
                        @click="saveShotAt"
                      >
                        保存
                      </NButton>
                      <NButton size="tiny" @click="cancelEditShotAt">取消</NButton>
                    </NSpace>
                  </NSpace>
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
                  <NSpace v-if="showActions">
                    <NButton
                      size="small"
                      type="info"
                      @click="$emit('viewDescription')"
                    >
                      查看详情
                    </NButton>
                    <NButton
                      size="small"
                      :loading="describeProcessing"
                      :disabled="vlmBatchRunning"
                      @click="$emit('triggerDescribe', photo.id)"
                    >
                      重新生成
                    </NButton>
                  </NSpace>
                </template>
                <template v-else>
                  <NEmpty description="暂无描述" size="small" />
                  <NButton
                    v-if="showActions"
                    size="small"
                    type="primary"
                    :loading="describeProcessing"
                    :disabled="vlmBatchRunning"
                    style="margin-top: 8px"
                    @click="$emit('triggerDescribe', photo.id)"
                  >
                    生成描述
                  </NButton>
                </template>
              </div>

              <NDivider />

              <!-- Embedding 信息 -->
              <div class="desc-section">
                <h4>Embedding 向量</h4>
                <div v-if="embedLoading" class="desc-loading">
                  <NSpin size="small" />
                </div>
                <template v-else-if="embedInfo">
                  <NDescriptions label-placement="left" :column="1" size="small" bordered>
                    <NDescriptionsItem label="模型">
                      <NTag type="info" size="small">{{ embedInfo.model || '未知' }}</NTag>
                    </NDescriptionsItem>
                    <NDescriptionsItem label="生成时间">
                      {{ embedInfo.embedded_at ? formatDateLocal(embedInfo.embedded_at) : '未知' }}
                    </NDescriptionsItem>
                    <NDescriptionsItem label="分块数">
                      {{ embedInfo.chunks }}
                    </NDescriptionsItem>
                    <NDescriptionsItem label="文档 ID">
                      <span v-for="(ch, i) in embedInfo.chunk_info" :key="ch.id">
                        {{ ch.id }}<br v-if="i < embedInfo.chunk_info.length - 1" />
                      </span>
                    </NDescriptionsItem>
                  </NDescriptions>
                  <NButton
                    v-if="showActions"
                    size="small"
                    :loading="embedProcessing"
                    :disabled="embedBatchRunning"
                    style="margin-top: 8px"
                    @click="$emit('triggerEmbed', photo.id)"
                  >
                    重新生成
                  </NButton>
                </template>
                <template v-else-if="photo.has_description">
                  <NEmpty description="暂无 Embedding 数据" size="small" />
                  <NButton
                    v-if="showActions"
                    size="small"
                    type="warning"
                    :loading="embedProcessing"
                    :disabled="embedBatchRunning"
                    style="margin-top: 8px"
                    @click="$emit('triggerEmbed', photo.id)"
                  >
                    生成 Embedding
                  </NButton>
                </template>
                <template v-else>
                  <span class="desc-hint">需先生成 AI 描述</span>
                </template>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.photo-lightbox {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  /* 左侧让出菜单栏（SideMenu 宽度 220px），详情区域只覆盖右侧子页面 */
  left: 220px;
  z-index: 2500;
  display: flex;
}

.lightbox-mask {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.88);
}

.lightbox-stage {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.lightbox-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.6);
}

.stage-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.lightbox-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}
.lightbox-nav:hover { background: rgba(0, 0, 0, 0.72); }
.lightbox-nav.prev { left: 20px; }
.lightbox-nav.next { right: 20px; }

.lightbox-counter {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  color: #fff;
  font-size: 13px;
  background: rgba(0, 0, 0, 0.5);
  padding: 2px 12px;
  border-radius: 12px;
}

.lightbox-caption {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
  max-width: 70%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 面板硬编码暗色主题色值：naive 的 --n-* 变量是组件级注入（hash class 下），
   Teleport 到 body 后解析不到，会回退成透明/黑色，故直接写死 darkTheme 色值 */
.lightbox-panel {
  position: relative;
  width: 460px;
  flex-shrink: 0;
  background: rgb(44, 44, 50);
  color: rgba(255, 255, 255, 0.9);
  border-left: 1px solid rgba(255, 255, 255, 0.24);
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.24);
  flex-shrink: 0;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px 24px;
}

.detail-loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}

.desc-section {
  margin-top: 8px;
}
.desc-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.82);
}
.desc-text {
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  margin: 0 0 12px 0;
  max-height: 200px;
  overflow-y: auto;
}
.desc-loading {
  display: flex;
  justify-content: center;
  padding: 16px 0;
}
.desc-hint {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.52);
}

.lightbox-fade-enter-active,
.lightbox-fade-leave-active {
  transition: opacity 0.2s ease;
}
.lightbox-fade-enter-from,
.lightbox-fade-leave-to {
  opacity: 0;
}
</style>
