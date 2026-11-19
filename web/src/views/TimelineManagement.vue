<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NLayout, NLayoutContent, NLayoutHeader, NButton, NIcon, NInput,
  NDatePicker, NEmpty, NSpin, NSpace, NTag, NModal, NForm, NFormItem,
  NPopconfirm, NTable, useMessage } from 'naive-ui'
import { AddOutline, CreateOutline, TrashOutline, RefreshOutline,
  CalendarOutline } from '@vicons/ionicons5'
import { useTimelines, type TimelineEventItem } from '../composables/useTimelines'

const message = useMessage()
const router = useRouter()
const { events, eventsLoading, eventsError, fetchEvents, saveEvent,
  deleteEvent, recompute } = useTimelines()
const showEditModal = ref(false)
const editingId = ref('')
const formDate = ref<number | null>(null)
const formEvent = ref('')
const formNote = ref('')
const saving = ref(false)
const syncing = ref(false)

function openCreate() {
  editingId.value = ''
  formDate.value = null
  formEvent.value = ''
  formNote.value = ''
  showEditModal.value = true
}

function openEdit(event: TimelineEventItem) {
  editingId.value = event.id
  formDate.value = event.date ? new Date(event.date.length === 10
    ? `${event.date}T00:00:00` : event.date).getTime() : null
  formEvent.value = event.event
  formNote.value = event.note
  showEditModal.value = true
}

function displayDate(date: string): string {
  if (!date) return '未设置时间'
  return date.length === 10 ? date : new Date(date).toLocaleString('zh-CN')
}

async function handleSave() {
  if (!formEvent.value.trim()) {
    message.warning('请填写活动目录名')
    return
  }
  saving.value = true
  try {
    await saveEvent({ id: editingId.value || undefined,
      date: formDate.value === null ? '' : new Date(formDate.value).toISOString(),
      event: formEvent.value.trim(), note: formNote.value.trim() })
    message.success(editingId.value ? '活动已更新' : '活动目录已创建')
    showEditModal.value = false
    await fetchEvents()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(event: TimelineEventItem) {
  try {
    await deleteEvent(event.id)
    message.success(`已删除空活动目录「${event.event}」`)
    await fetchEvents()
  } catch (error) {
    message.error(error instanceof Error ? error.message : '删除失败')
  }
}

async function handleSync() {
  syncing.value = true
  try {
    await recompute()
    await fetchEvents()
    message.success('活动目录已同步')
  } catch (error) {
    message.error(error instanceof Error ? error.message : '同步失败')
  } finally {
    syncing.value = false
  }
}

onMounted(fetchEvents)
</script>

<template>
  <NLayout class="page-layout">
    <NLayoutHeader bordered>
      <div class="toolbar">
        <h3 class="toolbar-title">时间线管理</h3>
        <NSpace :wrap="false">
          <NButton type="primary" @click="openCreate">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            新建活动
          </NButton>
          <NButton :loading="syncing" @click="handleSync">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
            同步目录
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>
    <NLayoutContent>
      <div class="content-wrapper">
        <p class="activity-hint">活动与照片库的子目录一一对应，修改活动名会同时修改目录名。时间和备注可单独编辑。</p>
        <div class="column">
          <div class="column-title">
            <NIcon><CalendarOutline /></NIcon>
            <span>拍摄活动</span>
            <NTag size="small" type="info">{{ events.length }}</NTag>
          </div>
          <div v-if="eventsLoading" class="column-state"><NSpin size="large" /></div>
          <NEmpty v-else-if="eventsError" class="column-state" :description="eventsError" />
          <NEmpty v-else-if="events.length === 0" class="column-state"
            description="暂无活动目录，可导入照片或新建活动" />
          <div v-else class="event-list">
            <NTable size="small" :bordered="false" class="event-table">
              <thead><tr><th>时间</th><th>活动</th><th>照片</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="event in events" :key="event.id" class="event-item">
                  <td class="event-date">{{ displayDate(event.date) }}</td>
                  <td class="event-body">
                    <div class="event-name" :title="event.event">{{ event.event }}</div>
                    <div v-if="event.note" class="event-note" :title="event.note">{{ event.note }}</div>
                  </td>
                  <td><NTag size="small" :type="event.photo_count > 0 ? 'success' : 'default'">{{ event.photo_count }} 张</NTag></td>
                  <td class="event-actions">
                    <div class="event-meta">
                      <NButton size="small" secondary @click="router.push({ path: '/photos', query: { activity: event.event } })">
                        查看图片
                      </NButton>
                      <NButton size="small" quaternary aria-label="编辑活动" @click="openEdit(event)">
                        <template #icon><NIcon><CreateOutline /></NIcon></template>
                      </NButton>
                      <NPopconfirm @positive-click="handleDelete(event)">
                        <template #trigger>
                          <NButton size="small" quaternary type="error" aria-label="删除空活动目录" :disabled="event.photo_count > 0">
                            <template #icon><NIcon><TrashOutline /></NIcon></template>
                          </NButton>
                        </template>
                        删除空活动目录「{{ event.event }}」及其时间、备注？非空目录无法删除。
                      </NPopconfirm>
                    </div>
                  </td>
                </tr>
              </tbody>
            </NTable>
          </div>
        </div>
      </div>
    </NLayoutContent>
  </NLayout>
  <NModal v-model:show="showEditModal" preset="card"
    :title="editingId ? '编辑活动' : '新建活动'" style="width: 480px; max-width: calc(100vw - 32px)">
    <NForm label-placement="top">
      <NFormItem label="活动目录名" required>
        <NInput v-model:value="formEvent" placeholder="如：202608-山西旅游" maxlength="180" />
      </NFormItem>
      <NFormItem label="活动时间">
        <NDatePicker v-model:value="formDate" type="datetime" clearable style="width: 100%" />
      </NFormItem>
      <NFormItem label="备注">
        <NInput v-model:value="formNote" type="textarea" :rows="3" placeholder="可选" />
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
.event-list { overflow-x: auto; }
.event-table { width: max-content; max-width: 100%; }
.event-table :deep(th), .event-table :deep(td) { vertical-align: middle; }
.event-date { font-size: 13px; color: var(--n-text-color-3); white-space: nowrap; }
.event-name { font-size: 14px; font-weight: 500; }
.event-name, .event-note { max-width: 32rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.event-note { margin-top: 4px; font-size: 12px; color: var(--n-text-color-3); }
.event-meta { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.activity-hint { margin: 0; font-size: 13px; color: var(--n-text-color-3); }
@media (max-width: 640px) {
  .content-wrapper { padding: 16px; }
  .toolbar { padding: 0 16px; }
}
</style>
