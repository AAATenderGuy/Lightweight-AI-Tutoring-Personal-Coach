<script setup>
/**
 * 完成反馈按钮：按下 0.97，成功后 morph 成「对勾 + 已提交」并保持 1.2s，
 * 失败抖动一次。内部锁定 busy / done 两态，从根上防重复点击。
 *
 * action 必须返回 Promise；reject 表示失败，由调用方决定怎么提示。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  action: { type: Function, required: true },
  label: { type: String, required: true },
  busyLabel: { type: String, default: '处理中…' },
  doneLabel: { type: String, default: '已提交' },
  disabled: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
})

const emit = defineEmits(['done', 'error', 'settled'])

const phase = ref('idle')
let timer = 0

const locked = computed(() => props.disabled || phase.value === 'busy' || phase.value === 'done')

async function run() {
  if (locked.value) return
  phase.value = 'busy'
  try {
    await props.action()
    phase.value = 'done'
    emit('done')
    timer = window.setTimeout(() => {
      phase.value = 'idle'
      emit('settled')
    }, 1200)
  } catch (error) {
    phase.value = 'error'
    emit('error', error)
    timer = window.setTimeout(() => {
      phase.value = 'idle'
    }, 420)
  }
}

onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
  <button
    class="act-btn"
    :class="[`is-${phase}`, { block }]"
    type="button"
    :disabled="disabled || phase === 'busy'"
    :aria-disabled="locked"
    :aria-busy="phase === 'busy'"
    @click="run"
  >
    <span class="act-face act-idle">
      <Icon v-if="phase === 'busy'" name="refresh" :size="14" class="act-spin" />
      {{ phase === 'busy' ? busyLabel : label }}
    </span>
    <span class="act-face act-done" aria-hidden="true">
      <Icon name="check" :size="14" />
      {{ doneLabel }}
    </span>
  </button>
</template>
