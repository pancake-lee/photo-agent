/**
 * 日期格式化工具函数。
 */

/** 将 ISO 字符串或 Date 格式化为 zh-CN 可读字符串 */
export function formatDate(date: string | Date): string {
  return new Date(date).toLocaleString('zh-CN')
}

/** 将 ISO 字符串格式化为仅日期部分 (YYYY/MM/DD) */
export function formatDateOnly(date: string | Date): string {
  return new Date(date).toLocaleDateString('zh-CN')
}
