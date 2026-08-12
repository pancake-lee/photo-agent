<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NLayoutContent,
  NLayoutHeader,
  NForm,
  NFormItem,
  NInput,
  NButton,
  NSpace,
  NIcon,
  NCard,
  useMessage,
} from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { settings, resetSettings } from '../stores/settings'
import { isWails } from '../utils/env'

const message = useMessage()

// 本地编辑副本（回车失焦即时保存，无需额外提交按钮）
const localBackendUrl = ref(settings.backendUrl)
const localAgentUrl = ref(settings.agentUrl)

onMounted(() => {
  localBackendUrl.value = settings.backendUrl
  localAgentUrl.value = settings.agentUrl
})

function saveBackend() {
  settings.backendUrl = localBackendUrl.value || 'http://localhost:10004'
  message.success('Backend 地址已保存')
}

function saveAgent() {
  settings.agentUrl = localAgentUrl.value || 'http://localhost:10005'
  message.success('Agent 地址已保存')
}

function handleReset() {
  resetSettings()
  localBackendUrl.value = settings.backendUrl
  localAgentUrl.value = settings.agentUrl
  message.success('已恢复默认地址')
}
</script>

<template>
  <NLayoutContent>
    <NLayoutHeader bordered>
      <div class="page-header">
        <h2 class="page-title">设置</h2>
      </div>
    </NLayoutHeader>

    <NLayoutContent class="page-body">
      <div class="settings-container">
        <!-- 环境提示 -->
        <NCard v-if="!isWails()" title="运行环境" size="small" class="env-card">
          <p class="env-note">
            🖥️ 当前在浏览器中运行，使用 Vite 代理转发请求，无需配置服务地址。
            切换到 Wails 桌面应用后，以下设置会生效。
          </p>
        </NCard>

        <NCard title="服务地址" size="small" class="service-card">
          <NForm label-placement="top" :show-feedback="false">
            <NFormItem label="Backend 服务地址（Go）">
              <NSpace align="center">
                <NInput
                  v-model:value="localBackendUrl"
                  placeholder="http://localhost:10004"
                  style="width: 360px"
                  @blur="saveBackend"
                  @keyup.enter="saveBackend"
                />
                <span class="hint">提供照片管理 API（/api/v1/*）</span>
              </NSpace>
            </NFormItem>

            <NFormItem label="Agent 服务地址（Python）">
              <NSpace align="center">
                <NInput
                  v-model:value="localAgentUrl"
                  placeholder="http://localhost:10005"
                  style="width: 360px"
                  @blur="saveAgent"
                  @keyup.enter="saveAgent"
                />
                <span class="hint">提供 AI 推理 API（/api/chat, /api/embed 等）</span>
              </NSpace>
            </NFormItem>

            <NFormItem>
              <NButton secondary size="small" @click="handleReset">
                <template #icon>
                  <NIcon size="14"><RefreshOutline /></NIcon>
                </template>
                恢复默认
              </NButton>
            </NFormItem>
          </NForm>
        </NCard>

        <NCard title="当前配置摘要" size="small" class="summary-card">
          <div class="summary-row">
            <span class="summary-label">Backend：</span>
            <code>{{ settings.backendUrl }}</code>
          </div>
          <div class="summary-row">
            <span class="summary-label">Agent：</span>
            <code>{{ settings.agentUrl }}</code>
          </div>
        </NCard>
      </div>
    </NLayoutContent>
  </NLayoutContent>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  padding: 16px 24px;
}
.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.page-body {
  padding: 24px;
}
.settings-container {
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.env-note {
  margin: 0;
  color: var(--n-text-color-3);
  font-size: 13px;
  line-height: 1.6;
}
.hint {
  font-size: 12px;
  color: var(--n-text-color-3);
  white-space: nowrap;
}
.summary-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}
.summary-label {
  font-weight: 500;
  min-width: 72px;
}
code {
  background: var(--n-color-embedded);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
</style>
