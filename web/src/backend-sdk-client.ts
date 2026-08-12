/**
 * Go Backend SDK 共享实例。
 *
 * 统一管理 SDK Configuration 和各 API 实例，避免各处重复创建。
 * web 前端通过 vite proxy 转发 /api/v1 到 Go 后端，basePath 设为空。
 * Wails 桌面环境使用用户配置的绝对地址。
 */

import { isWails } from './utils/env'
import { Configuration } from '../backend-sdk/configuration'
import {
  PhotoServiceApi,
  QueryServiceApi,
  TagServiceApi,
  TimelineServiceApi,
  VlmServiceApi,
} from '../backend-sdk/api'
import type { FetchAPI } from '../backend-sdk/api'

function getBasePath(): string {
  if (!isWails()) return ''
  try {
    const raw = localStorage.getItem('photo-agent-settings')
    if (raw) {
      const { backendUrl } = JSON.parse(raw)
      if (backendUrl) return backendUrl
    }
  } catch {}
  return 'http://localhost:10004'
}

// SDK 生成的 BaseAPI 默认 basePath 是 "http://127.0.0.1:8080"，
// 且构造时 `config.basePath || this.basePath` 会将空字符串 fallback 到默认值。
// 因此需要先构造再覆写为正确值。
function createApi<T>(Ctor: new (config: Configuration, basePath?: string, fetch?: FetchAPI) => T): T {
  const config = new Configuration({ basePath: '/' })
  // 显式传入原生 fetch，避免 isomorphic-fetch 在 Vite CJS 互操作下解析为非函数对象
  const api = new Ctor(config, undefined, globalThis.fetch.bind(globalThis))
  // basePath 在 BaseAPI 中是 protected，生成代码无法直接访问，用 any 绕过
  ;(api as any).basePath = getBasePath()
  return api
}

export const photoApi = createApi(PhotoServiceApi)
export const queryApi = createApi(QueryServiceApi)
export const tagApi = createApi(TagServiceApi)
export const timelineApi = createApi(TimelineServiceApi)
export const vlmApi = createApi(VlmServiceApi)
