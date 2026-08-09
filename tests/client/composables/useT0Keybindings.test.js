/**
 * useT0Keybindings.js 单测 (t0-trade-polish-bundle commit 5)
 *
 * 覆盖:
 *   - 5 键 mapping 5 action (B/S/P/ArrowUp/ArrowDown/Enter)
 *   - 大小写不敏感 (b/B 都触发)
 *   - 输入框守门 (input/textarea/select)
 *   - 修键守门 (Ctrl+B 不触发)
 *   - isEnabled() false → 全部不触发
 *   - Escape 不在拦截列表
 */
// @vitest-environment happy-dom
import { describe, it, expect, vi } from 'vitest'
import { useT0Keybindings } from '@/composables/useT0Keybindings'

function makeKeyEvent(key, opts = {}) {
  return {
    key,
    ctrlKey: !!opts.ctrl,
    metaKey: !!opts.meta,
    altKey: !!opts.alt,
    target: opts.target || { tagName: 'BODY' },
    preventDefault: vi.fn(),
  }
}

describe('useT0Keybindings', () => {
  it('5 键 mapping 5 action (lowercase)', () => {
    const handlers = {
      onBuy: vi.fn(), onSell: vi.fn(), onBalance: vi.fn(),
      onSelectPrev: vi.fn(), onSelectNext: vi.fn(), onEnter: vi.fn(),
    }
    const { _handle } = useT0Keybindings(handlers)
    _handle(makeKeyEvent('b'))
    _handle(makeKeyEvent('s'))
    _handle(makeKeyEvent('p'))
    _handle(makeKeyEvent('ArrowUp'))
    _handle(makeKeyEvent('ArrowDown'))
    _handle(makeKeyEvent('Enter'))
    expect(handlers.onBuy).toHaveBeenCalledTimes(1)
    expect(handlers.onSell).toHaveBeenCalledTimes(1)
    expect(handlers.onBalance).toHaveBeenCalledTimes(1)
    expect(handlers.onSelectPrev).toHaveBeenCalledTimes(1)
    expect(handlers.onSelectNext).toHaveBeenCalledTimes(1)
    expect(handlers.onEnter).toHaveBeenCalledTimes(1)
  })

  it('B/S/P 大小写不敏感', () => {
    const onBuy = vi.fn()
    const { _handle } = useT0Keybindings({ onBuy })
    _handle(makeKeyEvent('B'))
    _handle(makeKeyEvent('b'))
    expect(onBuy).toHaveBeenCalledTimes(2)
  })

  it('preventDefault 被调 (避免页面滚动/表单提交)', () => {
    const onBuy = vi.fn()
    const e = makeKeyEvent('b')
    const { _handle } = useT0Keybindings({ onBuy })
    _handle(e)
    expect(e.preventDefault).toHaveBeenCalled()
  })

  it('输入框 (input/textarea/select) → 不触发', () => {
    const onBuy = vi.fn()
    const { _handle } = useT0Keybindings({ onBuy })
    _handle(makeKeyEvent('b', { target: { tagName: 'INPUT' } }))
    _handle(makeKeyEvent('b', { target: { tagName: 'TEXTAREA' } }))
    _handle(makeKeyEvent('b', { target: { tagName: 'SELECT' } }))
    expect(onBuy).not.toHaveBeenCalled()
  })

  it('Ctrl+B / Cmd+S / Alt+P → 不触发 (系统快捷键)', () => {
    const handlers = { onBuy: vi.fn(), onSell: vi.fn(), onBalance: vi.fn() }
    const { _handle } = useT0Keybindings(handlers)
    _handle(makeKeyEvent('b', { ctrl: true }))
    _handle(makeKeyEvent('s', { meta: true }))
    _handle(makeKeyEvent('p', { alt: true }))
    expect(handlers.onBuy).not.toHaveBeenCalled()
    expect(handlers.onSell).not.toHaveBeenCalled()
    expect(handlers.onBalance).not.toHaveBeenCalled()
  })

  it('isEnabled() false → 全部不触发 (抽屉打开态)', () => {
    const handlers = { onBuy: vi.fn(), isEnabled: () => false }
    const { _handle } = useT0Keybindings(handlers)
    _handle(makeKeyEvent('b'))
    expect(handlers.onBuy).not.toHaveBeenCalled()
  })

  it('contenteditable → 不触发', () => {
    const onBuy = vi.fn()
    const { _handle } = useT0Keybindings({ onBuy })
    _handle(makeKeyEvent('b', { target: { tagName: 'DIV', isContentEditable: true } }))
    expect(onBuy).not.toHaveBeenCalled()
  })

  it('Escape → 不在拦截列表, 不调任何 handler', () => {
    const onBuy = vi.fn()
    const e = makeKeyEvent('Escape')
    const { _handle } = useT0Keybindings({ onBuy })
    _handle(e)
    expect(onBuy).not.toHaveBeenCalled()
    expect(e.preventDefault).not.toHaveBeenCalled()  // Escape 不 preventDefault
  })

  it('其他键 (a/1/F1) → 透传, 不调任何 handler', () => {
    const handlers = { onBuy: vi.fn(), onSell: vi.fn(), onBalance: vi.fn() }
    const { _handle } = useT0Keybindings(handlers)
    _handle(makeKeyEvent('a'))
    _handle(makeKeyEvent('1'))
    _handle(makeKeyEvent('F1'))
    expect(handlers.onBuy).not.toHaveBeenCalled()
    expect(handlers.onSell).not.toHaveBeenCalled()
    expect(handlers.onBalance).not.toHaveBeenCalled()
  })

  it('无 target.tagName → 不抛', () => {
    const onBuy = vi.fn()
    const { _handle } = useT0Keybindings({ onBuy })
    _handle({ key: 'b', target: null, preventDefault: vi.fn() })
    expect(onBuy).toHaveBeenCalled()
  })
})