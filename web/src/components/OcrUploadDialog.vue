<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { loadMaterials, notify } from '../store'
import Icon from './Icon.vue'

const emit = defineEmits(['close', 'saved'])

const input = ref(null)
const drag = ref(false)
const ready = ref(null) // null=检测中, true/false=组件是否可用
const busy = ref(false)
const saving = ref(false)
const errorText = ref('')
const text = ref('')
const lines = ref([])
const preview = ref('')
const meta = ref({ name: '', width: 0, height: 0, elapsedMs: 0, lowConfidence: false })

function resetImage() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  text.value = ''
  lines.value = []
  meta.value = { name: '', width: 0, height: 0, elapsedMs: 0, lowConfidence: false }
  errorText.value = ''
}

function pick() {
  if (!busy.value) input.value?.click()
}

function onDrop(event) {
  drag.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) handle(file)
}

function onChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file) handle(file)
}

async function handle(file) {
  resetImage()
  if (!/\.(png|jpe?g|webp)$/i.test(file.name)) {
    errorText.value = '只支持 JPG / PNG / WEBP 图片。'
    return
  }
  preview.value = URL.createObjectURL(file)
  meta.value = { ...meta.value, name: file.name }
  busy.value = true
  try {
    const result = await api.ocr.extract(file)
    text.value = result.text || ''
    lines.value = result.lines || []
    meta.value = {
      name: file.name,
      width: result.width,
      height: result.height,
      elapsedMs: result.elapsed_ms,
      lowConfidence: Boolean(result.low_confidence),
    }
    if (!result.text) errorText.value = '这张图里没有识别到文字，换一张更清晰的试试。'
  } catch (error) {
    errorText.value = error.message
  } finally {
    busy.value = false
  }
}

async function copyText() {
  try {
    await navigator.clipboard.writeText(text.value)
    notify('文字已复制')
  } catch {
    notify('浏览器不允许自动复制，请手动选中文本框内容', 'error')
  }
}

async function saveAsMaterial() {
  const body = text.value.trim()
  if (!body) {
    errorText.value = '没有可保存的文字。'
    return
  }
  saving.value = true
  errorText.value = ''
  try {
    const base = (meta.value.name || '拍题').replace(/\.[^.]+$/, '')
    const file = new File([body], `${base}.txt`, { type: 'text/plain' })
    await api.materials.upload(file)
    await loadMaterials()
    notify('已存入资料库，导师和课堂可以直接引用')
    emit('saved')
    emit('close')
  } catch (error) {
    errorText.value = error.message
    notify(error.message, 'error')
  } finally {
    saving.value = false
  }
}

function close() {
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  try {
    const status = await api.ocr.status()
    ready.value = Boolean(status.available)
    if (!status.available) {
      errorText.value = '服务端没有安装 OCR 组件（onnxruntime + rapidocr），当前无法识别图片。'
    }
  } catch (error) {
    ready.value = false
    errorText.value = error.message
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (preview.value) URL.revokeObjectURL(preview.value)
})
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="modal modal-wide modal-flex" role="dialog" aria-modal="true" aria-labelledby="ocr-title">
      <div class="modal-head">
        <div>
          <h2 id="ocr-title">拍题识别</h2>
          <p>拍照或截图上传，识别成可编辑文字。印刷体准确率高，手写与公式请对照原图核对。</p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <input
          ref="input"
          type="file"
          accept=".png,.jpg,.jpeg,.webp,image/*"
          style="display: none"
          @change="onChange"
        />

        <div
          class="dropzone"
          :class="{ drag, disabled: ready === false || busy }"
          role="button"
          tabindex="0"
          @click="pick"
          @keydown.enter="pick"
          @dragover.prevent="drag = true"
          @dragleave.prevent="drag = false"
          @drop.prevent="onDrop"
        >
          <img v-if="preview" :src="preview" class="ocr-preview" alt="待识别图片预览" />
          <template v-else>
            <Icon name="upload" :size="20" />
            <strong>{{ busy ? '正在识别…' : '点击选择图片，或把它拖到这里' }}</strong>
            <span>支持 JPG / PNG / WEBP，单张不超过 8 MB</span>
          </template>
        </div>

        <div v-if="busy" class="ocr-status">
          <div class="spinner" />
          <span class="small muted">首次识别需要加载模型，通常 1–3 秒…</span>
        </div>

        <template v-else-if="text || lines.length">
          <div class="field">
            <label for="ocr-text">识别结果 <span class="muted small">（可以直接修改）</span></label>
            <textarea id="ocr-text" v-model="text" class="textarea" rows="8" />
          </div>

          <div class="ocr-meta">
            <span class="chip">{{ meta.width }} × {{ meta.height }}</span>
            <span class="chip">{{ meta.elapsedMs }} ms</span>
            <span class="chip">{{ lines.length }} 行</span>
            <span v-if="meta.lowConfidence" class="chip chip-warn">含低置信度行，建议核对</span>
          </div>

          <div v-if="meta.lowConfidence" class="ocr-lines">
            <div v-for="(line, index) in lines" :key="index" class="ocr-line" :class="{ low: line.low }">
              <span class="muted">{{ line.score.toFixed(2) }}</span>
              <span>{{ line.text }}</span>
            </div>
          </div>
        </template>

        <div class="hint-box">
          识别只在本机完成，图片不会发到外部服务。结果可以「存为资料」，之后对话和课堂就会引用它。
        </div>
        <div v-if="errorText" class="msg-error">{{ errorText }}</div>
      </div>

      <div class="modal-foot">
        <button class="btn btn-sm" type="button" :disabled="!text" @click="copyText">
          <Icon name="copy" :size="13" />
          复制文字
        </button>
        <span class="spacer" />
        <button class="btn" type="button" @click="close">关闭</button>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="busy || saving || !text.trim()"
          @click="saveAsMaterial"
        >
          {{ saving ? '保存中…' : '存为资料' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dropzone.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.chip-warn {
  border-color: #e8d6a8;
  background: #fdf6e6;
  color: #8a6116;
}

.ocr-preview {
  max-width: 100%;
  max-height: 260px;
  border-radius: 8px;
  border: 1px solid var(--border);
  object-fit: contain;
}

.ocr-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ocr-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ocr-lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow-y: auto;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.ocr-line {
  display: flex;
  gap: 10px;
  font-size: 12.5px;
  line-height: 1.6;
}

.ocr-line.low {
  color: var(--ink-2);
  background: rgba(214, 158, 46, 0.08);
}
</style>
