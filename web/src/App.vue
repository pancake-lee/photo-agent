<script setup lang="ts">
import { onMounted } from 'vue'
import {
  darkTheme,
  dateZhCN,
  zhCN,
  NConfigProvider,
  NMessageProvider,
  NLayout,
} from 'naive-ui'
import SideMenu from './components/SideMenu.vue'

// ── 桌面环境调试辅助 ──

onMounted(() => {
  // 1. 全局图片加载错误捕获
  window.addEventListener('error', (e) => {
    const target = e.target
    if (target instanceof HTMLImageElement) {
      console.error(
        `[图片加载失败] ${target.src}`,
        '\n  当前 API Base:', typeof window !== 'undefined' ? '[见 Network 面板]' : 'N/A'
      )
    }
  }, true)

  // 2. 右键任意位置弹出"检查"（含空白处）
  //    WebView2 在 mouseup→contextmenu 之间会清除临时选区。但如果是
  //    上一次点击留下的选区就不会被清。所以每次点击（含左键）都把 ghost
  //    放到点击位置并选中，下一次右键时 ghost 已经是"上个操作留下的选区"
  //    就不会被清了。
  let ghost: HTMLSpanElement | null = null

  function placeGhost(x: number, y: number) {
    if (ghost) ghost.remove()
    ghost = document.createElement('span')
    ghost.textContent = '​' // 零宽空格
    ghost.style.cssText =
      `position:fixed;left:${x}px;top:${y}px;` +
      'width:1px;height:1px;overflow:hidden;pointer-events:none;'
    document.body.appendChild(ghost)
    const sel = window.getSelection()
    if (!sel) return
    const range = document.createRange()
    range.selectNodeContents(ghost)
    sel.removeAllRanges()
    sel.addRange(range)
  }

  // 初始化：预置 ghost 在角落
  placeGhost(0, 0)

  // 每次 mousedown 时更新 ghost 位置并选中
  // 左键：只在无真实选区时介入，不影响用户拖选文字
  // 右键：始终介入，确保 contextmenu 时已有选区
  document.addEventListener('mousedown', (e) => {
    if (e.button === 2) {
      placeGhost(e.clientX, e.clientY)
    } else if (e.button === 0) {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed) {
        placeGhost(e.clientX, e.clientY)
      }
    }
  }, true)

  // contextmenu 时做最后一次兜底：如果选区被 WebView2 清了，再创建一次
  document.addEventListener('contextmenu', (e) => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed) {
      placeGhost(e.clientX, e.clientY)
    }
  }, true)
})
</script>

<template>
  <NConfigProvider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN">
    <NMessageProvider>
      <NLayout has-sider position="absolute">
        <SideMenu />
        <router-view />
      </NLayout>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
/* ── 全局滚动条（暗色主题） ── */

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.24);
}

::-webkit-scrollbar-corner {
  background: transparent;
}

/* Firefox */
* {
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.12) transparent;
}
</style>
