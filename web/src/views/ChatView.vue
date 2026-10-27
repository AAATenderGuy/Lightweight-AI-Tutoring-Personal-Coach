<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import { streamJSON } from '../api'
import { state } from '../store'
import Icon from '../components/Icon.vue'
import MarkdownText from '../components/MarkdownText.vue'
import MaterialScope from '../components/MaterialScope.vue'

const mode = ref('socratic')
const scope = ref({ mode: 'all', ids: [] })
const messages = ref([])
const input = ref('')
const busy = ref(false)
const scrollEl = ref(null)
const textareaEl = ref(null)
let controller = null

const suggestions = [
  '用自己的话讲讲「机会成本」，再给我一个生活例子',
  '我总是分不清「相关」和「因果」，怎么判断？',
  '帮我看看这道题的思路卡在哪：求 f(x)=x²-4x+3 的最小值',
  '把「光合作用」拆成三个环节，每步问我一个问题',
]

const scopeText = computed(() => {
  if (scope.value.mode === 'none') return '不使用资料'
  if (scope.value.mode === 'selected') return `${scope.value.ids.length} 篇资料`
  return '全部资料'
})

function scrollToBottom(smooth = false) {
  nextTick(() => {
    const el = scrollEl.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  })
}

function autoGrow() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

async function send(text) {
  const content = (text ?? input.value).trim()
  if (!content || busy.value) return

  messages.value.push({ role: 'user', content })
  input.value = ''
  nextTick(autoGrow)

  const history = messages.value
    .slice(0, -1)
    .slice(-12)
    .filter((item) => item.content && !item.error)
    .map((item) => ({ role: item.role, content: item.content }))

  const assistant = reactive({
    role: 'assistant',
    content: '',
    sources: [],
    error: '',
    streaming: true,
  })
  messages.value.push(assistant)
  busy.value = true
  scrollToBottom()

  controller = new AbortController()
  try {
    await streamJSON(
      '/api/chat/stream',
      {
        message: content,
        mode: mode.value,
        history,
        material_ids: scope.value.mode === 'selected' ? scope.value.ids : [],
        use_materials: scope.value.mode !== 'none',
      },
      (event) => {
        if (event.type === 'meta') assistant.sources = event.sources || []
        else if (event.type === 'delta') {
          assistant.content += event.text
          scrollToBottom()
        } else if (event.type === 'error') {
          assistant.error = event.message
          assistant.streaming = false
        } else if (event.type === 'done') {
          assistant.streaming = false
        }
      },
      controller.signal,
    )
  } catch (error) {
    if (error.name === 'AbortError') {
      if (!assistant.content) assistant.content = '（已停止）'
    } else {
      assistant.error = error.message
    }
  } finally {
    assistant.streaming = false
    if (!assistant.content && !assistant.error) assistant.error = '没有收到回复，请重试。'
    busy.value = false
    controller = null
    scrollToBottom()
  }
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

function stop() {
  controller?.abort()
}

function openSettings() {
  state.settingsOpen = true
}

function useSuggestion(text) {
  send(text)
}
</script>

<template>
  <section class="chat">
    <header class="chat-head">
      <div>
        <h1>AI 导师</h1>
        <p>先给线索，再一步步陪你把问题想清楚。回答会标注资料出处。</p>
      </div>
      <div class="chat-controls">
        <div class="segmented" role="group" aria-label="回答模式">
          <button type="button" :class="{ active: mode === 'socratic' }" @click="mode = 'socratic'">引导</button>
          <button type="button" :class="{ active: mode === 'explain' }" @click="mode = 'explain'">讲解</button>
        </div>
        <MaterialScope v-model="scope" :materials="state.materials" />
      </div>
    </header>

    <div ref="scrollEl" class="chat-scroll">
      <div class="chat-inner">
        <div v-if="!messages.length" class="empty">
          <h2>今天想弄懂什么？</h2>
          <p>{{ state.settings.demo ? '当前是演示模式：回答由本地规则生成，配置 API Key 后可获得真实模型回答。' : `当前模型：${state.settings.model}` }}</p>
          <div class="suggestions">
            <button
              v-for="suggestion in suggestions"
              :key="suggestion"
              class="suggestion"
              type="button"
              @click="useSuggestion(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
          <p class="small muted" style="margin-top: 18px">
            检索范围：{{ scopeText }}<span v-if="state.materials.length === 0"> · 还没有资料，可到「资料」页上传</span>
          </p>
        </div>

        <template v-for="(message, index) in messages" :key="index">
          <div v-if="message.role === 'user'" class="bubble-user">{{ message.content }}</div>

          <div v-else class="msg">
            <div class="msg-role">
              <span>导师</span>
              <span v-if="message.streaming" class="typing"><i /><i /><i /></span>
              <span v-else-if="message.sources?.length" class="muted">{{ message.sources.length }} 条资料引用</span>
            </div>
            <MarkdownText v-if="message.content" :source="message.content" />
            <div v-if="message.error" class="msg-error">{{ message.error }}</div>
            <div v-if="message.sources?.length" class="sources">
              <div v-for="source in message.sources" :key="source.index" class="source-card">
                <div class="source-head">
                  <span class="source-index">[{{ source.index }}]</span>
                  <span class="source-title">{{ source.title }}</span>
                  <span v-if="source.chunk_id" class="source-chunk">段落 {{ source.chunk_id }}</span>
                </div>
                <p class="source-preview">{{ source.preview }}</p>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <footer class="composer">
      <div class="composer-inner">
        <textarea
          ref="textareaEl"
          v-model="input"
          rows="1"
          placeholder="问一个问题，或贴一段材料…"
          aria-label="输入问题"
          @keydown="onKeydown"
          @input="autoGrow"
        />
        <div class="composer-bar">
          <span class="composer-hint">
            Enter 发送 · Shift+Enter 换行
            <template v-if="state.settings.demo">
              · <button class="btn btn-sm btn-ghost" type="button" style="padding: 0; font-size: inherit" @click="openSettings">配置模型</button>
            </template>
          </span>
          <button v-if="busy" class="btn btn-sm" type="button" @click="stop">
            <Icon name="stop" :size="13" />
            停止
          </button>
          <button v-else class="btn btn-primary btn-sm" type="button" :disabled="!input.trim()" @click="send()">
            <Icon name="send" :size="14" />
            发送
          </button>
        </div>
      </div>
    </footer>
  </section>
</template>
