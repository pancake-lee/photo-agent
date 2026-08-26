export interface DirRow {
  name: string
  state: 'created' | 'existed' | 'failed'
  stateText: string
  count: number
  latest: string
}

export interface CleanupAdviceRow {
  dir: string
  ok: boolean
  tip: string
}
