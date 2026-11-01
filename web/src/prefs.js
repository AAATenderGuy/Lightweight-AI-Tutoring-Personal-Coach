import { reactive, watch } from 'vue'

const KEY = 'edu:prefs'

function read() {
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

/** 纯前端偏好，只影响观感，不参与任何接口请求。 */
export const prefs = reactive({
  smoothScroll: true,
  ...read(),
})

watch(
  prefs,
  (value) => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(value))
    } catch {
      /* 隐私模式下写不进去，忽略即可 */
    }
  },
  { deep: true },
)
