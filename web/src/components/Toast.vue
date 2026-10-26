<script setup>
import { state } from '../store'
</script>

<template>
  <Transition name="toast">
    <div v-if="state.toast" class="toast" :class="state.toast.kind" role="status">
      {{ state.toast.message }}
    </div>
  </Transition>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
