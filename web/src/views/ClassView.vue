<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { clearStudent, loadStudentTasks, notify, saveStudent, state } from '../store'
import { debounce, openStream } from '../realtime'
import Icon from '../components/Icon.vue'

const joinForm = reactive({
  code: state.pendingJoinCode || '',
  name: '',
  number: '',
})
const loginForm = reactive({ number: '', password: '', code: '' })
const authMode = ref(state.pendingJoinCode ? 'join' : 'login')
const loggingIn = ref(false)
const loginError = ref('')
const joining = ref(false)
const joinError = ref('')
const loading = ref(false)
const starting = ref(false)
const submitting = ref(false)

const stage = ref('list')
const activeTask = ref(null)
const quiz = ref(null)
const answers = reactive({})
const result = ref(null)
const timeline = ref({ events: [], topics: [] })
const selectedFile = ref(null)
const fileNote = ref('')
const uploading = ref(false)
const fileError = ref('')

const profile = computed(() => state.student.profile)
const klass = computed(() => state.student.klass)
const tasks = computed(() => state.student.tasks || [])
const pendingTasks = computed(() => tasks.value.filter((item) => item.status === 'todo'))
const doneTasks = computed(() => tasks.value.filter((item) => item.status === 'done'))
const missedTasks = computed(() => tasks.value.filter((item) => item.status === 'missed'))
const answered = computed(() => {
  if (!quiz.value) return 0
  return quiz.value.questions.filter((question) => String(answers[question.id] ?? '').trim() !== '').length
})
const progressPercent = computed(() => {
  if (!quiz.value?.questions?.length) return 0
  return Math.round((answered.value / quiz.value.questions.length) * 100)
})

const live = ref('off')
let stream = null
let openedOnce = false
const refreshSoon = debounce(() => refreshTasks(), 300)

function connectRealtime(studentId) {
  stream?.close()
  stream = null
  live.value = 'off'
  openedOnce = false
  if (!studentId) return
  stream = openStream(`/api/student/stream?student_id=${encodeURIComponent(studentId)}`, {
    headers: { 'X-Student-Token': profile.value?.token || '' },
    onStatus: (status) => { live.value = status },
    onOpen: () => {
      // 首次连接由下面的 watch 负责加载；重连时整体补一次，补上断线期间的变化。
      if (openedOnce) refreshSoon()
      openedOnce = true
    },
    onEvent: (event) => {
      if (event.type === 'student_gone') {
        clearStudent()
        notify('你已被移出班级', 'error')
        return
      }
      if (event.type === 'class_deleted') {
        clearStudent()
        notify('班级已被老师删除，请向老师要新的邀请码', 'error')
        return
      }
      if (event.type === 'assignment_created') notify(`老师发布了新作业：${event.title}`)
      if (event.type === 'assignment_deleted') notify('老师删除了一份作业')
      refreshSoon()
    },
  })
}

watch(() => profile.value?.id, (studentId) => {
  connectRealtime(studentId)
  if (studentId) refreshTasks()
}, { immediate: true })

onUnmounted(() => stream?.close())

async function refreshTasks() {
  if (!profile.value?.id) return
  loading.value = true
  try {
    await Promise.all([loadStudentTasks(), loadTimeline()])
  } catch (error) {
    notify(error.message, 'error')
    if (/学生档案不存在|班级已被删除|重新加入|身份已失效/.test(error.message)) clearStudent()
  } finally {
    loading.value = false
  }
}

async function loadTimeline() {
  // 学习轨迹只是旁路展示，加载失败不影响任务列表
  try {
    timeline.value = await api.student.timeline(profile.value.id, profile.value.token)
  } catch {
    timeline.value = { events: [], topics: [] }
  }
}

async function login() {
  if (!loginForm.number.trim() || !loginForm.password) {
    loginError.value = '请填写学号和密码。'
    return
  }
  loggingIn.value = true
  loginError.value = ''
  try {
    const data = await api.student.login({
      number: loginForm.number.trim(),
      password: loginForm.password,
      code: loginForm.code.trim(),
    })
    saveStudent({ ...data.student, token: data.token, class_name: data.klass.name })
    state.student.klass = data.klass
    state.student.tasks = data.tasks || []
    state.student.loaded = true
    loginForm.password = ''
    stage.value = 'list'
    notify(`欢迎回来，${data.student.name}`)
    window.scrollTo({ top: 0 })
  } catch (error) {
    loginError.value = error.message
  } finally {
    loggingIn.value = false
  }
}

async function join() {
  if (!joinForm.code.trim() || !joinForm.name.trim()) {
    joinError.value = '邀请码和姓名都要填写。'
    return
  }
  joining.value = true
  joinError.value = ''
  try {
    const data = await api.student.join({
      code: joinForm.code.trim(),
      name: joinForm.name.trim(),
      number: joinForm.number.trim(),
    })
    saveStudent({ ...data.student, token: data.token, class_name: data.klass.name })
    state.student.klass = data.klass
    state.pendingJoinCode = ''
    await refreshTasks()
    notify(`已加入「${data.klass.name}」`)
  } catch (error) {
    joinError.value = error.message
  } finally {
    joining.value = false
  }
}

function leaveClass() {
  if (!window.confirm('退出当前班级？重新登录需要学号和密码，已提交的作业记录不会丢失。')) return
  clearStudent()
  joinForm.name = ''
  joinForm.number = ''
  loginForm.password = ''
  loginForm.code = ''
  authMode.value = 'login'
  stage.value = 'list'
  quiz.value = null
  result.value = null
  notify('已退出班级')
}

async function startTask(task) {
  if (starting.value) return
  starting.value = true
  try {
    const data = await api.student.start(task.id, profile.value.id, profile.value.token)
    activeTask.value = { ...task, ...(data.assignment || {}) }
    result.value = null
    fileError.value = ''
    selectedFile.value = null
    fileNote.value = ''
    if (data.assignment?.submission_mode === 'file' || !data.quiz) {
      result.value = data.submitted ? await api.student.result(task.id, profile.value.id, profile.value.token) : null
      stage.value = 'file'
    } else {
      quiz.value = data.quiz
      Object.keys(answers).forEach((key) => delete answers[key])
      stage.value = 'quiz'
    }
    if (data.submitted) notify('这份作业之前已提交过，重新提交会以最后一次为准')
    window.scrollTo({ top: 0 })
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    starting.value = false
  }
}

async function viewResult(task) {
  try {
    result.value = await api.student.result(task.id, profile.value.id, profile.value.token)
    activeTask.value = { ...task, ...(result.value.kind === 'file' ? { submission_mode: 'file' } : {}) }
    quiz.value = null
    stage.value = result.value.kind === 'file' ? 'file' : 'result'
    window.scrollTo({ top: 0 })
  } catch (error) {
    notify(error.message, 'error')
  }
}

function onFilePick(event) {
  const file = event.target.files?.[0] || null
  selectedFile.value = file
  fileError.value = ''
}

async function submitFile() {
  if (!selectedFile.value || uploading.value) {
    fileError.value = '请先选择一个文件。'
    return
  }
  uploading.value = true
  fileError.value = ''
  try {
    result.value = await api.student.submitFile(
      activeTask.value.id,
      profile.value.id,
      profile.value.token,
      selectedFile.value,
      fileNote.value.trim(),
    )
    selectedFile.value = null
    stage.value = 'file'
    await refreshTasks()
    notify(`已提交，AI 初评 ${Math.round((result.value.score || 0) * 100)} 分`)
    window.scrollTo({ top: 0 })
  } catch (error) {
    fileError.value = error.message
  } finally {
    uploading.value = false
  }
}

async function submit() {
  if (!quiz.value || submitting.value) return
  submitting.value = true
  try {
    const payload = quiz.value.questions.map((question) => ({
      question_id: question.id,
      answer: String(answers[question.id] ?? ''),
    }))
    result.value = await api.student.submit(
      activeTask.value.id, profile.value.id, profile.value.token, payload,
    )
    stage.value = 'result'
    quiz.value = null
    await refreshTasks()
    notify(`已提交，得分 ${Math.round((result.value.score || 0) * 100)}`)
    window.scrollTo({ top: 0 })
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    submitting.value = false
  }
}

function backToList() {
  stage.value = 'list'
  quiz.value = null
  result.value = null
  activeTask.value = null
  selectedFile.value = null
  fileNote.value = ''
  fileError.value = ''
  Object.keys(answers).forEach((key) => delete answers[key])
}

function retry() {
  if (activeTask.value) startTask(activeTask.value)
}

function pct(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function scoreOf(value) {
  return Math.round((Number(value) || 0) * 100)
}

function fileUrl(fileId) {
  if (!result.value?.submission_id) return '#'
  return api.student.fileUrl(result.value.submission_id, fileId, profile.value.id, profile.value.token)
}

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function dueText(task) {
  if (!task.due_at) return '不限时'
  const overdue = task.due_at < Date.now() / 1000
  return `${overdue ? '已截止' : '截止'} ${formatTime(task.due_at)}`
}

function kindLabel(kind) {
  return kind === 'quiz' ? '随堂测验' : '课后作业'
}

function answerText(item) {
  if (item.type === 'single') {
    const index = Number(item.submitted)
    if (!Number.isInteger(index) || index < 0 || item.submitted === '') return '未作答'
    return item.options?.[index] ? `${'ABCDEF'[index]}. ${item.options[index]}` : `选项 ${'ABCDEF'[index]}`
  }
  return item.submitted || '未作答'
}

function correctText(item) {
  if (item.type === 'single') {
    const index = Number(item.correct_index)
    if (Number.isInteger(index) && item.options?.[index]) return `${'ABCDEF'[index]}. ${item.options[index]}`
    return '—'
  }
  return item.correct_answer || '—'
}
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h1>我的班级</h1>
        <p>用老师导入的学号和密码登录，在这里完成随堂测验和课后作业。</p>
      </div>
      <div class="page-actions">
        <template v-if="profile">
          <span class="chip">{{ profile.name }}<template v-if="profile.number"> · {{ profile.number }}</template></span>
          <span v-if="live === 'live'" class="live-pill" title="老师发布的作业会立刻出现">
            <span class="dot live" />实时
          </span>
          <span v-else-if="live === 'offline'" class="live-pill" title="正在重新连接">
            <span class="dot" />重连中
          </span>
          <button class="btn btn-sm" type="button" :disabled="loading" @click="refreshTasks">
            <Icon name="refresh" :size="13" />
            刷新
          </button>
          <button class="btn btn-sm btn-ghost" type="button" @click="leaveClass">退出班级</button>
        </template>
      </div>
    </header>

    <div class="content">
      <div class="wide">
        <!-- 未登录 -->
        <div v-if="!profile" class="join-wrap">
          <form v-if="authMode === 'login'" class="join-card" @submit.prevent="login">
            <div class="join-mark">E</div>
            <h2>学生登录</h2>
            <p class="small muted" style="margin: 0 0 4px">
              用老师导入的教务系统学号和密码登录；忘记密码请联系老师重置。
            </p>
            <div class="field">
              <label for="login-number">学号</label>
              <input
                id="login-number"
                v-model="loginForm.number"
                class="input"
                inputmode="numeric"
                autocomplete="username"
                placeholder="例：2024001"
                maxlength="32"
                spellcheck="false"
              />
            </div>
            <div class="field">
              <label for="login-password">密码</label>
              <input
                id="login-password"
                v-model="loginForm.password"
                class="input"
                type="password"
                autocomplete="current-password"
                placeholder="初始密码由老师提供"
                maxlength="72"
              />
            </div>
            <details class="field">
              <summary class="small muted" style="cursor: pointer">同号多班？填写班级邀请码（可选）</summary>
              <input
                v-model="loginForm.code"
                class="input"
                style="margin-top: 8px"
                placeholder="6 位邀请码"
                maxlength="12"
                spellcheck="false"
              />
            </details>
            <div v-if="loginError" class="msg-error">{{ loginError }}</div>
            <button class="btn btn-primary btn-block" type="submit" :disabled="loggingIn">
              {{ loggingIn ? '登录中…' : '登录' }}
            </button>
            <p class="small muted" style="margin: 0">还没有账号？让老师先在班级里导入名单。</p>
            <button class="btn btn-sm btn-ghost" type="button" @click="authMode = 'join'; loginError = ''">
              老师给了邀请码，改用邀请码加入
            </button>
          </form>

          <form v-else class="join-card" @submit.prevent="join">
            <div class="join-mark">E</div>
            <h2>用邀请码加入</h2>
            <p class="small muted" style="margin: 0 0 4px">
              邀请码由老师提供，共 6 位。老师导入名单后，请改用学号 + 密码登录。
            </p>
            <div class="field">
              <label for="join-code">班级邀请码</label>
              <input
                id="join-code"
                v-model="joinForm.code"
                class="input invite-input"
                placeholder="例如 K7M2QP"
                maxlength="8"
                autocapitalize="characters"
                spellcheck="false"
              />
            </div>
            <div class="grid-2">
              <div class="field">
                <label for="join-name">姓名</label>
                <input id="join-name" v-model="joinForm.name" class="input" placeholder="真实姓名或昵称" maxlength="20" />
              </div>
              <div class="field">
                <label for="join-number">学号（可选）</label>
                <input id="join-number" v-model="joinForm.number" class="input" placeholder="例：07" maxlength="20" />
              </div>
            </div>
            <div v-if="joinError" class="msg-error">{{ joinError }}</div>
            <button class="btn btn-primary btn-block" type="submit" :disabled="joining">
              {{ joining ? '正在加入…' : '加入班级' }}
            </button>
            <button class="btn btn-sm btn-ghost" type="button" @click="authMode = 'login'; joinError = ''">
              返回学号登录
            </button>
          </form>
        </div>

        <!-- 作答 -->
        <div v-else-if="stage === 'quiz' && quiz" class="task-run">
          <div class="task-bar">
            <button class="btn btn-sm btn-ghost" type="button" @click="backToList">
              <Icon name="left" :size="13" />
              返回任务
            </button>
            <span class="spacer" />
            <span class="small muted">{{ klass?.name }} · {{ dueText(activeTask || {}) }}</span>
          </div>

          <div class="quiz-layout">
            <div class="quiz-main">
              <div class="result-head">
                <div class="row" style="gap: 8px; flex-wrap: wrap">
                  <span class="chip">{{ kindLabel(activeTask?.kind) }}</span>
                  <span class="chip">{{ quiz.questions.length }} 题</span>
                </div>
                <div style="font-size: 17px; font-weight: 650; margin-top: 6px">{{ activeTask?.title || quiz.title }}</div>
                <div class="small muted">{{ activeTask?.instructions || '完成后提交，老师会看到你的作答与得分。' }}</div>
              </div>

              <div v-for="(question, index) in quiz.questions" :key="question.id" class="quiz-card">
                <div class="quiz-q-title">{{ index + 1 }}. {{ question.question }}</div>
                <div v-if="question.type === 'single'" class="quiz-options" style="margin-top: 10px">
                  <button
                    v-for="(option, optionIndex) in question.options"
                    :key="optionIndex"
                    type="button"
                    class="quiz-option"
                    :class="{ selected: answers[question.id] === optionIndex }"
                    @click="answers[question.id] = optionIndex"
                  >
                    <span class="key">{{ 'ABCD'[optionIndex] }}</span>
                    <span>{{ option }}</span>
                  </button>
                </div>
                <textarea
                  v-else
                  v-model="answers[question.id]"
                  class="textarea"
                  rows="3"
                  style="margin-top: 10px"
                  placeholder="写下你的回答，尽量覆盖关键点…"
                />
                <div v-if="question.knowledge_point" class="small muted" style="margin-top: 8px">
                  知识点：{{ question.knowledge_point }}
                </div>
              </div>
            </div>

            <aside class="quiz-side">
              <div class="quiz-card stack">
                <div>
                  <div class="small muted">作答进度</div>
                  <div style="font-size: 20px; font-weight: 600">{{ answered }} / {{ quiz.questions.length }}</div>
                </div>
                <div class="bar" style="margin: 0"><span :style="{ width: `${progressPercent}%` }" /></div>
                <button class="btn btn-primary" type="button" :disabled="submitting || !answered" @click="submit">
                  {{ submitting ? '提交中…' : '提交作业' }}
                </button>
                <p class="small muted" style="margin: 0">提交后不能修改，未作答按 0 分计。</p>
              </div>
              <div class="hint-box">
                简答题由 AI 按评分要点批改；没有配置 API Key 时使用关键词匹配，结果仅供参考。
              </div>
            </aside>
          </div>
        </div>

        <!-- 文件提交 -->
        <div v-else-if="stage === 'file'" class="task-run">
          <div class="task-bar">
            <button class="btn btn-sm btn-ghost" type="button" @click="backToList">
              <Icon name="left" :size="13" />
              返回任务
            </button>
            <span class="spacer" />
            <span class="small muted">{{ klass?.name }} · {{ dueText(activeTask || {}) }}</span>
          </div>

          <div class="quiz-layout">
            <div class="quiz-main">
              <div class="result-head">
                <div class="row" style="gap: 8px; flex-wrap: wrap">
                  <span class="chip">{{ kindLabel(activeTask?.kind) }}</span>
                  <span class="chip">文件提交</span>
                  <span v-if="result" class="chip accent">已提交</span>
                </div>
                <div style="font-size: 17px; font-weight: 650; margin-top: 6px">{{ activeTask?.title || result?.title }}</div>
                <div class="small muted">
                  {{ activeTask?.instructions || '按老师要求提交文件，AI 先给出初评，老师复核后为最终成绩。' }}
                </div>
                <div v-if="activeTask?.rubric" class="hint-box" style="margin-top: 10px">
                  <b>评分要点：</b>{{ activeTask.rubric }}
                </div>
              </div>

              <template v-if="result">
                <div class="result-head">
                  <div class="small muted">{{ result.title }}</div>
                  <div class="result-score">
                    {{ scoreOf(result.teacher_score ?? result.score) }}<span style="font-size: 14px; color: var(--ink-3); font-weight: 400"> / 100</span>
                  </div>
                  <div class="small muted">
                    {{ result.teacher_score != null ? '教师复核分' : 'AI 初评分' }}
                    <template v-if="result.ai_score != null && result.teacher_score != null"> · AI 初评 {{ scoreOf(result.ai_score) }} 分</template>
                    <template v-if="result.needs_review"> · 待老师复核</template>
                  </div>
                </div>

                <div v-if="result.teacher_feedback" class="explain-block">
                  <span class="answer-label">教师评语</span>{{ result.teacher_feedback }}
                </div>
                <div v-if="result.ai_feedback" class="hint-box">
                  <b>AI 初评：</b>{{ result.ai_feedback }}
                  <span v-if="result.ai_demo" class="chip" style="margin-left: 6px">演示评分</span>
                </div>

                <div v-if="result.ai_criteria?.length" class="quiz-card">
                  <div class="small muted" style="margin-bottom: 6px">评分要点</div>
                  <div v-for="item in result.ai_criteria" :key="item.name" class="row" style="gap: 8px; padding: 4px 0">
                    <span class="chip" :class="{ accent: item.met }">{{ item.met ? '达成' : '未达成' }}</span>
                    <span style="flex: 1">{{ item.name }}</span>
                    <span class="small muted">{{ item.comment }}</span>
                  </div>
                </div>

                <div v-if="result.files?.length" class="quiz-card">
                  <div class="small muted" style="margin-bottom: 6px">已提交的文件</div>
                  <div v-for="file in result.files" :key="file.id" class="row" style="justify-content: space-between; gap: 8px">
                    <span>{{ file.filename }}</span>
                    <a class="btn btn-sm" :href="fileUrl(file.id)" target="_blank" rel="noopener">下载</a>
                  </div>
                </div>

                <div class="row" style="gap: 8px">
                  <button class="btn" type="button" @click="backToList">返回任务列表</button>
                  <button
                    v-if="activeTask?.state === 'open'"
                    class="btn btn-primary"
                    type="button"
                    :disabled="uploading"
                    @click="startTask(activeTask)"
                  >
                    重新提交
                  </button>
                </div>
              </template>

              <template v-else>
                <div class="quiz-card stack">
                  <div class="field">
                    <label for="task-file">选择文件</label>
                    <input
                      id="task-file"
                      class="input"
                      type="file"
                      accept=".pdf,.docx,.pptx,.txt,.md,.png,.jpg,.jpeg,.webp"
                      @change="onFilePick"
                    />
                    <span class="small muted">支持 pdf / docx / pptx / txt / md / 图片，单个文件不超过 20 MB。</span>
                  </div>
                  <div class="field">
                    <label for="task-note">给老师的说明（可选）</label>
                    <textarea
                      id="task-note"
                      v-model="fileNote"
                      class="textarea"
                      rows="2"
                      maxlength="500"
                      placeholder="例：第 3 题用到了课堂上的推导。"
                    />
                  </div>
                  <div v-if="fileError" class="msg-error">{{ fileError }}</div>
                  <button class="btn btn-primary" type="button" :disabled="uploading || !selectedFile" @click="submitFile">
                    {{ uploading ? '正在提交并批改…' : '提交作业' }}
                  </button>
                  <p class="small muted" style="margin: 0">
                    提交后 AI 会给出初评，老师复核后计入最终成绩；截止前可以重新提交。
                  </p>
                </div>
                <div class="hint-box">图片或扫描件可能无法提取文字，会自动转给老师人工批改。</div>
              </template>
            </div>
          </div>
        </div>

        <!-- 结果 -->
        <div v-else-if="stage === 'result' && result" class="stack">
          <div class="result-head">
            <div class="row" style="justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap">
              <div>
                <div class="small muted">{{ activeTask?.title || result.title }}</div>
                <div class="result-score">
                  {{ scoreOf(result.score) }}<span style="font-size: 14px; color: var(--ink-3); font-weight: 400"> / 100</span>
                </div>
                <div class="small muted">
                  答对 {{ result.correct_count }} / {{ result.total }} 题
                  <template v-if="result.attempts > 1"> · 第 {{ result.attempts }} 次提交</template>
                </div>
              </div>
              <div class="result-actions">
                <button class="btn btn-sm" type="button" @click="backToList">返回任务列表</button>
                <button
                  v-if="activeTask?.status === 'todo' || activeTask?.state === 'open'"
                  class="btn btn-sm btn-primary"
                  type="button"
                  @click="retry"
                >
                  再做一次
                </button>
              </div>
            </div>
          </div>

          <div v-if="!result.reveal" class="hint-box">
            老师设置了「交卷后不显示答案」，这里只显示对错与得分。需要讲解可以回到课堂提问。
          </div>

          <div
            v-for="(item, index) in result.results"
            :key="item.question_id"
            class="result-item"
            :class="item.correct ? 'correct' : 'wrong'"
          >
            <div class="result-meta">
              <span class="chip" :class="{ accent: item.correct }">{{ item.correct ? '正确' : '待改进' }}</span>
              <span v-if="item.knowledge_point" class="small muted">{{ item.knowledge_point }}</span>
              <span class="spacer" />
              <span class="small muted">得分 {{ pct(item.score) }}</span>
            </div>
            <div class="q">{{ index + 1 }}. {{ item.question }}</div>
            <div class="answer-grid">
              <div class="answer-cell">
                <span class="answer-label">你的作答</span>
                <div class="answer-text">{{ answerText(item) }}</div>
              </div>
              <div v-if="result.reveal" class="answer-cell">
                <span class="answer-label">正确答案</span>
                <div class="answer-text strong">{{ correctText(item) }}</div>
              </div>
            </div>
            <div v-if="result.reveal && item.explanation" class="explain-block">
              <span class="answer-label">解析</span>{{ item.explanation }}
            </div>
            <div v-if="result.reveal && item.type !== 'single' && item.feedback" class="feedback-line">
              {{ item.feedback }}
            </div>
          </div>
        </div>

        <!-- 任务列表 -->
        <div v-else>
          <div v-if="klass" class="class-banner">
            <div>
              <div class="small muted">当前班级</div>
              <div class="class-banner-name">{{ klass.name }}</div>
              <div class="small muted">
                {{ klass.teacher_name }}<template v-if="klass.subject"> · {{ klass.subject }}</template>
                · 邀请码 {{ klass.code }}
              </div>
            </div>
            <div class="class-banner-stats">
              <div><b>{{ pendingTasks.length }}</b><span>待完成</span></div>
              <div><b>{{ doneTasks.length }}</b><span>已完成</span></div>
            </div>
          </div>

          <div v-if="loading && !tasks.length" class="loading-stage">
            <div class="spinner" />
            <strong>正在读取班级任务</strong>
          </div>

          <template v-else>
            <div v-if="!tasks.length" class="empty-state">
              <p>老师还没有布置作业，先去看看课堂或做一份自己的测验吧。</p>
            </div>

            <template v-else>
              <div v-if="pendingTasks.length" class="section" style="margin-top: 18px">
                <div class="section-head">
                  <h2>待完成</h2>
                  <span class="small muted">{{ pendingTasks.length }} 份</span>
                </div>
                <div class="task-list">
                  <div v-for="task in pendingTasks" :key="task.id" class="task-card">
                    <div class="task-main">
                      <div class="row" style="gap: 6px; flex-wrap: wrap">
                        <span class="chip accent">{{ kindLabel(task.kind) }}</span>
                        <span class="chip">{{ task.submission_mode === 'file' ? '文件提交' : `${task.question_count} 题` }}</span>
                        <span class="chip">{{ dueText(task) }}</span>
                      </div>
                      <div class="task-title">{{ task.title }}</div>
                      <div class="small muted">{{ task.instructions || '按题目要求作答后提交。' }}</div>
                    </div>
                    <button class="btn btn-primary btn-sm" type="button" :disabled="starting" @click="startTask(task)">
                      {{ task.submission_mode === 'file' ? '提交附件' : '开始作答' }}
                      <Icon name="arrow" :size="12" />
                    </button>
                  </div>
                </div>
              </div>

              <div v-if="doneTasks.length" class="section">
                <div class="section-head">
                  <h2>已完成</h2>
                  <span class="small muted">重复提交以最后一次为准</span>
                </div>
                <div class="task-list">
                  <div v-for="task in doneTasks" :key="task.id" class="task-card done">
                    <div class="task-main">
                      <div class="row" style="gap: 6px; flex-wrap: wrap">
                        <span class="chip accent">{{ kindLabel(task.kind) }}</span>
                        <span class="chip">已提交 · {{ formatTime(task.submitted_at) }}</span>
                        <span v-if="task.attempts > 1" class="chip">{{ task.attempts }} 次</span>
                      </div>
                      <div class="task-title">{{ task.title }}</div>
                    </div>
                    <div class="task-side">
                      <div class="task-score">{{ scoreOf(task.score) }}<span>分</span></div>
                      <button class="btn btn-sm" type="button" @click="viewResult(task)">查看结果</button>
                      <button
                        v-if="task.state === 'open'"
                        class="btn btn-sm btn-ghost"
                        type="button"
                        :disabled="starting"
                        @click="startTask(task)"
                      >
                        {{ task.submission_mode === 'file' ? '重新提交' : '再做一次' }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="missedTasks.length" class="section">
                <div class="section-head">
                  <h2>已截止</h2>
                  <span class="small muted">可以找老师重新开放</span>
                </div>
                <div class="task-list">
                  <div v-for="task in missedTasks" :key="task.id" class="task-card missed">
                    <div class="task-main">
                      <div class="row" style="gap: 6px; flex-wrap: wrap">
                        <span class="chip">{{ kindLabel(task.kind) }}</span>
                        <span class="chip">{{ dueText(task) }}</span>
                      </div>
                      <div class="task-title">{{ task.title }}</div>
                    </div>
                    <span class="small muted">未提交</span>
                  </div>
                </div>
              </div>
            </template>

            <div v-if="timeline.topics.length || timeline.events.length" class="section">
              <div class="section-head">
                <h2>学习轨迹</h2>
                <span class="small muted">由作业与测验记录自动汇总</span>
              </div>
              <div v-if="timeline.topics.length" class="mastery-list">
                <div v-for="topic in timeline.topics.slice(0, 6)" :key="topic.topic" class="mastery-row">
                  <span class="mastery-name" :title="topic.topic">{{ topic.topic }}</span>
                  <div class="mastery-bar"><i :style="{ width: scoreOf(topic.mastery) + '%' }" /></div>
                  <span class="mastery-val">{{ scoreOf(topic.mastery) }}%</span>
                  <span class="chip">{{ topic.label }}</span>
                </div>
              </div>
              <div v-if="timeline.events.length" class="timeline-list">
                <div v-for="event in timeline.events" :key="event.id" class="timeline-row">
                  <span class="chip accent">{{ event.label }}</span>
                  <span class="timeline-text" :title="event.summary">{{ event.summary || event.topic }}</span>
                  <span v-if="event.score != null" class="timeline-score">{{ scoreOf(event.score) }}分</span>
                  <span class="small muted">{{ formatTime(event.ts) }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>
