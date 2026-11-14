<script setup lang="ts">
import { ref, watch } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import { getApiBase } from '../config'

const props = defineProps<{ id: string }>()
const favorite = ref<boolean>()
const saving = ref(false)
const message = useMessage()

async function load(id: string, value?: boolean) {
  const response = await fetch(`${getApiBase()}/photos/${encodeURIComponent(id)}/favorite`, {
    method: value === undefined ? 'GET' : 'POST',
    headers: value === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: value === undefined ? undefined : JSON.stringify({ favorite: value }),
    cache: 'no-store',
  })
  const data = await response.json()
  if (!response.ok || typeof data.favorite !== 'boolean') throw new Error(data.error || '无法读取收藏状态')
  if (id === props.id) favorite.value = data.favorite
}

watch(() => props.id, (id) => {
  favorite.value = undefined
  if (!id) return
  void load(id).catch((error: Error) => message.error(error.message))
}, { immediate: true })

async function toggle() {
  if (favorite.value === undefined || saving.value) return
  saving.value = true
  try { await load(props.id, !favorite.value) }
  catch (error) { message.error(error instanceof Error ? error.message : String(error)) }
  finally { saving.value = false }
}
</script>

<template>
  <NButton size="small" :type="favorite ? 'warning' : 'default'" :disabled="favorite === undefined" :loading="saving" @click="toggle">
    {{ favorite ? '取消收藏' : '收藏照片' }}
  </NButton>
</template>
