import { getApiBase } from '../config'
import type { ImportDecision } from './importBatch'

export interface ReviewEntry {
  id: string
  name: string
  sha256: string
  shot_at?: string
  decision: ImportDecision
  origin: string
}
export interface ReviewBatch {
  batch_id: string
  name: string
  activity: string
  state: 'review' | 'locked'
  revision: number
  updated_at: string
  entries: ReviewEntry[]
  fine?: string[][]
  coarse?: string[][]
}
export interface ReviewSummary {
  batch_id: string
  name: string
  state: ReviewBatch['state']
  updated_at: string
  count: number
}
export interface ReviewChange { id: string; decision: ImportDecision }

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${getApiBase()}/photo-import/${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`)
  return data as T
}
export const listImportReviews = () => request<ReviewSummary[]>('review/list')
export const getImportReview = (id: string) => request<ReviewBatch>(`review?batch_id=${encodeURIComponent(id)}`)
export const editImportReview = (id: string, changes: ReviewChange[]) =>
  request<ReviewBatch>('review/edit', { batch_id: id, changes })
export function reviewImageURL(batchID: string, entry: ReviewEntry, thumbnail = false) {
  const query = new URLSearchParams({ batch_id: batchID, sha256: entry.sha256 })
  if (thumbnail) query.set('size', 'thumbnail')
  return `${getApiBase()}/photo-import/stage/image?${query}`
}
export function importReviewLink(base: string, id: string): string {
  try {
    const url = new URL(base)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    url.hash = `/import?batch=${encodeURIComponent(id)}`
    return url.toString()
  } catch { return '' }
}
