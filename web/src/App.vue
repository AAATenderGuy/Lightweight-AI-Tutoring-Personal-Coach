<script setup>
import { onMounted } from 'vue'
import ChatView from './views/ChatView.vue'
import ClassroomView from './views/ClassroomView.vue'
import QuizView from './views/QuizView.vue'
import MaterialsView from './views/MaterialsView.vue'
import ProgressView from './views/ProgressView.vue'
import ClassView from './views/ClassView.vue'
import TeacherView from './views/TeacherView.vue'
import Icon from './components/Icon.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import Toast from './components/Toast.vue'
import { bootstrap, state, switchView } from './store'

const nav = [
  { id: 'chat', label: '对话', icon: 'chat' },
  { id: 'classroom', label: '课堂', icon: 'classroom' },
  { id: 'quiz', label: '测验', icon: 'quiz' },
  { id: 'materials', label: '资料', icon: 'materials' },
  { id: 'progress', label: '进度', icon: 'progress' },
  { id: 'class', label: '班级', icon: 'users' },
  { id: 'teacher', label: '教师', icon: 'board' },
]

onMounted(bootstrap)
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
          @click="switchView(item.id)"
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

    <main class="main">
      <ChatView v-if="state.view === 'chat'" />
      <ClassroomView v-else-if="state.view === 'classroom'" />
      <QuizView v-else-if="state.view === 'quiz'" />
      <MaterialsView v-else-if="state.view === 'materials'" />
      <ProgressView v-else-if="state.view === 'progress'" />
      <ClassView v-else-if="state.view === 'class'" />
      <TeacherView v-else-if="state.view === 'teacher'" />
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
