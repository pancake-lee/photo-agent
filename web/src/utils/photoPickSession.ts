/**
 * photoPickSession — 跨页面选图会话（sessionStorage 持久化）
 *
 * 发起方（如黄金用例新建弹窗）在打开选图覆盖层前写入会话：
 * 已选照片（含扩展字段如粒度）+ 发起方草稿。覆盖层「完成选择」后把
 * 新的选择写回，发起方读取并清理。F5 刷新后会话仍在，页面重建时可恢复。
 *
 * 协议见 docs/design/2026-08-26-1-photo-pick-overlay.md 第 3.3 节。
 */

/** 覆盖层回传的选中照片：photo_id 去后缀文件名，与评估匹配口径一致 */
export interface PickedPhoto {
  photo_id: string
  filename: string
  uuid: string
}

/** 会话里的已选照片：发起方可带扩展字段（如 granularity） */
export type SessionPickedPhoto = PickedPhoto & Record<string, unknown>

/** 会话结构。draft 由发起方自定义（如表单草稿），覆盖层不解释 */
export interface PhotoPickSession<TDraft = unknown> {
  /** 发起方标识（如 golden-create），用于刷新恢复时校验归属 */
  source: string
  /** 已选照片（含发起方扩展字段，如 granularity） */
  selected: SessionPickedPhoto[]
  /** 完成标记：覆盖层写回结果时置 true，发起方据此区分「进行中/已完成」 */
  done?: boolean
  draft?: TDraft
}

const STORAGE_KEY = 'photo-pick-session'

function readRaw(): PhotoPickSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || typeof parsed.source !== 'string') return null
    return parsed as PhotoPickSession
  } catch {
    return null
  }
}

/** 发起选图：写入会话（覆盖旧会话） */
export function createPickSession(session: PhotoPickSession): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

/** 读取会话；source 不匹配时返回 null */
export function readPickSession<TDraft = unknown>(source: string): PhotoPickSession<TDraft> | null {
  const raw = readRaw()
  return raw && raw.source === source ? (raw as PhotoPickSession<TDraft>) : null
}

/** 覆盖层完成选择：把结果写回会话并置 done 标记 */
export function completePickSession(selected: PickedPhoto[]): void {
  const raw = readRaw()
  if (!raw) return
  raw.selected = selected.map((p) => ({ ...p }))
  raw.done = true
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(raw))
}

/** 清理会话（发起方读取结果后 / 覆盖层取消时调用） */
export function clearPickSession(): void {
  sessionStorage.removeItem(STORAGE_KEY)
}
