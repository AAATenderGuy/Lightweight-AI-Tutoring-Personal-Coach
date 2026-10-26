<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { loadSettings, notify, state } from '../store'
import Icon from './Icon.vue'

const form = reactive({
  base_url: state.settings.base_url || 'https://api.deepseek.com/v1',
  model: state.settings.model || 'deepseek-chat',
  api_key: '',
  temperature: state.settings.temperature ?? 0.6,
})
const clearKey = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)

const presets = [
  { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { name: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { name: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { name: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { name: 'Ollama 本地', base_url: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:7b' },
]

function applyPreset(preset) {
  form.base_url = preset.base_url
  form.model = preset.model
}

async function persist(showToast) {
  const payload = {
    base_url: form.base_url,
    model: form.model,
    temperature: Number(form.temperature),
  }
  if (clearKey.value) payload.api_key = ''
  else if (form.api_key.trim()) payload.api_key = form.api_key.trim()

  const data = await api.settings.save(payload)
  Object.assign(state.settings, data)
  form.api_key = ''
  clearKey.value = false
  await loadSettings().catch(() => {})
  if (showToast) notify('设置已保存')
}

async function save() {
  saving.value = true
  testResult.value = null
  try {
    await persist(true)
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    await persist(false)
    testResult.value = await api.settings.test()
  } catch (error) {
    testResult.value = { ok: false, message: error.message }
  } finally {
    testing.value = false
  }
}

function close() {
  state.settingsOpen = false
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div class="modal-head">
        <div>
          <h2 id="settings-title">模型设置</h2>
          <p>支持任何 OpenAI 兼容接口。密钥只保存在本机 <code>data/settings.json</code>。</p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <div class="field">
          <label>快速填充</label>
          <div class="presets">
            <button
              v-for="preset in presets"
              :key="preset.name"
              class="btn btn-sm"
              type="button"
              @click="applyPreset(preset)"
            >
              {{ preset.name }}
            </button>
          </div>
        </div>

        <div class="field">
          <label for="settings-url">Base URL</label>
          <input id="settings-url" v-model="form.base_url" class="input" placeholder="https://api.deepseek.com/v1" spellcheck="false" />
        </div>

        <div class="field">
          <label for="settings-model">模型名</label>
          <input id="settings-model" v-model="form.model" class="input" placeholder="deepseek-chat" spellcheck="false" />
        </div>

        <div class="field">
          <label for="settings-key">API Key</label>
          <input
            id="settings-key"
            v-model="form.api_key"
            class="input"
            type="password"
            autocomplete="off"
            :placeholder="state.settings.has_key ? `已保存 ${state.settings.key_hint}，留空则保持不变` : '粘贴你的 API Key'"
          />
          <div v-if="state.settings.has_key" class="row small muted">
            <button v-if="!clearKey" class="btn btn-sm btn-ghost" type="button" @click="clearKey = true">清除密钥</button>
            <template v-else>
              <span>保存后将清除密钥，回到演示模式。</span>
              <button class="btn btn-sm btn-ghost" type="button" @click="clearKey = false">撤销</button>
            </template>
          </div>
        </div>

        <details class="field">
          <summary class="small muted" style="cursor: pointer">高级：温度 {{ Number(form.temperature).toFixed(1) }}</summary>
          <input v-model.number="form.temperature" type="range" min="0" max="1.2" step="0.1" style="margin-top: 8px" />
          <span class="small muted">越低越稳定，越高越发散。教学场景建议 0.4–0.7。</span>
        </details>

        <div class="hint-box">
          不填 Key 也能启动：应用会运行在<strong>离线演示模式</strong>，用本地规则生成示例回答、课堂和测验，方便先体验流程。
        </div>

        <div v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'bad'">
          {{ testResult.message }}
        </div>
      </div>

      <div class="modal-foot">
        <button class="btn" type="button" :disabled="testing || saving" @click="testConnection">
          {{ testing ? '测试中…' : '测试连接' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
