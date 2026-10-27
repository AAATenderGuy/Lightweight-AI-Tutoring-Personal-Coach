<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { loadMaterials, notify, state } from '../store'
import Icon from '../components/Icon.vue'
import OcrUploadDialog from '../components/OcrUploadDialog.vue'

const fileInput = ref(null)
const drag = ref(false)
const uploading = ref(false)
const uploads = ref([])
const ocrOpen = ref(false)

const totalChars = computed(() => state.materials.reduce((sum, item) => sum + (item.chars || 0), 0))

function pick() {
  if (!uploading.value) fileInput.value?.click()
}

function onDrop(event) {
  drag.value = false
  handleFiles(event.dataTransfer?.files)
}

function onChange(event) {
  handleFiles(event.target.files)
  event.target.value = ''
}

async function handleFiles(fileList) {
  const files = Array.from(fileList || [])
  if (!files.length) return
  uploading.value = true
  uploads.value = []
  for (const file of files) {
    const row = reactive({ name: file.name, status: '上传中…', error: '' })
    uploads.value.push(row)
    try {
      await api.materials.upload(file)
      row.status = '已入库'
    } catch (error) {
      row.status = '失败'
      row.error = error.message
    }
  }
  uploading.value = false
  try {
    await loadMaterials()
    const failed = uploads.value.filter((row) => row.error)
    if (!failed.length) notify('资料库已更新')
    else notify('部分文件未能解析，请查看下方提示', 'error')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function remove(item) {
  if (!window.confirm(`删除资料《${item.title}》？依赖它的检索将不再命中。`)) return
  try {
    await api.materials.remove(item.id)
    await loadMaterials()
    notify('资料已删除')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function formatChars(count) {
  if (count >= 10000) return `${(count / 10000).toFixed(1)} 万字`
  return `${count} 字`
}

function formatDate(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp * 1000).toLocaleDateString('zh-CN')
}

function ext(item) {
  const name = item.filename || ''
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index + 1) : 'txt'
}
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h1>资料库</h1>
        <p>上传讲义、论文或笔记，导师与课堂会优先依据这些内容回答，并标注出处。</p>
      </div>
      <div class="page-actions">
        <span v-if="state.materials.length" class="chip">{{ state.materials.length }} 篇 · {{ formatChars(totalChars) }}</span>
        <button class="btn btn-sm" type="button" @click="ocrOpen = true">
          <Icon name="spark" :size="14" />
          拍题识别
        </button>
        <button class="btn btn-sm" type="button" :disabled="uploading" @click="pick">
          <Icon name="upload" :size="14" />
          上传资料
        </button>
      </div>
    </header>

    <div class="content">
      <div class="wide">
        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".txt,.md,.markdown,.pdf,.docx,.csv,.json,.py,.js,.ts"
          style="display: none"
          @change="onChange"
        />

        <div
          class="dropzone"
          :class="{ drag }"
          role="button"
          tabindex="0"
          @click="pick"
          @keydown.enter="pick"
          @dragover.prevent="drag = true"
          @dragleave.prevent="drag = false"
          @drop.prevent="onDrop"
        >
          <Icon name="upload" :size="20" />
          <strong>{{ uploading ? '正在解析…' : '点击选择，或把文件拖到这里' }}</strong>
          <span>支持 PDF、Word（.docx）、Markdown、TXT，单文件不超过 10 MB</span>
        </div>

        <div v-if="uploads.length" class="upload-list">
          <div v-for="(row, index) in uploads" :key="index" class="upload-row">
            <span>{{ row.name }}</span>
            <span class="muted">· {{ row.status }}</span>
            <span v-if="row.error" style="color: var(--danger)">· {{ row.error }}</span>
          </div>
        </div>

        <div v-if="!state.materials.length" class="empty-state">
          <p>资料库还是空的。上传一份讲义，再回到对话或课堂试试。</p>
        </div>

        <div v-else class="mat-list">
          <div v-for="item in state.materials" :key="item.id" class="mat-row">
            <div class="mat-icon">{{ ext(item) }}</div>
            <div class="mat-main">
              <div class="mat-title">{{ item.title }}</div>
              <div class="mat-meta">
                {{ formatChars(item.chars) }} · {{ item.chunks }} 个检索片段 · {{ formatDate(item.created_at) }}
              </div>
              <div class="mat-preview">{{ item.preview }}</div>
            </div>
            <button class="icon-btn" type="button" title="删除" @click="remove(item)">
              <Icon name="trash" :size="15" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <OcrUploadDialog v-if="ocrOpen" @close="ocrOpen = false" @saved="loadMaterials()" />
  </section>
</template>
