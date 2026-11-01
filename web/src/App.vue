<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import ChatView from './views/ChatView.vue'
import ClassroomView from './views/ClassroomView.vue'
import QuizView from './views/QuizView.vue'
import MaterialsView from './views/MaterialsView.vue'
import ProgressView from './views/ProgressView.vue'
import ClassView from './views/ClassView.vue'
import TeacherView from './views/TeacherView.vue'
import AuthGate from './components/AuthGate.vue'
import Icon from './components/Icon.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import Toast from './components/Toast.vue'
import { bootstrap, state, switchView } from './store'
import { useSmoothScroll } from './composables/useSmoothScroll'

const baseNav = [
  { id: 'chat', label: '对话', icon: 'chat' },
  { id: 'classroom', label: '课堂', icon: 'classroom' },
  { id: 'quiz', label: '测验', icon: 'quiz' },
  { id: 'materials', label: '资料', icon: 'materials' },
  { id: 'progress', label: '进度', icon: 'progress' },
]

/** 登录后只出现与身份匹配的工作区入口；未登录只给「登录」。 */
const nav = computed(() => {
  if (state.teacher.profile) return [...baseNav, { id: 'teacher', label: '教师', icon: 'board' }]
  if (state.student.profile) return [...baseNav, { id: 'class', label: '班级', icon: 'users' }]
  return [...baseNav, { id: 'auth', label: '登录', icon: 'user' }]
})

onMounted(bootstrap)

/* 惯性滚轮挂在当前视图的滚动容器上：视图换了容器也换了，所以要跟着重建。 */
const mainRef = ref(null)
const smoothScroll = useSmoothScroll(
  () => mainRef.value?.querySelector('.content, .chat-scroll') || null,
)

watch(
  () => [state.booted, state.view],
  async () => {
    await nextTick()
    smoothScroll.mount()
  },
  { immediate: true },
)

/**
 * 侧栏切页：以点击位置为圆心做 clip-path 圆形扩散。
 * 优先用原生 View Transitions API；浏览器不支持就直接换页，不加 polyfill。
 */
function go(id, event) {
  if (id === state.view) return
  if (typeof document.startViewTransition !== 'function') {
    switchView(id)
    return
  }
  const x = event?.clientX ?? window.innerWidth / 2
  const y = event?.clientY ?? window.innerHeight / 2
  const radius = Math.hypot(
    Math.max(x, window.innerWidth - x),
    Math.max(y, window.innerHeight - y),
  )
  const root = document.documentElement
  root.style.setProperty('--vt-x', `${x}px`)
  root.style.setProperty('--vt-y', `${y}px`)
  root.style.setProperty('--vt-r', `${Math.ceil(radius)}px`)
  document.startViewTransition(async () => {
    switchView(id)
    await nextTick()
  })
}
</script>

<template>
  <div v-if="state.booted" class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">E</div>
        <div class="brand-text">
          <div class="brand-name">Edu</div>
          <div class="brand-sub">轻量 AI 教学 · v{{ state.health?.version || '1.2.0' }}</div>
        </div>
      </div>

      <nav class="nav" aria-label="主导航">
        <button
          v-for="item in nav"
          :key="item.id"
          class="nav-item"
          :class="{ active: state.view === item.id }"
          type="button"
          :aria-current="state.view === item.id ? 'page' : undefined"
          @click="go(item.id, $event)"
        >
          <Icon :name="item.icon" :size="16" />
          {{ item.label }}
        </button>
      </nav>

      <div class="sidebar-foot">
        <button class="mode-pill" type="button" title="打开模型设置" @click="state.settingsOpen = true">
          <span class="dot" :class="{ live: !state.settings.demo }" />
          <span>{{ state.settings.demo ? '演示模式' : state.settings.model }}</span>
        </button>
        <button class="nav-item" type="button" @click="state.settingsOpen = true">
          <Icon name="settings" :size="16" />
          <span class="nav-label">设置</span>
        </button>
      </div>
    </aside>

    <main ref="mainRef" class="main">
      <ChatView v-if="state.view === 'chat'" />
      <ClassroomView v-else-if="state.view === 'classroom'" />
      <QuizView v-else-if="state.view === 'quiz'" />
      <MaterialsView v-else-if="state.view === 'materials'" />
      <ProgressView v-else-if="state.view === 'progress'" />
      <ClassView v-else-if="state.view === 'class'" />
      <TeacherView v-else-if="state.view === 'teacher'" />
      <section v-else-if="state.view === 'auth'" class="page">
        <div class="content">
          <AuthGate />
        </div>
      </section>
    </main>

    <SettingsDialog v-if="state.settingsOpen" />
    <Toast />
  </div>

  <div v-else class="boot">
    <div class="boot-inner">
      <template v-if="state.booting">
        <h1>Edu 正在启动</h1>
        <p>正在连接本地服务并读取资料库…</p>
        <div class="spinner" style="margin: 0 auto" />
      </template>
      <template v-else>
        <h1>无法连接 Edu 服务</h1>
        <p>{{ state.error || '请确认后端已启动（start.bat 或 python -m server.main）。' }}</p>
        <button class="btn btn-primary" type="button" @click="bootstrap">重试连接</button>
      </template>
    </div>
  </div>
</template>
