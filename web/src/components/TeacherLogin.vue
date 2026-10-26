<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { applyTeacherSession, notify } from '../store'
import Icon from './Icon.vue'

const emit = defineEmits(['done'])
const mode = ref('login')
const busy = ref(false)
const errorText = ref('')
const form = reactive({ username: '', password: '', name: '' })

const title = computed(() => (mode.value === 'login' ? '登录教师工作台' : '创建教师账号'))

function switchMode(next) {
  mode.value = next
  errorText.value = ''
}

function fillDemo() {
  form.username = 'demo'
  form.password = 'demo1234'
  mode.value = 'login'
  errorText.value = ''
}

async function submit() {
  if (busy.value) return
  const username = form.username.trim()
  if (!username || !form.password) {
    errorText.value = '请填写账号和密码。'
    return
  }
  busy.value = true
  errorText.value = ''
  try {
    const data = mode.value === 'login'
      ? await api.teacher.login({ username, password: form.password })
      : await api.teacher.register({ username, password: form.password, name: form.name.trim() })
    applyTeacherSession(data)
    notify(mode.value === 'login' ? `欢迎回来，${data.teacher.name}` : '账号已创建')
    emit('done')
  } catch (error) {
    errorText.value = error.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="teacher-gate">
    <div class="gate-card">
      <div class="gate-brand">
        <div class="brand-mark">E</div>
        <div>
          <div class="gate-kicker">教师工作台</div>
          <div class="gate-title">{{ title }}</div>
        </div>
      </div>

      <div class="segmented gate-tabs">
        <button type="button" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button type="button" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>

      <form class="stack" @submit.prevent="submit">
        <div class="field">
          <label for="teacher-username">账号</label>
          <input
            id="teacher-username"
            v-model="form.username"
            class="input"
            autocomplete="username"
            placeholder="3–24 位字母、数字或下划线"
            spellcheck="false"
          />
        </div>

        <div v-if="mode === 'register'" class="field">
          <label for="teacher-name">显示姓名</label>
          <input id="teacher-name" v-model="form.name" class="input" placeholder="例：王老师（可留空）" maxlength="24" />
        </div>

        <div class="field">
          <label for="teacher-password">密码</label>
          <input
            id="teacher-password"
            v-model="form.password"
            class="input"
            type="password"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            :placeholder="mode === 'login' ? '输入密码' : '至少 6 位'"
          />
        </div>

        <div v-if="errorText" class="msg-error">{{ errorText }}</div>

        <button class="btn btn-primary gate-submit" type="submit" :disabled="busy">
          <Icon :name="busy ? 'refresh' : 'arrow'" :size="14" />
          {{ busy ? '请稍候…' : mode === 'login' ? '登录' : '创建并登录' }}
        </button>
      </form>

      <div class="gate-hint">
        <div class="row" style="justify-content: space-between; gap: 8px; flex-wrap: wrap">
          <span>演示账号 <code>demo</code> / <code>demo1234</code></span>
          <button class="btn btn-sm btn-ghost" type="button" @click="fillDemo">填入</button>
        </div>
        <p>
          账号只保存在本机 <code>data/teachers/</code>，密码经 PBKDF2 加盐后存储。
          学生不在这里登录：学生用老师导入的学号 + 密码进入「班级」页。
        </p>
      </div>
    </div>

    <ul class="gate-points">
      <li><b>导入名单 + 学号登录</b><span>把教务系统的学生名单导入班级，学生用学号和密码登录。</span></li>
      <li><b>随堂测验 / 文件作业</b><span>在线答题或提交附件，AI 初评后教师可复核改分。</span></li>
      <li><b>进度与错题</b><span>谁交了、哪道题错得多、哪个知识点薄弱，一眼看到。</span></li>
      <li><b>一键导出</b><span>班级成绩 CSV、学生个人 HTML 报告（可打印成 PDF）。</span></li>
    </ul>
  </div>
</template>
