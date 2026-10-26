<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  materials: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({ mode: 'all', ids: [] }) },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const root = ref(null)

const label = computed(() => {
  if (props.modelValue.mode === 'none') return '不使用资料'
  if (props.modelValue.mode === 'selected') return `${props.modelValue.ids.length} 篇资料`
  return props.materials.length ? `全部资料 · ${props.materials.length}` : '全部资料'
})

function setMode(mode) {
  const ids = mode === 'selected' ? props.materials.map((item) => item.id) : []
  emit('update:modelValue', { mode, ids })
}

function toggle(id) {
  const base = props.modelValue.mode === 'all'
    ? props.materials.map((item) => item.id)
    : props.modelValue.mode === 'none'
      ? []
      : props.modelValue.ids
  const ids = new Set(base)
  if (ids.has(id)) ids.delete(id)
  else ids.add(id)
  if (ids.size === 0) emit('update:modelValue', { mode: 'none', ids: [] })
  else if (ids.size === props.materials.length) emit('update:modelValue', { mode: 'all', ids: [] })
  else emit('update:modelValue', { mode: 'selected', ids: [...ids] })
}

function isChecked(id) {
  if (props.modelValue.mode === 'all') return true
  if (props.modelValue.mode === 'none') return false
  return props.modelValue.ids.includes(id)
}

function onDocumentClick(event) {
  if (root.value && !root.value.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentClick))
</script>

<template>
  <div ref="root" class="scope">
    <button class="btn btn-sm" type="button" @click="open = !open" :aria-expanded="open">
      {{ label }}
      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M2 4.5 6 8.5 10 4.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <div v-if="open" class="scope-panel">
      <label class="scope-item">
        <input type="radio" :checked="modelValue.mode === 'all'" @change="setMode('all')" />
        <span>全部资料（自动检索）</span>
      </label>
      <label class="scope-item">
        <input type="radio" :checked="modelValue.mode === 'none'" @change="setMode('none')" />
        <span>不使用资料，仅凭模型知识</span>
      </label>
      <template v-if="materials.length">
        <div class="scope-divider" />
        <label v-for="item in materials" :key="item.id" class="scope-item">
          <input type="checkbox" :checked="isChecked(item.id)" @change="toggle(item.id)" />
          <span>{{ item.title }}</span>
        </label>
      </template>
      <div v-else class="scope-empty">
        还没有资料。到「资料」页上传 PDF、Word 或 Markdown，回答就会带上出处。
      </div>
    </div>
  </div>
</template>

<style scoped>
.scope-divider {
  height: 1px;
  margin: 6px 4px;
  background: var(--border);
}
</style>
