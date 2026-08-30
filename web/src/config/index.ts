// API 地址和上传配置常量

import { isWails } from '../utils/env'
import { settings } from '../stores/settings'
export { DEFAULT_AGENT_URL, DEFAULT_BACKEND_URL } from './runtime'

// ── 动态 API 地址 ──────────────────────────────────────────
// 在 Wails 桌面环境中读取用户配置的绝对地址，浏览器中保持相对路径（走 Vite 代理）

export function getApiBase(): string {
  if (isWails()) return `${settings.backendUrl}/api/v1`
  return '/api/v1'
}

export function getAgentBase(): string {
  if (isWails()) return `${settings.agentUrl}/api`
  return '/api'
}

// 保留旧常量供兼容（逐步迁移后可移除）
/** @deprecated 使用 getApiBase() 替代 */
export const API_BASE = '/api/v1'
/** @deprecated 使用 getAgentBase() 替代 */
export const AGENT_BASE = '/api'

// ── 静态配置 ──────────────────────────────────────────────

// VLM 队列轮询间隔（ms）
export const VLM_POLL_INTERVAL = 1500

// Embed 队列轮询间隔（ms）
export const EMBED_POLL_INTERVAL = 2000

// 照片列表默认分页
export const DEFAULT_PAGE_SIZE = 24
