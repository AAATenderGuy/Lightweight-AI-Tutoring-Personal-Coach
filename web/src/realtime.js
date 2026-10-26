/**
 * 实时事件连接层。
 *
 * 用 fetch + ReadableStream 而不是浏览器原生 EventSource，原因有三：
 * 1. EventSource 不能带 Authorization 头，教师端 token 只能塞进 URL；
 * 2. 401 在 EventSource 里拿不到状态码，无法区分「登录过期」和「网络抖动」；
 * 3. 解析逻辑和 api.js 里的 streamJSON 一致，后续维护成本更低。
 *
 * 协议：服务端每条事件是 `data: {json}`，另有 `: ping` 心跳。
 * 断线自动指数退避重连；每次（重）连成功都会回调 onOpen，
 * 调用方应在 onOpen 里整体重拉一次，以补齐断线期间错过的事件。
 */

import { getToken } from './api.js'

const RETRY_MIN = 800
const RETRY_MAX = 10000

function parseBlock(block, onEvent) {
  for (const line of block.split(/\r?\n/)) {
    if (!line.startsWith('data:')) continue
    const payload = line.slice(5).trim()
    if (!payload) continue
    try {
      onEvent(JSON.parse(payload))
    } catch {
      /* 忽略坏块 */
    }
  }
}

/**
 * @param {string} path SSE 地址，例如 /api/teacher/stream
 * @param {object} options
 * @param {(event: object) => void} [options.onEvent] 每收到一个事件回调
 * @param {() => void} [options.onOpen] 连接（含重连）成功时回调
 * @param {(status: 'live'|'offline'|'unauthorized') => void} [options.onStatus] 连接状态
 * @returns {{ close: () => void }}
 */
export function openStream(path, { onEvent, onOpen, onStatus, headers = {} } = {}) {
  let stopped = false
  let controller = null
  let retry = RETRY_MIN
  let timer = 0

  const notifyStatus = (status) => onStatus?.(status)

  // 服务端在 token 过期时会先推一条 unauthorized 再断开，收到后不再重连。
  const dispatch = (event) => {
    if (event?.type === 'unauthorized') stopped = true
    onEvent?.(event)
  }

  async function connect() {
    if (stopped) return
    controller = new AbortController()
    const token = getToken()
    try {
      const response = await fetch(path, {
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...headers,
        },
        signal: controller.signal,
      })
      if (response.status === 401) {
        stopped = true
        notifyStatus('unauthorized')
        onEvent?.({ type: 'unauthorized' })
        return
      }
      if (!response.ok || !response.body) throw new Error(`stream ${response.status}`)
      retry = RETRY_MIN
      notifyStatus('live')
      onOpen?.()

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let match = buffer.match(/\r?\n\r?\n/)
        while (match) {
          parseBlock(buffer.slice(0, match.index), dispatch)
          buffer = buffer.slice(match.index + match[0].length)
          match = buffer.match(/\r?\n\r?\n/)
        }
      }
    } catch (error) {
      if (stopped || error.name === 'AbortError') return
    }
    if (stopped) return
    notifyStatus('offline')
    timer = window.setTimeout(connect, retry)
    retry = Math.min(retry * 2, RETRY_MAX)
  }

  connect()

  return {
    close() {
      stopped = true
      window.clearTimeout(timer)
      controller?.abort()
    },
  }
}

/** 合并短时间内的多次触发：40 个学生同时交卷也只重拉一次。 */
export function debounce(fn, wait = 300) {
  let timer = 0
  return function debounced(...args) {
    window.clearTimeout(timer)
    timer = window.setTimeout(() => fn.apply(this, args), wait)
  }
}
