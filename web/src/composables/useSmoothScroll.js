import Lenis from 'lenis'
import { onBeforeUnmount, watch } from 'vue'
import { prefs } from '../prefs'

const WIDE = '(min-width: 901px)'
const REDUCE = '(prefers-reduced-motion: reduce)'

/**
 * 给「当前视图的滚动容器」挂一层惯性滚轮。
 *
 * 这个应用是固定高度布局，滚动发生在内层容器（.content / .chat-scroll）里，
 * 不是 window，所以必须把容器本身同时当作 wrapper 和 content 交给 Lenis：
 * Lenis 在 wrapper 非 window 时，滚动量直接取 wrapper.scrollHeight/clientHeight，
 * 传同一个元素正好是我们要的那组数值。
 *
 * 关闭条件（任一满足即退化成原生滚动，功能完全不受影响）：
 * - 用户在设置里关掉「惯性滚轮」
 * - 窗口窄于 900px（移动端）
 * - 系统开启了「减少动态效果」
 */
export function useSmoothScroll(resolveContainer) {
  const wide = window.matchMedia(WIDE)
  const reduce = window.matchMedia(REDUCE)
  let lenis = null

  function teardown() {
    if (lenis) {
      lenis.destroy()
      lenis = null
    }
  }

  function mount() {
    teardown()
    if (!prefs.smoothScroll || !wide.matches || reduce.matches) return
    const element = resolveContainer()
    if (!element) return
    lenis = new Lenis({
      wrapper: element,
      content: element,
      lerp: 0.1,
      smoothWheel: true,
      allowNestedScroll: true,
      autoRaf: true,
    })
  }

  function onQueryChange() {
    mount()
  }

  wide.addEventListener('change', onQueryChange)
  reduce.addEventListener('change', onQueryChange)
  watch(() => prefs.smoothScroll, mount)

  onBeforeUnmount(() => {
    wide.removeEventListener('change', onQueryChange)
    reduce.removeEventListener('change', onQueryChange)
    teardown()
  })

  return { mount, teardown }
}
