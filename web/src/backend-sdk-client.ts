/**
 * Go Backend SDK 共享实例。
 *
 * 统一管理 SDK Configuration 和各 API 实例，避免各处重复创建。
 * web 前端通过 vite proxy 转发 /api/v1 到 Go 后端，basePath 设为空。
 */

import { Configuration } from '../backend-sdk/configuration'
import {
  PhotoServiceApi,
  QueryServiceApi,
  TagServiceApi,
  TimelineServiceApi,
  VlmServiceApi,
} from '../backend-sdk/api'

// SDK 生成的 BaseAPI 默认 basePath 是 "http://127.0.0.1:8080"，
// 且构造时 `config.basePath || this.basePath` 会将空字符串 fallback 到默认值。
// 因此需要先构造再覆写为正确值。
function createApi<T>(Ctor: new (config: Configuration) => T): T {
  const config = new Configuration({ basePath: '/' })
  const api = new Ctor(config)
  // web 端使用相对路径，由 vite proxy 转发
  // basePath 在 BaseAPI 中是 protected，生成代码无法直接访问，用 any 绕过
  ;(api as any).basePath = ''
  return api
}

export const photoApi = createApi(PhotoServiceApi)
export const queryApi = createApi(QueryServiceApi)
export const tagApi = createApi(TagServiceApi)
export const timelineApi = createApi(TimelineServiceApi)
export const vlmApi = createApi(VlmServiceApi)
