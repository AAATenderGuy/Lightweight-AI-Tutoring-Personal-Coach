<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 16 },
})
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'chat'">
      <path d="M4 5.5h16v11.5H9.5L4 21V5.5Z" />
      <path d="M8 9.5h8M8 13h5" />
    </template>
    <template v-else-if="name === 'classroom'">
      <rect x="3" y="4" width="18" height="12" rx="1.5" />
      <path d="M12 16v4M8.5 20h7M7 8h8M7 11.5h5" />
    </template>
    <template v-else-if="name === 'quiz'">
      <rect x="4" y="3.5" width="16" height="17" rx="2" />
      <path d="M8 8.5h8M8 12h5M8 15.5h3" />
      <path d="M16 15.5h.01" />
    </template>
    <template v-else-if="name === 'materials'">
      <path d="M6 3.5h7.5L18.5 9v11.5H6V3.5Z" />
      <path d="M13.5 3.5V9h5" />
      <path d="M9 13h6M9 16.5h4" />
    </template>
    <template v-else-if="name === 'progress'">
      <path d="M4 20h16" />
      <path d="M7 20v-5M12 20V8M17 20v-9" />
    </template>
    <template v-else-if="name === 'settings'">
      <path d="M4 8h9M17 8h3M4 16h3M11 16h9" />
      <circle cx="15" cy="8" r="2.2" />
      <circle cx="9" cy="16" r="2.2" />
    </template>
    <template v-else-if="name === 'send'">
      <path d="M4.5 12 20 5l-5.5 14-3.2-5.8L4.5 12Z" />
    </template>
    <template v-else-if="name === 'stop'">
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </template>
    <template v-else-if="name === 'close'">
      <path d="M6 6l12 12M18 6 6 18" />
    </template>
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>
    <template v-else-if="name === 'upload'">
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    </template>
    <template v-else-if="name === 'download'">
      <path d="M12 4v12M7 11l5 5 5-5" />
      <path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" />
    </template>
    <template v-else-if="name === 'trash'">
      <path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5" />
    </template>
    <template v-else-if="name === 'left'">
      <path d="M15 5l-7 7 7 7" />
    </template>
    <template v-else-if="name === 'right'">
      <path d="M9 5l7 7-7 7" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 5v6h-6" />
    </template>
    <template v-else-if="name === 'spark'">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </template>
    <template v-else-if="name === 'check'">
      <path d="M5 12.5 10 17l9-10" />
    </template>
    <template v-else-if="name === 'arrow'">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </template>
    <template v-else-if="name === 'users'">
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 20c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M16 5.6a3 3 0 0 1 0 5.8" />
      <path d="M17.5 15.2c1.8.6 3 2.3 3 4.3" />
    </template>
    <template v-else-if="name === 'board'">
      <rect x="3" y="4" width="18" height="13" rx="1.5" />
      <path d="M7 13.5v-3M11 13.5V8M15 13.5v-2M12 17v3" />
    </template>
    <template v-else-if="name === 'copy'">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M15 5.5A1.5 1.5 0 0 0 13.5 4h-8A1.5 1.5 0 0 0 4 5.5v8A1.5 1.5 0 0 0 5.5 15" />
    </template>
    <template v-else-if="name === 'link'">
      <path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.3-2.3a4 4 0 0 0-5.7-5.7L11.5 6.8" />
      <path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.3 2.3a4 4 0 0 0 5.7 5.7l1.3-1.3" />
    </template>
  </svg>
</template>
