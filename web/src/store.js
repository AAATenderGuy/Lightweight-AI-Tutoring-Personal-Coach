import { reactive } from 'vue'
import { api, getToken, setToken } from './api'

function readStored(key) {
  try {
    return JSON.parse(window.localStorage.getItem(key) || 'null')
  } catch {
    return null
  }
}

export const state = reactive({
  view: 'chat',
  booted: false,
  booting: true,
  error: '',
  health: null,
  settings: {
    base_url: '',
    model: '',
    has_key: false,
    demo: true,
    key_hint: '',
    temperature: 0.6,
  },
  materials: [],
  lessons: [],
  progress: {
    topics: [],
    recommendations: [],
    stats: { topics: 0, attempts: 0, average_mastery: 0 },
    events: [],
  },
  settingsOpen: false,
  toast: null,
  pendingQuizTopic: '',
  pendingJoinCode: '',
  teacher: {
    token: getToken(),
    profile: null,
    checked: false,
  },
  student: {
    profile: readStored('edu_student'),
    klass: null,
    tasks: [],
    loaded: false,
  },
})

let toastTimer = 0

export function notify(message, kind = 'info') {
  state.toast = { message, kind, id: Date.now() }
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    state.toast = null
  }, kind === 'error' ? 6000 : 3200)
}

export function switchView(view) {
  state.view = view
  if (view === 'progress') refreshProgress()
  if (view === 'classroom') loadLessons().catch((error) => notify(error.message, 'error'))
}

export async function loadHealth() {
  state.health = await api.health()
}

export async function loadMaterials() {
  const data = await api.materials.list()
  state.materials = data.items || []
}

export async function loadLessons() {
  const data = await api.lessons.list()
  state.lessons = data.items || []
}

export async function refreshProgress() {
  try {
    state.progress = await api.progress.get()
  } catch (error) {
    notify(error.message, 'error')
  }
}

export async function loadSettings() {
  const data = await api.settings.get()
  Object.assign(state.settings, data)
}

// ---------------------------------------------------------------- 教师会话
export function applyTeacherSession(data) {
  setToken(data.token)
  state.teacher.token = data.token
  state.teacher.profile = data.teacher
  state.teacher.checked = true
}

export function clearTeacherSession() {
  setToken('')
  state.teacher.token = ''
  state.teacher.profile = null
  state.teacher.checked = true
}

export async function loadTeacher() {
  if (!state.teacher.token) {
    state.teacher.profile = null
    state.teacher.checked = true
    return null
  }
  try {
    const data = await api.teacher.me()
    state.teacher.profile = data.teacher
  } catch {
    clearTeacherSession()
  } finally {
    state.teacher.checked = true
  }
  return state.teacher.profile
}

// ---------------------------------------------------------------- 学生身份
export function saveStudent(profile) {
  state.student.profile = profile
  try {
    if (profile) window.localStorage.setItem('edu_student', JSON.stringify(profile))
    else window.localStorage.removeItem('edu_student')
  } catch {
    /* 忽略存储失败 */
  }
}

export function clearStudent() {
  saveStudent(null)
  state.student.klass = null
  state.student.tasks = []
  state.student.loaded = false
}

export async function loadStudentTasks() {
  const profile = state.student.profile
  if (!profile?.id) {
    state.student.loaded = true
    return
  }
  const data = await api.student.tasks(profile.id, profile.token)
  state.student.klass = data.klass
  state.student.tasks = data.tasks || []
  state.student.loaded = true
  saveStudent({ ...profile, ...data.student, token: profile.token, class_name: data.klass?.name || '' })
}

export async function bootstrap() {
  state.booting = true
  state.error = ''
  try {
    await Promise.all([loadHealth(), loadSettings()])
    await Promise.all([loadMaterials(), loadLessons(), refreshProgress()])
    const params = new URLSearchParams(window.location.search)
    const joinCode = params.get('join')
    if (joinCode) {
      state.pendingJoinCode = joinCode.trim().toUpperCase()
      state.view = 'class'
    }
    if (state.teacher.token) loadTeacher()
    state.booted = true
  } catch (error) {
    state.error = error.message
  } finally {
    state.booting = false
  }
}
