<script setup>
/**
 * 叠卡列表：默认前 3 张轻微堆叠（每张上移 6px、缩放 0.98），
 * 点击某张展开为单卡，其余淡出并下移；再点一次收起。
 * stacked 置 false 即为普通列表，用来「关掉」这个效果。
 */
const props = defineProps({
  items: { type: Array, required: true },
  keyField: { type: String, default: 'id' },
  expanded: { type: String, default: '' },
  stacked: { type: Boolean, default: true },
})

const emit = defineEmits(['update:expanded'])

const STACK_LIMIT = 3

function styleOf(item, index) {
  if (props.expanded || !props.stacked || index >= STACK_LIMIT) return {}
  return {
    marginTop: index === 0 ? '0' : '-6px',
    transform: `scale(${1 - index * 0.01})`,
    zIndex: 3 - index,
  }
}

function toggle(item) {
  const key = String(item[props.keyField])
  emit('update:expanded', props.expanded === key ? '' : key)
}
</script>

<template>
  <div class="stack-cards" :class="{ 'is-stacked': stacked && !expanded, 'is-expanded': Boolean(expanded) }">
    <div
      v-for="(item, index) in items"
      :key="item[keyField]"
      class="stack-item"
      :class="{ 'is-open': expanded === String(item[keyField]) }"
      :style="styleOf(item, index)"
      @click="toggle(item)"
    >
      <slot name="card" :item="item" :index="index" />
    </div>
  </div>
</template>
