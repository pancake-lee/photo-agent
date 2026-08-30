<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
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
  NInputNumber,
  NDivider,
  useMessage,
} from 'naive-ui'
import { RefreshOutline, SaveOutline } from '@vicons/ionicons5'
import { settings, resetSettings } from '../stores/settings'
import { isWails } from '../utils/env'
import { DEFAULT_AGENT_URL, DEFAULT_BACKEND_URL } from '../config/runtime'
import { useBurstGroups } from '../composables/useBurstGroups'
import type { BurstProfileConfig } from '../types/photo'

const message = useMessage()

// 本地编辑副本（回车失焦即时保存，无需额外提交按钮）
const localBackendUrl = ref(settings.backendUrl)
const localAgentUrl = ref(settings.agentUrl)

// ── 连拍分组两档阈值 ──
const { fetchConfig, saveConfig } = useBurstGroups()

const burstConfig = reactive<{ fine: BurstProfileConfig; coarse: BurstProfileConfig }>({
  fine: { time_window_sec: 5, hash_threshold: 10, ssim_threshold: 0.85, ssim_gray_min: 8, ssim_gray_max: 12 },
  coarse: { time_window_sec: 30, hash_threshold: 18, ssim_threshold: 0.6, ssim_gray_min: 12, ssim_gray_max: 24 },
})

const burstSaving = ref(false)

interface FieldMeta {
  key: keyof BurstProfileConfig
  label: string
  hint: string
  min: number
  max: number
  step?: number
  precision?: number
}

const profileFields: FieldMeta[] = [
  { key: 'time_window_sec', label: '时间窗（秒）', hint: '相邻两张拍摄间隔超过此秒数则切分新组', min: 1, max: 3600 },
  { key: 'hash_threshold', label: '哈希阈值（0-64）', hint: 'dHash 汉明距离超过此值判定为不同场景', min: 0, max: 64 },
  { key: 'ssim_threshold', label: 'SSIM 阈值（0-1）', hint: '灰区二次验证，SSIM 低于此值判定为不同', min: 0, max: 1, step: 0.05, precision: 2 },
  { key: 'ssim_gray_min', label: '灰区下界', hint: '哈希距离进入此值才触发 SSIM 二次验证', min: 0, max: 64 },
  { key: 'ssim_gray_max', label: '灰区上界', hint: '哈希距离超过此值直接判定为不同', min: 0, max: 64 },
]

function updateField(profile: 'fine' | 'coarse', key: keyof BurstProfileConfig, v: number | null) {
  if (v == null) return
  burstConfig[profile][key] = v
}

async function loadBurstConfig() {
  try {
    const cfg = await fetchConfig()
    burstConfig.fine = cfg.fine
    burstConfig.coarse = cfg.coarse
  } catch (e) {
    message.error(e instanceof Error ? e.message : '读取连拍参数失败')
  }
}

async function handleSaveBurstConfig() {
  burstSaving.value = true
  try {
    await saveConfig({ ...burstConfig })
    message.success('连拍参数已保存，下次重算生效')
  } catch (e) {
    message.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    burstSaving.value = false
  }
}

onMounted(() => {
  localBackendUrl.value = settings.backendUrl
  localAgentUrl.value = settings.agentUrl
  loadBurstConfig()
})

function saveBackend() {
  settings.backendUrl = localBackendUrl.value || DEFAULT_BACKEND_URL
  message.success('Backend 地址已保存')
}

function saveAgent() {
  settings.agentUrl = localAgentUrl.value || DEFAULT_AGENT_URL
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

        <NCard title="连拍分组" size="small" class="burst-card">
          <p class="burst-hint">
            连拍分组分「精细」「模糊」两档，重算时一次产出两档结果。图片管理页用「展示」按钮循环切换三级显示。
            重算入口在图片管理页顶栏。
          </p>

          <!-- 精细档 -->
          <div class="burst-profile-title">精细档</div>
          <NForm label-placement="left" :show-feedback="false" label-width="168" size="small">
            <NFormItem
              v-for="f in profileFields"
              :key="`fine-${f.key}`"
              :label="f.label"
            >
              <div class="burst-field">
                <NInputNumber
                  :value="burstConfig.fine[f.key]"
                  :min="f.min"
                  :max="f.max"
                  :step="f.step ?? 1"
                  :precision="f.precision"
                  style="width: 160px"
                  @update:value="(v: number | null) => updateField('fine', f.key, v)"
                />
                <span class="burst-field-hint">{{ f.hint }}</span>
              </div>
            </NFormItem>
          </NForm>

          <NDivider />

          <!-- 模糊档 -->
          <div class="burst-profile-title">模糊档</div>
          <NForm label-placement="left" :show-feedback="false" label-width="168" size="small">
            <NFormItem
              v-for="f in profileFields"
              :key="`coarse-${f.key}`"
              :label="f.label"
            >
              <div class="burst-field">
                <NInputNumber
                  :value="burstConfig.coarse[f.key]"
                  :min="f.min"
                  :max="f.max"
                  :step="f.step ?? 1"
                  :precision="f.precision"
                  style="width: 160px"
                  @update:value="(v: number | null) => updateField('coarse', f.key, v)"
                />
                <span class="burst-field-hint">{{ f.hint }}</span>
              </div>
            </NFormItem>
          </NForm>

          <div class="burst-save-row">
            <NButton
              type="primary"
              size="small"
              :loading="burstSaving"
              @click="handleSaveBurstConfig"
            >
              <template #icon>
                <NIcon size="14"><SaveOutline /></NIcon>
              </template>
              保存参数
            </NButton>
          </div>
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
  max-width: 800px;
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
.burst-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--n-text-color-3);
  line-height: 1.6;
}
.burst-profile-title {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
}
.burst-field {
  display: flex;
  align-items: center;
  gap: 8px;
}
.burst-field-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
  line-height: 1.5;
}
.burst-save-row {
  margin-top: 12px;
}
</style>
