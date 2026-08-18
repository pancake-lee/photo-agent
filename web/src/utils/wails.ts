/**
 * Wails 客户端 Go 绑定访问层。
 *
 * 在 Wails WebView 中，客户端 Go 层通过 `window.go.main.App` 暴露方法。
 * 本模块定义返回类型（对应 client/import.go 与 client/sync.go 的结构体 JSON 字段），
 * 并封装调用，统一处理「非 Wails 环境」的错误提示。
 */

import { isWails } from './env'

// ------------------------------------------------------------------ #
// 类型定义（对应客户端 Go 结构体的 json 字段）
// ------------------------------------------------------------------ #

export interface StagingDir {
  name: string
  path: string
  status: 'created' | 'existed' | 'failed'
}

export interface CreateStagingResult {
  staging_path: string
  dirs: StagingDir[]
}

export interface FileInfo {
  name: string
  size: number
  mod_time: number
  shot_time?: number
}

export interface DirFileList {
  dir: string
  count: number
  files: FileInfo[]
}

export interface StagingScan {
  staging_path: string
  full: DirFileList
  like: DirFileList
  nef: DirFileList
}

export interface NefDecision {
  name: string
  shot_at?: string
}

export interface JpgRef {
  name: string
  path: string
  dir: string
}

export interface OutlierFile {
  name: string
  shot_at: string
}

export interface TimeRange {
  min?: string
  max?: string
}

export interface ImportAnalysis {
  full_jpg_count: number
  like_jpg_count: number
  nef_count: number
  favorite_count: number
  retained_count: number
  discarded_count: number
  migrated_count: number
  favorite_list: NefDecision[]
  missing_nef: JpgRef[]
  time_range: TimeRange
  outliers: OutlierFile[]
  no_date: JpgRef[]
}

export interface MigrateFailure {
  name: string
  reason: string
}

export interface MigrateResult {
  migrated_count: number
  migrated: string[]
  failed: MigrateFailure[]
}

export interface StorageInfo {
  root: string
  jpg_count: number
  nef_count: number
  months: string[]
  activities: string[]
  last_sync: string
  warning?: string
}

export interface SyncFileResult {
  name: string
  status: 'stored' | 'conflict' | 'skipped' | 'failed'
  error?: string
}

export interface SyncResult {
  total: number
  succeeded: number
  skipped: number
  failed: number
  elapsed_ms: number
  files: SyncFileResult[]
}

export interface SyncProgress {
  completed: number
  total: number
  name: string
  status: string
}

export interface ConflictCheck {
  total: number
  existing: string[]
  new: string[]
}

// ------------------------------------------------------------------ #
// Wails App 绑定接口
// ------------------------------------------------------------------ #

interface WailsApp {
  ChooseDirectory(): Promise<string>
  CreateStagingDirs(stagingPath: string, folderName: string): Promise<CreateStagingResult>
  ScanStaging(stagingPath: string, folderName: string): Promise<StagingScan>
  AnalyzeStaging(stagingPath: string, folderName: string): Promise<ImportAnalysis>
  MigrateKeptNef(stagingPath: string, folderName: string, keepList: string[]): Promise<MigrateResult>
  PreviewImage(path: string): Promise<string>
  GetStorageInfo(serverURL: string): Promise<StorageInfo>
  CheckConflicts(stagingPath: string, folderName: string, serverURL: string): Promise<ConflictCheck>
  SyncToServer(stagingPath: string, folderName: string, serverURL: string, resolution: string): Promise<SyncResult>
  Log(msg: string): Promise<void>
}

function getApp(): WailsApp {
  const w = window as any
  const app = w.go?.main?.App
  if (!app) {
    throw new Error('Wails 桌面环境未就绪')
  }
  return app as WailsApp
}

/** 统一提取 Wails 绑定异常的可读信息。 */
export function wailsError(e: unknown): string {
  if (typeof e === 'string') return e
  if (e instanceof Error) return e.message
  return String(e)
}

export const wailsApi = {
  chooseDirectory(): Promise<string> {
    return getApp().ChooseDirectory()
  },
  createStagingDirs(stagingPath: string, folderName: string): Promise<CreateStagingResult> {
    return getApp().CreateStagingDirs(stagingPath, folderName)
  },
  scanStaging(stagingPath: string, folderName: string): Promise<StagingScan> {
    return getApp().ScanStaging(stagingPath, folderName)
  },
  analyzeStaging(stagingPath: string, folderName: string): Promise<ImportAnalysis> {
    return getApp().AnalyzeStaging(stagingPath, folderName)
  },
  migrateKeptNef(stagingPath: string, folderName: string, keepList: string[]): Promise<MigrateResult> {
    return getApp().MigrateKeptNef(stagingPath, folderName, keepList)
  },
  previewImage(path: string): Promise<string> {
    return getApp().PreviewImage(path)
  },
  getStorageInfo(serverURL: string): Promise<StorageInfo> {
    return getApp().GetStorageInfo(serverURL)
  },
  checkConflicts(stagingPath: string, folderName: string, serverURL: string): Promise<ConflictCheck> {
    return getApp().CheckConflicts(stagingPath, folderName, serverURL)
  },
  syncToServer(stagingPath: string, folderName: string, serverURL: string, resolution: string): Promise<SyncResult> {
    return getApp().SyncToServer(stagingPath, folderName, serverURL, resolution)
  },
  /** 写入客户端日志文件（Go 层 Log 绑定），用于排查前端调用链路。非 Wails 环境降级为 console.log。 */
  log(msg: string): void {
    const app = (window as any).go?.main?.App
    if (app?.Log) {
      app.Log(msg)
    } else {
      console.log('[wails-log]', msg)
    }
  },
}

/**
 * 订阅客户端上传进度事件（对应 Go 侧 runtime.EventsEmit("sync:progress", …)）。
 * 返回取消订阅函数；非 Wails 环境返回 no-op。
 */
export function onSyncProgress(cb: (p: SyncProgress) => void): () => void {
  const runtime = (window as any).runtime
  if (runtime?.EventsOn) {
    return runtime.EventsOn('sync:progress', cb)
  }
  return () => {}
}

export { isWails }
