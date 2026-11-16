import { getWailsApp } from './wails'

export type ImportDecision = 'pending' | 'kept' | 'favorite' | 'discarded' | 'later'
export type ImportSourceRole = 'local' | 'retained' | 'favorite' | 'starting'
export type ImportStep = 'review' | 'reject' | 'archive' | 'keep' | 'finish' | 'done'

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
  staged_server?: string
  stage_error?: string
  upload?: ImportUpload
}

interface ImportUpload {
  root: string
  target: string
  nef_target?: string
  jpg_ready: boolean
  jpg_staged?: boolean
  photo_id?: string
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
  destination?: string
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

export interface ImportSummary {
  id: string
  activity: string
  name: string
  step?: ImportStep | 'abandoning' | 'abandoned'
}

export interface ImportBatch extends ImportSummary {
  sources: ImportSource[]
  complete: boolean
  entries: ImportEntry[]
  issues: string[]
  undo?: unknown[]
  recycling?: ImportRecycleGroup[]
  bursts?: { server: string; fine: string[][]; coarse: string[][] }
}

export interface ImportBurstProgress {
  batch_id: string
  done: number
  total: number
  failed: number
  message: string
}

interface ImportBatchApp {
  ChooseImportSource(): Promise<string>
  ChooseImportRecycleDirectory(): Promise<string>
  ListImportBatches(): Promise<ImportSummary[]>
  GetImportBatch(id: string): Promise<ImportBatch>
  ScanImportBatch(id: string, activity: string, sources: ImportSource[], complete: boolean): Promise<ImportBatch>
  DecideImportBatch(id: string, entries: string[], decision: ImportDecision): Promise<ImportBatch>
  UndoImportBatch(id: string): Promise<ImportBatch>
  ResolveImportPair(id: string, entry: string, nefPath: string): Promise<ImportBatch>
  SetImportShotAt(id: string, entry: string, shotAt: string): Promise<ImportBatch>
  StageImportJPGs(id: string, server: string): Promise<ImportBatch>
  GroupImportBatch(id: string, server: string): Promise<ImportBatch>
  CancelImportBursts(): Promise<void>
  AdvanceImportBatch(id: string, next: ImportStep, leaveLocal: boolean): Promise<ImportBatch>
  FinishImportBatch(id: string): Promise<ImportBatch>
  AbandonImportBatch(id: string): Promise<void>
  PreviewImportUploads(id: string, server: string): Promise<ImportPlan[]>
  UploadImportBatch(id: string, server: string, plans: ImportPlan[]): Promise<ImportBatch>
  PreviewImportRecycle(id: string, kind: string): Promise<ImportRecycleFile[]>
  RecycleImportFiles(id: string, kind: string, paths: string[], parent: string): Promise<ImportBatch>
}

export const getImportBatchApp = () => getWailsApp<ImportBatchApp>()
