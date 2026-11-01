<script setup>
/**
 * 三态复选框：checked / indeterminate / 未选。
 * 原生 input 的 indeterminate 只能通过 JS 设置，这里统一在挂载与依赖变化时同步。
 */
import { onMounted, ref, watch } from 'vue'

const props = defineProps({
  checked: { type: Boolean, default: false },
  indeterminate: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  label: { type: String, default: '' },
})

const emit = defineEmits(['change'])
const box = ref(null)

function sync() {
  if (box.value) box.value.indeterminate = props.indeterminate && !props.checked
}

onMounted(sync)
watch(() => [props.checked, props.indeterminate], sync)
</script>

<template>
  <label class="tri-check" :class="{ 'is-disabled': disabled }">
    <input
      ref="box"
      type="checkbox"
      :checked="checked"
      :disabled="disabled"
      @change="emit('change', $event.target.checked)"
    />
    <span v-if="label" class="tri-label">{{ label }}</span>
  </label>
</template>
