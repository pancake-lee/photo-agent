<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NLayout, NLayoutContent, NLayoutHeader,
  NButton, NTag, NEmpty, NSpin, NPopconfirm, NIcon, NSpace, useMessage,
} from 'naive-ui'
import { FolderOpenOutline, AddOutline } from '@vicons/ionicons5'
import { getApiBase } from '../config'
import { formatDate } from '../utils/format'

const router = useRouter()
const message = useMessage()

interface DraftItem {
  id: string
  title: string
  content: string
  photo_ids: string[]
  style: string
  source: string
  status: string
  created_at: string
  updated_at: string
}

const drafts = ref<DraftItem[]>([])
const isLoading = ref(true)

onMounted(() => fetchDrafts())

function imageUrl(id: string): string {
  return id ? `${getApiBase()}/photos/${id}/image` : ''
}

// 草稿 photo_ids 中连拍组以 g:<组id>:<封面id> 标记，缩略图展示其封面（最后一段为封面 id）
function thumbPhotoId(pid: string): string {
  if (!pid.startsWith('g:')) return pid
  const parts = pid.slice(2).split(':')
  return parts[parts.length - 1] || ''
}

async function fetchDrafts() {
  isLoading.value = true
  try {
    const resp = await fetch(`${getApiBase()}/drafts`)
    if (!resp.ok) throw new Error('加载失败')
    const data = await resp.json()
    drafts.value = data.items || []
  } catch (e: any) {
    message.error(e.message || '加载草稿列表失败')
  } finally {
    isLoading.value = false
  }
}

function goEdit(draft: DraftItem) {
  router.push(`/post-studio?draft_id=${draft.id}`)
}

async function deleteDraft(id: string) {
  try {
    const resp = await fetch(`${getApiBase()}/drafts/${id}`, { method: 'DELETE' })
    if (!resp.ok) throw new Error('删除失败')
    message.success('已删除')
    fetchDrafts()
  } catch (e: any) {
    message.error(e.message || '删除失败')
  }
}

async function toggleStatus(draft: DraftItem) {
  const newStatus = draft.status === 'draft' ? 'published' : 'draft'
  try {
    const resp = await fetch(`${getApiBase()}/drafts/${draft.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    })
    if (!resp.ok) throw new Error('更新失败')
    message.success(newStatus === 'published' ? '已标记为已发布' : '已标记为草稿')
    fetchDrafts()
  } catch (e: any) {
    message.error(e.message || '更新失败')
  }
}

function sourceLabel(source: string): string {
  const map: Record<string, string> = {
    topic: '主题发现',
    self_select: '自选图片',
  }
  return map[source] || source || '—'
}

function styleLabel(style: string): string {
  const map: Record<string, string> = {
    literary: '文艺',
    documentary: '纪实',
    casual: '轻松',
    guide: '攻略',
  }
  return map[style] || style || '—'
}
</script>

<template>
  <NLayout>
    <NLayoutHeader bordered>
      <div class="page-header">
        <div class="page-header-left">
          <NIcon size="20"><FolderOpenOutline /></NIcon>
          <h3 class="page-title">草稿管理</h3>
          <NTag v-if="drafts.length" :bordered="false" size="small">
            {{ drafts.length }} 条
          </NTag>
        </div>
        <NSpace>
          <NButton size="small" type="primary" @click="router.push('/post-studio')">
            <template #icon><NIcon><AddOutline /></NIcon></template>
            新建草稿
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <NLayoutContent>
      <div class="page-content">
        <NSpin :show="isLoading">
          <div v-if="drafts.length === 0 && !isLoading" class="empty-state">
            <NEmpty description="暂无草稿">
              <template #extra>
                <NButton size="small" type="primary" @click="router.push('/post-studio')">创建第一篇</NButton>
              </template>
            </NEmpty>
          </div>

          <div v-else class="draft-list">
            <div
              v-for="d in drafts"
              :key="d.id"
              class="draft-card"
            >
              <div class="draft-main">
                <span class="draft-title" @click="goEdit(d)">{{ d.title || '无标题' }}</span>
                <div class="draft-meta">
                  <NTag :type="d.status === 'published' ? 'success' : 'default'" size="small" round :bordered="false">
                    {{ d.status === 'published' ? '已发布' : '草稿' }}
                  </NTag>
                  <NTag size="small" round :bordered="false">{{ sourceLabel(d.source) }}</NTag>
                  <NTag v-if="d.style" size="small" round :bordered="false">{{ styleLabel(d.style) }}</NTag>
                  <span class="draft-time">{{ formatDate(d.updated_at) }}</span>
                </div>
                <p class="draft-preview">{{ d.content || '暂无内容' }}</p>

                <div v-if="d.photo_ids?.length" class="draft-photos">
                  <img
                    v-for="pid in d.photo_ids.slice(0, 6)"
                    :key="pid"
                    :src="imageUrl(thumbPhotoId(pid))"
                    class="draft-photo-thumb"
                    :title="thumbPhotoId(pid)"
                  />
                  <span v-if="d.photo_ids.length > 6" class="photo-rest">+{{ d.photo_ids.length - 6 }}</span>
                </div>
              </div>

              <div class="draft-actions">
                <NButton size="small" @click="goEdit(d)">编辑</NButton>
                <NButton size="small" @click="toggleStatus(d)">
                  {{ d.status === 'published' ? '转为草稿' : '标记已发布' }}
                </NButton>
                <NPopconfirm @positive-click="deleteDraft(d.id)">
                  <template #trigger>
                    <NButton size="small" type="error" quaternary>删除</NButton>
                  </template>
                  确定删除此草稿？
                </NPopconfirm>
              </div>
            </div>
          </div>
        </NSpin>
      </div>
    </NLayoutContent>
  </NLayout>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.page-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.page-title {
  margin: 0;
  font-size: 16px;
}

.page-content {
  padding: 16px 24px;
  max-width: 960px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 320px;
}

.draft-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.draft-card {
  display: flex;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.draft-card:hover {
  border-color: var(--n-color-primary);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.draft-main {
  flex: 1;
  min-width: 0;
}

.draft-title {
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  color: var(--n-text-color);
}
.draft-title:hover { color: var(--n-color-primary); }

.draft-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.draft-time {
  font-size: 12px;
  color: var(--n-text-color-3);
}

.draft-preview {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--n-text-color-2);
  line-height: 1.6;
  /* 正文完整展示，超过 10 行折断并在末尾显示省略号 */
  white-space: pre-wrap;
  word-break: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 10;
  -webkit-box-orient: vertical;
}

.draft-photos {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.draft-photo-thumb {
  width: 44px;
  height: 44px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--n-border-color);
}
.photo-rest {
  font-size: 12px;
  color: var(--n-text-color-3);
}

.draft-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  align-items: stretch;
}
</style>
