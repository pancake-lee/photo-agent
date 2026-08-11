/**
 * Detect the runtime environment: Wails desktop app or browser.
 * In Wails WebView, the Go backend injects `window.go.main.App`.
 */
export function isWails(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as any
  return !!(w.go?.main?.App)
}

/** Expose the check as a global for use in templates that can't import TS. */
if (typeof window !== 'undefined') {
  ;(window as any).__IS_WAILS__ = isWails()
}
