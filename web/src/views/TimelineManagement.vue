<script setup lang="ts">
/**
 * TimelineManagement — 时间线管理页。
 *
 * 活动事件的增删改 + 全量重算（进度轮询）+ 散片组只读展示。
 * 重算语义：人工改过的 timeline 保留，事件匹配 + 散片名自动填充其余照片。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NButton,
  NIcon,
  NInput,
  NDatePicker,
  NEmpty,
  NSpin,
  NSpace,
  NTag,
  NTooltip,
  NModal,
  NForm,
  NFormItem,
  NPopconfirm,
  useMessage,
} from 'naive-ui'
import {
  AddOutline,
  CreateOutline,
  TrashOutline,
  RefreshOutline,
  CalendarOutline,
} from '@vicons/ionicons5'
import { useTimelines, type TimelineEventItem } from '../composables/useTimelines'

const message = useMessage()

const {
  events,
  scattered,
  eventsLoading,
  eventsError,
  recomputeStatus,
  fetchEvents,
  saveEvent,
  deleteEvent,
  recompute,
  fetchRecomputeStatus,
  stopPolling,
} = useTimelines()

// ── 事件编辑弹窗 ──
const showEditModal = ref(false)
const editingId = ref('') // 空串 = 新建
const formDate = ref<number | null>(null)
const formEvent = ref('')
const formNote = ref('')
const saving = ref(false)

function openCreate() {
  editingId.value = ''
  formDate.value = Date.now()
  formEvent.value = ''
  formNote.value = ''
  showEditModal.value = true
}

function openEdit(e: TimelineEventItem) {
  editingId.value = e.id
  formDate.value = new Date(e.date + 'T00:00:00').getTime()
  formEvent.value = e.event
  formNote.value = e.note
  showEditModal.value = true
}

async function handleSave() {
  if (!formDate.value || !formEvent.value.trim()) {
    message.warning('请填写日期和活动名')
    return
  }
  const d = new Date(formDate.value)
  const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  saving.value = true
  try {
    await saveEvent({
      id: editingId.value || undefined,
      date: dateStr,
      event: formEvent.value.trim(),
      note: formNote.value.trim(),
    })
    message.success(editingId.value ? '事件已更新' : '事件已创建')
    showEditModal.value = false
    await fetchEvents()
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(e: TimelineEventItem) {
  try {
    await deleteEvent(e.id)
    message.success(`已删除「${e.event}」（照片需重算后清理该 timeline）`)
    await fetchEvents()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除失败')
  }
}

// ── 重算 ──
const recomputing = computed(() => recomputeStatus.value.running)
const recomputePercent = computed(() => {
  const { processed, total } = recomputeStatus.value
  if (total <= 0) return 0
  return Math.min(100, Math.round((processed / total) * 100))
})

async function handleRecompute() {
  try {
    const st = await recompute(async () => {
      const s = recomputeStatus.value
      message.success(
        `时间线重算完成：事件匹配 ${s.event_count} 张 / 散片填充 ${s.scattered_count} 张`,
      )
      await fetchEvents()
    })
    if (st === 'already_running') {
      message.info('时间线重算已在进行中')
    } else {
      message.success('时间线重算已启动')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '启动失败')
  }
}

// ── 初始化 ──
onMounted(() => {
  fetchEvents()
  fetchRecomputeStatus()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <NLayout class="page-layout">
    <NLayoutHeader bordered>
      <div class="toolbar">
        <h3 class="toolbar-title">时间线管理</h3>
        <NSpace :wrap="false">
          <NButton type="primary" @click="openCreate">
            <template #icon>
              <NIcon><AddOutline /></NIcon>
            </template>
            新建活动
          </NButton>
          <NButton :loading="recomputing" @click="handleRecompute">
            <template #icon>
              <NIcon><RefreshOutline /></NIcon>
            </template>
            重算时间线
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <NLayoutContent>
      <div class="content-wrapper">
        <!-- 重算进度条 -->
        <div v-if="recomputing" class="recompute-bar">
          <NSpin size="small" />
          <span>正在重算 {{ recomputeStatus.processed }}/{{ recomputeStatus.total }}（{{ recomputePercent }}%）</span>
        </div>
        <!-- 重算结果摘要（未在跑且有数据时） -->
        <div v-else-if="recomputeStatus.total > 0" class="recompute-bar done">
          <span>
            上次重算：事件匹配 {{ recomputeStatus.event_count }} 张 / 散片填充 {{ recomputeStatus.scattered_count }} 张
          </span>
        </div>

        <div class="columns">
          <!-- 活动事件列表 -->
          <div class="column">
            <div class="column-title">
              <NIcon><CalendarOutline /></NIcon>
              <span>活动事件</span>
              <NTag size="small" type="info">{{ events.length }}</NTag>
            </div>

            <div v-if="eventsLoading" class="column-state">
              <NSpin size="large" />
            </div>
            <NEmpty v-else-if="eventsError" class="column-state" :description="eventsError" />
            <NEmpty
              v-else-if="events.length === 0"
              class="column-state"
              description="暂无活动事件，点击右上角「新建活动」"
            />
            <div v-else class="event-list">
              <div v-for="e in events" :key="e.id" class="event-item">
                <div class="event-date">{{ e.date }}</div>
                <div class="event-body">
                  <div class="event-name">{{ e.event }}</div>
                  <div v-if="e.note" class="event-note">{{ e.note }}</div>
                </div>
                <div class="event-meta">
                  <NTooltip trigger="hover">
                    <template #trigger>
                      <NTag size="small" :type="e.photo_count > 0 ? 'success' : 'default'">
                        {{ e.photo_count }} 张
                      </NTag>
                    </template>
                    该活动名下的照片数
                  </NTooltip>
                  <NButton size="tiny" quaternary @click="openEdit(e)">
                    <template #icon>
                      <NIcon><CreateOutline /></NIcon>
                    </template>
                  </NButton>
                  <NPopconfirm @positive-click="handleDelete(e)">
                    <template #trigger>
                      <NButton size="tiny" quaternary type="error">
                        <template #icon>
                          <NIcon><TrashOutline /></NIcon>
                        </template>
                      </NButton>
                    </template>
                    删除活动「{{ e.event }}」？已归入该活动的照片 timeline 将在下次重算时清理。
                  </NPopconfirm>
                </div>
              </div>
            </div>
          </div>

          <!-- 散片组（只读） -->
          <div class="column">
            <div class="column-title">
              <NIcon><CalendarOutline /></NIcon>
              <span>散片组</span>
              <NTag size="small" type="info">{{ scattered.length }}</NTag>
            </div>

            <div v-if="eventsLoading" class="column-state">
              <NSpin size="large" />
            </div>
            <NEmpty
              v-else-if="scattered.length === 0"
              class="column-state"
              description="暂无散片组，重算时间线后自动生成"
            />
            <div v-else class="event-list">
              <div v-for="g in scattered" :key="g.event" class="event-item scattered">
                <div class="event-date">{{ g.date }}</div>
                <div class="event-body">
                  <div class="event-name">{{ g.event }}</div>
                </div>
                <div class="event-meta">
                  <NTag size="small">{{ g.photo_count }} 张</NTag>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </NLayoutContent>
  </NLayout>

  <!-- 事件编辑弹窗 -->
  <NModal
    v-model:show="showEditModal"
    preset="card"
    :title="editingId ? '编辑活动' : '新建活动'"
    style="width: 420px"
  >
    <NForm label-placement="left" label-width="64">
      <NFormItem label="日期" required>
        <NDatePicker v-model:value="formDate" type="date" style="width: 100%" />
      </NFormItem>
      <NFormItem label="活动名" required>
        <NInput v-model:value="formEvent" placeholder="如：兰圃" maxlength="100" />
      </NFormItem>
      <NFormItem label="备注">
        <NInput v-model:value="formNote" type="textarea" :rows="2" placeholder="可选" />
      </NFormItem>
    </NForm>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="showEditModal = false">取消</NButton>
        <NButton type="primary" :loading="saving" @click="handleSave">保存</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
/* 补齐高度链（与 PhotoManagement 同模式） */
.page-layout > :deep(.n-layout-scroll-container) {
  display: flex;
  flex-direction: column;
}
.page-layout :deep(.n-layout-header) {
  flex-shrink: 0;
}
.page-layout :deep(.n-layout-content) {
  flex: 1;
  min-height: 0;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.toolbar-title {
  margin: 0;
  font-size: 16px;
}
.content-wrapper {
  height: 100%;
  box-sizing: border-box;
  padding: 20px 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.recompute-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: 8px;
  background: var(--n-color-embedded);
  font-size: 13px;
  color: var(--n-text-color-2);
}
.recompute-bar.done {
  color: var(--n-text-color-3);
}
.columns {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  flex: 1;
  min-height: 0;
}
.column {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.column-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--n-border-color);
}
.column-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}
.event-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.event-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  background: var(--n-card-color);
}
.event-item.scattered {
  background: var(--n-color-embedded);
}
.event-date {
  font-size: 13px;
  color: var(--n-text-color-3);
  white-space: nowrap;
  flex-shrink: 0;
}
.event-body {
  flex: 1;
  min-width: 0;
}
.event-name {
  font-size: 14px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.event-note {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.event-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
</style>
