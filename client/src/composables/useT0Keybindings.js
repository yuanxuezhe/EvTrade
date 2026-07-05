/**
 * useT0Keybindings.js — T0Trade 主表全局快捷键 (t0-trade-polish-bundle commit 5)
 *
 * Why:
 *   - trader 50+ 持仓滚不动, 鼠标点慢
 *   - 5 键 (B/S/P/↑↓/Enter) 走键盘, ↑↓ 切行 + B/S/P 触发对应行操作
 *
 * 守门 (按顺序短路):
 *   1. uiStore.t0Keybindings === false → 全不触发 (opt-out)
 *   2. e.ctrlKey/metaKey/altKey → 跳过 (避免 Ctrl+B / Cmd+S 等系统快捷键冲突)
 *   3. target.tagName ∈ {INPUT, TEXTAREA, SELECT} → 跳过 (输入框不抢)
 *   4. drawerVisible === true → 跳过 (抽屉打开时让抽屉内组件响应)
 *
 * 字母键大小写不敏感 (b/B 都触发 buy)
 *
 * change t0-trade-polish-bundle (commit 5)
 */

import { onMounted, onUnmounted } from 'vue'


/**
 * 注册快捷键 (在 setup() 调, 自动 onMounted/onUnmounted 挂卸)
 *
 * @param {Object} options
 * @param {Function} options.onBuy — 按 B 时调用 (selectedRow)
 * @param {Function} options.onSell — 按 S 时调用 (selectedRow)
 * @param {Function} options.onBalance — 按 P 时调用 (selectedRow)
 * @param {Function} options.onSelectPrev — 按 ↑ 时调用
 * @param {Function} options.onSelectNext — 按 ↓ 时调用
 * @param {Function} options.onEnter — 按 Enter 时调用 (selectedRow → 打开抽屉)
 * @param {Function} options.isEnabled — () => boolean, 默认 true; 抽屉打开等场景下动态关闭
 * @param {Function} options.getTarget — () => EventTarget, 默认 e.target (用于守门 tagName)
 */
export function useT0Keybindings({
  onBuy,
  onSell,
  onBalance,
  onSelectPrev,
  onSelectNext,
  onEnter,
  isEnabled = () => true,
  getTarget,
} = {}) {
  function _handle(e) {
    if (!isEnabled()) return
    // 修键守门
    if (e.ctrlKey || e.metaKey || e.altKey) return
    // 输入框 / 下拉守门
    const target = getTarget ? getTarget() : e.target
    const tag = (target?.tagName || '').toLowerCase()
    if (['input', 'textarea', 'select'].includes(tag)) return
    // 抽屉内可能含 contenteditable (兜底)
    if (target?.isContentEditable) return

    const key = e.key
    // Escape 留给 view 自行处理 (关闭抽屉), 不在此拦截
    if (key === 'Escape') return

    const k = key.length === 1 ? key.toLowerCase() : key
    switch (k) {
      case 'b':
        e.preventDefault()
        onBuy?.()
        break
      case 's':
        e.preventDefault()
        onSell?.()
        break
      case 'p':
        e.preventDefault()
        onBalance?.()
        break
      case 'ArrowUp':
        e.preventDefault()
        onSelectPrev?.()
        break
      case 'ArrowDown':
        e.preventDefault()
        onSelectNext?.()
        break
      case 'Enter':
        // Enter 在 input 中让表单提交, 但已守门; 主表上 = 打开抽屉
        e.preventDefault()
        onEnter?.()
        break
      default:
        // 其他键透传
        break
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', _handle)
  })
  onUnmounted(() => {
    window.removeEventListener('keydown', _handle)
  })

  return {
    /** 测试用: 手动触发 handler (绕过 onMounted) */
    _handle,
  }
}