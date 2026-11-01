<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { applyAuthSession, notify, state } from '../store'
import Icon from './Icon.vue'

const emit = defineEmits(['done'])

const mode = ref(state.pendingJoinCode ? 'register' : 'login')
const busy = ref(false)
const errorText = ref('')
const codeOpen = ref(false)

const loginForm = reactive({ account: '', password: '', code: '' })
const regForm = reactive({
  invite: state.pendingJoinCode || '',
  name: '',
  account: '',
  password: '',
})

/**
 * 身份由输入直接判定，不让人先选「我是学生/教师」：
 * 纯数字 → 学号（学生）；含字母或符号 → 教师用户名。
 * 教师用户名禁止纯数字（服务端已强校验），所以这条规则不会误判。
 */
function guessRole(value) {
  const text = (value || '').trim()
  if (!text) return ''
  return /^\d+$/.test(text) ? 'student' : 'teacher'
}

const loginRole = computed(() => guessRole(loginForm.account))
const regRole = computed(() => (regForm.invite.trim() ? 'student' : 'teacher'))
const ROLE_TEXT = { student: '学生', teacher: '教师' }

function switchMode(next) {
  mode.value = next
  errorText.value = ''
}

function fillDemo() {
  mode.value = 'login'
  loginForm.account = 'demo'
  loginForm.password = 'demo1234'
  errorText.value = ''
}

function finish(data) {
  const role = data.role === 'teacher' ? 'teacher' : 'student'
  applyAuthSession(role, data)
  const who = role === 'teacher' ? data.teacher?.name : data.student?.name
  notify(who ? `欢迎回来，${who}` : '登录成功')
  emit('done', role)
}

async function submitLogin() {
  if (busy.value) return
  const account = loginForm.account.trim()
  if (!account || !loginForm.password) {
    errorText.value = '请填写账号和密码。'
    return
  }
  busy.value = true
  errorText.value = ''
  try {
    finish(await api.auth.login({
      account,
      password: loginForm.password,
      code: loginForm.code.trim(),
    }))
  } catch (error) {
    errorText.value = error.message
    // 学号在多个班时需要邀请码，出错时把折叠项展开，省得再找
    if (/邀请码/.test(error.message)) codeOpen.value = true
  } finally {
    busy.value = false
  }
}

async function submitRegister() {
  if (busy.value) return
  const invite = regForm.invite.trim().toUpperCase()
  if (!regForm.name.trim()) {
    errorText.value = invite ? '请填写姓名。' : '请填写姓名或昵称。'
    return
  }
  if (!invite && (!regForm.account.trim() || !regForm.password)) {
    errorText.value = '创建教师账号需要填写账号和密码。'
    return
  }
  busy.value = true
  errorText.value = ''
  try {
    finish(await api.auth.register({
      invite,
      name: regForm.name.trim(),
      account: regForm.account.trim(),
      password: invite ? '' : regForm.password,
    }))
  } catch (error) {
    errorText.value = error.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-wrap">
    <form class="auth-card" @submit.prevent="mode === 'login' ? submitLogin() : submitRegister()">
      <div class="auth-brand">
        <div class="auth-mark">E</div>
        <div class="auth-brand-text">
          <div class="auth-wordmark"><em>Edu</em><span class="auth-dot">·</span>轻量 AI 教学</div>
          <div class="auth-tagline"><span class="hint-mark">*</span>学生与教师，同一个入口</div>
        </div>
      </div>

      <div class="segmented auth-tabs">
        <button type="button" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button type="button" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>

      <!-- 登录：只填账号 + 密码 -->
      <template v-if="mode === 'login'">
        <div class="field">
          <label for="auth-account">账号</label>
          <div class="auth-input-row">
            <input
              id="auth-account"
              v-model="loginForm.account"
              class="input"
              autocomplete="username"
              placeholder="学号或教师用户名"
              maxlength="32"
              spellcheck="false"
            />
            <span v-if="loginRole" class="auth-role" :class="loginRole">{{ ROLE_TEXT[loginRole] }}</span>
          </div>
          <span class="small muted"><span class="hint-mark">*</span>学生填学号，教师填用户名，系统自动分辨。</span>
        </div>

        <div class="field">
          <label for="auth-password">密码</label>
          <input
            id="auth-password"
            v-model="loginForm.password"
            class="input"
            type="password"
            autocomplete="current-password"
            placeholder="学生初始密码由老师提供"
            maxlength="72"
          />
        </div>

        <div class="field">
          <button class="auth-more" type="button" @click="codeOpen = !codeOpen">
            <Icon :name="codeOpen ? 'left' : 'right'" :size="11" />
            同一个学号在多个班？填班级邀请码
          </button>
          <input
            v-if="codeOpen"
            v-model="loginForm.code"
            class="input"
            style="margin-top: 8px"
            placeholder="6 位邀请码"
            maxlength="12"
            spellcheck="false"
          />
        </div>
      </template>

      <!-- 注册：邀请码决定身份 -->
      <template v-else>
        <div class="field">
          <label for="auth-invite">班级邀请码</label>
          <input
            id="auth-invite"
            v-model="regForm.invite"
            class="input invite-input"
            placeholder="学生填，教师留空"
            maxlength="12"
            autocapitalize="characters"
            spellcheck="false"
          />
          <span class="small muted"><span class="hint-mark">*</span>填了邀请码就是学生入班；留空则创建教师账号。</span>
        </div>

        <div class="grid-2">
          <div class="field">
            <label for="auth-name">姓名</label>
            <input
              id="auth-name"
              v-model="regForm.name"
              class="input"
              :placeholder="regRole === 'teacher' ? '例：王老师' : '真实姓名或昵称'"
              maxlength="20"
            />
          </div>
          <div class="field">
            <label for="auth-number">{{ regRole === 'teacher' ? '用户名' : '学号（可选）' }}</label>
            <input
              id="auth-number"
              v-model="regForm.account"
              class="input"
              :placeholder="regRole === 'teacher' ? '3–24 位，含字母' : '例：2024007'"
              :maxlength="regRole === 'teacher' ? 24 : 20"
              spellcheck="false"
            />
          </div>
        </div>

        <div v-if="regRole === 'teacher'" class="field">
          <label for="auth-new-password">密码</label>
          <input
            id="auth-new-password"
            v-model="regForm.password"
            class="input"
            type="password"
            autocomplete="new-password"
            placeholder="至少 6 位"
            maxlength="72"
          />
        </div>
      </template>

      <div class="auth-id" :class="mode === 'login' ? loginRole : regRole">
        <span class="auth-id-dot" />
        <template v-if="mode === 'login'">
          <template v-if="loginRole">
            将按「{{ ROLE_TEXT[loginRole] }}」身份登录
            <template v-if="loginRole === 'student'">，进入「班级」</template>
            <template v-else>，进入「教师」工作台</template>
          </template>
          <template v-else>输入账号后自动识别学生 / 教师</template>
        </template>
        <template v-else>
          <template v-if="regRole === 'student'">将按「学生」身份加入班级</template>
          <template v-else>将创建「教师」账号</template>
        </template>
      </div>

      <div v-if="errorText" class="msg-error">{{ errorText }}</div>

      <button class="btn btn-primary auth-submit" type="submit" :disabled="busy">
        <Icon :name="busy ? 'refresh' : 'arrow'" :size="14" />
        {{ busy ? '请稍候…' : mode === 'login' ? '登录' : regRole === 'student' ? '加入班级' : '创建并登录' }}
      </button>

      <div v-if="mode === 'login'" class="auth-foot">
        <span class="hint-mark">*</span>还没有账号？老师会在班级里导入名单，或直接切到「注册」。
        <button class="auth-link" type="button" @click="fillDemo">填入演示教师账号</button>
      </div>
      <div v-else class="auth-foot">
        <span class="hint-mark">*</span>{{ regRole === 'student' ? '老师已导入名单？请改用学号 + 密码登录。' : '教师账号只保存在本机，密码经 PBKDF2 加盐存储。' }}
      </div>
    </form>
  </div>
</template>
