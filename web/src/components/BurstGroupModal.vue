<script setup lang="ts">
/**
 * BurstGroupModal — 连拍组展开弹窗
 *
 * 主图按原始像素尺寸展示（存储图片为 ≤512px 压缩缩略图，放大是糊的，不做放大预览）。
 * 底部缩略列表切换当前照片，「设为封面」把当前照片设为组封面，点击主图进照片详情。
 */
import { ref, watch, computed } from 'vue'
import { NModal, NButton, NIcon, NSpin, NEmpty, NTooltip, NCheckbox } from 'naive-ui'
import { StarOutline, CheckmarkCircleOutline } from '@vicons/ionicons5'

// 连拍组成员的最小展示形态：图片管理与图文工坊的成员对象都满足此结构
interface BurstMember {
  id: string
  thumbnail_url: string
  filename: string
}

const props = withDefaults(defineProps<{
  show: boolean
  groupId: string
  members: BurstMember[]
  coverId: string
  loading: boolean
  /** cover：图片管理设为封面；curate：图文工坊连拍精选 */
  mode?: 'cover' | 'curate'
}>(), {
  mode: 'cover',
})

const emit = defineEmits<{
  close: []
  viewDetail: [photoId: string]
  setCover: [photoId: string]
  curate: [photoIds: string[]]
}>()

// 当前选中的照片：打开弹窗时默认停在封面
const selectedId = ref('')
// curate 模式下已勾选的子图集合
const selectedIds = ref<Set<string>>(new Set())

const isCurate = computed(() => props.mode === 'curate')

watch(
  () => props.groupId,
  (gid) => {
    selectedIds.value = new Set()
    if (gid) {
      selectedId.value = props.coverId
    } else {
      selectedId.value = ''
    }
  },
  { immediate: true },
)

// 成员就绪后，若选中项不在组内（封面 id 缺失等），回退到第一张
watch(
  () => props.members,
  (list) => {
    if (list.length === 0) return
    if (!list.some((p) => p.id === selectedId.value)) {
      selectedId.value = list[0].id
    }
  },
)

const selected = computed(
  () => props.members.find((p) => p.id === selectedId.value) ?? null,
)

const isCover = computed(() => selectedId.value !== '' && selectedId.value === props.coverId)

function selectPhoto(id: string) {
  selectedId.value = id
}

function toggleSelect(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function handleThumbClick(id: string) {
  if (isCurate.value) toggleSelect(id)
  selectPhoto(id)
}

function handleSetCover() {
  if (!selectedId.value || isCover.value) return
  emit('setCover', selectedId.value)
}

function handleCurate() {
  const ids = props.members
    .filter((m) => selectedIds.value.has(m.id))
    .map((m) => m.id)
  if (ids.length === 0) return
  emit('curate', ids)
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`连拍组 · ${members.length || '...' } 张`"
    :style="{ width: '600px', maxWidth: 'calc(100vw - 32px)' }"
    :mask-closable="true"
    @update:show="(v: boolean) => !v && emit('close')"
  >
    <!-- 加载中 -->
    <div v-if="loading" class="burst-modal-state">
      <NSpin size="medium" />
    </div>

    <!-- 空组 -->
    <div v-else-if="members.length === 0" class="burst-modal-state">
      <NEmpty description="组内没有照片" />
    </div>

    <template v-else>
      <!-- 主图：原始尺寸展示，点击进入照片详情 -->
      <div class="burst-main">
        <NTooltip trigger="hover">
          <template #trigger>
            <img
              v-if="selected"
              :key="selected.id"
              :src="selected.thumbnail_url"
              :alt="selected.filename"
              class="burst-main-img"
              @click="emit('viewDetail', selected.id)"
            />
          </template>
          点击查看照片详情
        </NTooltip>
      </div>

      <!-- 操作行：左侧当前照片文件名，右侧封面 / 精选操作 -->
      <div class="burst-actions">
        <span class="burst-filename">{{ selected?.filename ?? '' }}</span>
        <div v-if="isCurate" class="burst-curate-actions">
          <span class="burst-selected-count">已选 {{ selectedIds.size }} 张</span>
          <NButton
            size="small"
            type="primary"
            :disabled="selectedIds.size === 0"
            @click="handleCurate"
          >
            <template #icon>
              <NIcon size="14"><CheckmarkCircleOutline /></NIcon>
            </template>
            连拍精选
          </NButton>
        </div>
        <NTooltip v-else :disabled="!isCover" trigger="hover">
          <template #trigger>
            <NButton
              size="small"
              type="primary"
              :secondary="isCover"
              :disabled="isCover"
              @click="handleSetCover"
            >
              <template #icon>
                <NIcon size="14"><StarOutline /></NIcon>
              </template>
              设为封面
            </NButton>
          </template>
          该照片已是本组封面
        </NTooltip>
      </div>

      <!-- 底部缩略列表：点击切换（curate 模式下同时勾选） -->
      <div class="burst-strip">
        <div
          v-for="p in members"
          :key="p.id"
          class="burst-thumb-wrap"
          :class="{ 'burst-thumb-active': p.id === selectedId }"
          :title="p.filename"
          @click="handleThumbClick(p.id)"
        >
          <img :src="p.thumbnail_url" :alt="p.filename" class="burst-thumb" />
          <NCheckbox
            v-if="isCurate"
            :checked="selectedIds.has(p.id)"
            class="burst-thumb-check"
            @click.stop
            @update:checked="toggleSelect(p.id)"
          />
          <span v-if="p.id === coverId" class="burst-thumb-cover-mark">封面</span>
        </div>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.burst-modal-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}
.burst-main {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 160px;
  background: var(--n-color-embedded);
  border-radius: 8px;
  padding: 8px;
}
.burst-main-img {
  display: block;
  /* 仅限制上限，不拉伸：图片保持原始像素尺寸 */
  max-width: 100%;
  max-height: 400px;
  height: auto;
  border-radius: 4px;
  cursor: pointer;
}
.burst-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 8px;
}
.burst-filename {
  font-size: 12px;
  color: var(--n-text-color-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.burst-curate-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.burst-selected-count {
  font-size: 12px;
  color: var(--n-text-color-2);
  white-space: nowrap;
}
.burst-strip {
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  overflow-x: auto;
  margin-top: 8px;
  padding-bottom: 4px;
}
.burst-thumb-wrap {
  position: relative;
  flex-shrink: 0;
  cursor: pointer;
  border-radius: 6px;
  border: 2px solid transparent;
  transition: border-color 0.15s;
}
.burst-thumb-wrap:hover {
  border-color: var(--n-border-color);
}
.burst-thumb-active {
  border-color: var(--n-color-primary);
}
.burst-thumb {
  display: block;
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 4px;
}
.burst-thumb-check {
  position: absolute;
  top: 2px;
  right: 2px;
}
.burst-thumb-cover-mark {
  position: absolute;
  left: 0;
  bottom: 0;
  right: 0;
  padding: 1px 0;
  font-size: 10px;
  text-align: center;
  color: #fff;
  background: rgba(24, 108, 248, 0.78);
  border-radius: 0 0 4px 4px;
}
</style>
