import { getWailsApp } from './wails'

export type ImportDecision = 'pending' | 'kept' | 'favorite' | 'discarded' | 'later'
export type ImportSourceRole = 'local' | 'retained' | 'favorite' | 'starting'

export interface ImportSource {
  path: string
  role: ImportSourceRole
}

interface ImportFile {
  path: string
  sha256: string
  size: number
}

export interface ImportEntry {
  id: string
  jpg?: ImportFile
  nef?: ImportFile
  nef_candidates?: ImportFile[]
  pair: 'paired' | 'jpg_only' | 'review' | 'manual' | 'nef_only'
  decision: ImportDecision
  origin: 'pending' | 'ipad' | 'manual'
  inherited?: ImportDecision
  conflict?: boolean
  historical?: boolean
  reference_only?: boolean
  missing_from_export?: boolean
  shot_at?: string
  score?: { rating: number; rank: number; tier: string; why: string; cluster: string }
  upload?: ImportUpload
}

interface ImportUpload {
  root: string
  target: string
  nef_target?: string
  jpg_ready: boolean
  nef_ready: boolean
  verified: boolean
  error?: string
}

export interface ImportPlan {
  entry_id: string
  jpg: string
  nef?: string
  plan: ImportUpload
}

interface ImportRecycleFile {
  source: string
  restored_to?: string
  status: string
  error?: string
}

interface ImportRecycleGroup {
  directory: string
  kind: string
  status: string
  files: ImportRecycleFile[]
  error?: string
}

interface ImportSummary {
  id: string
  activity: string
}

export interface ImportBatch extends ImportSummary {
  sources: ImportSource[]
  reviewed: boolean
  complete: boolean
  entries: ImportEntry[]
  issues: string[]
  undo?: unknown[]
  recycling?: ImportRecycleGroup[]
}

export interface ImportCullProgress {
  batch_id: string
  done: number
  total: number
  failed: number
  message: string
}

interface ImportBatchApp {
  ChooseImportSource(): Promise<string>
  ListImportBatches(): Promise<ImportSummary[]>
  GetImportBatch(id: string): Promise<ImportBatch>
  ScanImportBatch(id: string, activity: string, sources: ImportSource[], reviewed: boolean, complete: boolean): Promise<ImportBatch>
  DecideImportBatch(id: string, entries: string[], decision: ImportDecision, pendingOnly: boolean): Promise<ImportBatch>
  UndoImportBatch(id: string): Promise<ImportBatch>
  ResolveImportPair(id: string, entry: string, nefPath: string): Promise<ImportBatch>
  SetImportShotAt(id: string, entry: string, shotAt: string): Promise<ImportBatch>
  AnalyzeImportBatch(id: string, executable: string, scene: string): Promise<ImportBatch>
  CancelImportCull(): Promise<void>
  ClearImportCull(id: string): Promise<ImportBatch>
  PreviewImportUploads(id: string, server: string): Promise<ImportPlan[]>
  UploadImportBatch(id: string, server: string, plans: ImportPlan[]): Promise<ImportBatch>
  PreviewImportRecycle(id: string, kind: string): Promise<ImportRecycleFile[]>
  RecycleImportFiles(id: string, kind: string, paths: string[], permanent: boolean): Promise<ImportBatch>
  RestoreImportDirectory(id: string, directory: string): Promise<ImportBatch>
}

export const getImportBatchApp = () => getWailsApp<ImportBatchApp>()
