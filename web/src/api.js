const JSON_HEADERS = { 'Content-Type': 'application/json' }
const TOKEN_KEY = 'edu_teacher_token'

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token)
    else window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略即可 */
  }
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function errorMessage(data, status) {
  if (!data) return `请求失败（HTTP ${status}）`
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail) && data.detail.length) {
    const first = data.detail[0]
    return first?.msg ? `参数不正确：${first.msg}` : '请求参数不正确'
  }
  if (typeof data.message === 'string') return data.message
  return `请求失败（HTTP ${status}）`
}

async function request(path, { method = 'GET', body, form = false } = {}) {
  const options = { method, headers: { ...authHeaders() } }
  if (body !== undefined) {
    if (form) {
      options.body = body
    } else {
      options.headers = { ...options.headers, ...JSON_HEADERS }
      options.body = JSON.stringify(body)
    }
  }
  let response
  try {
    response = await fetch(path, options)
  } catch (error) {
    throw new Error('无法连接 Edu 服务，请确认后端仍在运行。')
  }
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!response.ok) throw new Error(errorMessage(data, response.status))
  return data
}

/** 带登录态下载文件（CSV / HTML 报告），成功后触发浏览器保存。 */
export async function downloadFile(path, fallbackName = 'download') {
  let response
  try {
    response = await fetch(path, { headers: { ...authHeaders() } })
  } catch {
    throw new Error('无法连接 Edu 服务，请确认后端仍在运行。')
  }
  if (!response.ok) {
    const text = await response.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = null
    }
    throw new Error(errorMessage(data, response.status))
  }
  const blob = await response.blob()
  let filename = fallbackName
  const disposition = response.headers.get('content-disposition') || ''
  const matched = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (matched) {
    try {
      filename = decodeURIComponent(matched[1])
    } catch {
      /* 保留兜底文件名 */
    }
  }
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 4000)
  return filename
}

/**
 * 读取服务端的 SSE 流。事件形如：data: {"type":"delta","text":"..."}\n\n
 */
export async function streamJSON(path, body, onEvent, signal) {
  let response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { ...JSON_HEADERS, Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('无法连接 Edu 服务，请确认后端仍在运行。')
  }
  if (!response.ok) {
    const text = await response.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      data = null
    }
    throw new Error(errorMessage(data, response.status))
  }
  if (!response.body) throw new Error('当前浏览器不支持流式响应。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  const handleBlock = (block) => {
    for (const line of block.split(/\r?\n/)) {
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload))
      } catch {
        /* 忽略无法解析的心跳或坏块 */
      }
    }
  }
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let match = buffer.match(/\r?\n\r?\n/)
    while (match) {
      const index = match.index
      handleBlock(buffer.slice(0, index))
      buffer = buffer.slice(index + match[0].length)
      match = buffer.match(/\r?\n\r?\n/)
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) handleBlock(buffer)
}

export const api = {
  health: () => request('/api/health'),
  settings: {
    get: () => request('/api/settings'),
    save: (payload) => request('/api/settings', { method: 'PUT', body: payload }),
    test: () => request('/api/settings/test', { method: 'POST' }),
  },
  materials: {
    list: () => request('/api/materials'),
    upload: (file) => {
      const form = new FormData()
      form.append('file', file)
      return request('/api/materials', { method: 'POST', body: form, form: true })
    },
    remove: (id) => request(`/api/materials/${id}`, { method: 'DELETE' }),
  },
  ocr: {
    status: () => request('/api/ocr/status'),
    extract: (file) => {
      const form = new FormData()
      form.append('file', file)
      return request('/api/ocr/extract', { method: 'POST', body: form, form: true })
    },
  },
  lessons: {
    list: () => request('/api/classroom/lessons'),
    get: (id) => request(`/api/classroom/lessons/${id}`),
    remove: (id) => request(`/api/classroom/lessons/${id}`, { method: 'DELETE' }),
    quiz: (id) => request(`/api/classroom/lessons/${id}/quiz`, { method: 'POST' }),
    groupAgents: () => request('/api/classroom/group/agents'),
    saveGroupAgents: (payload) => request('/api/classroom/group/agents', { method: 'PUT', body: payload }),
    resetGroupAgents: () => request('/api/classroom/group/agents/reset', { method: 'POST' }),
  },
  quiz: {
    generate: (payload) => request('/api/quiz/generate', { method: 'POST', body: payload }),
    similar: (id, payload) => request(`/api/quiz/${id}/similar`, { method: 'POST', body: payload }),
    submit: (id, answers) => request(`/api/quiz/${id}/submit`, { method: 'POST', body: { answers } }),
  },
  progress: {
    get: () => request('/api/progress'),
    reset: () => request('/api/progress', { method: 'DELETE' }),
  },
  teacher: {
    register: (payload) => request('/api/teacher/register', { method: 'POST', body: payload }),
    login: (payload) => request('/api/teacher/login', { method: 'POST', body: payload }),
    logout: () => request('/api/teacher/logout', { method: 'POST' }),
    me: () => request('/api/teacher/me'),
    password: (payload) => request('/api/teacher/password', { method: 'PUT', body: payload }),
    overview: () => request('/api/teacher/overview'),
    presence: () => request('/api/teacher/presence'),
    classes: {
      list: () => request('/api/teacher/classes'),
      create: (payload) => request('/api/teacher/classes', { method: 'POST', body: payload }),
      detail: (id) => request(`/api/teacher/classes/${id}`),
      update: (id, payload) => request(`/api/teacher/classes/${id}`, { method: 'PATCH', body: payload }),
      remove: (id) => request(`/api/teacher/classes/${id}`, { method: 'DELETE' }),
      refreshCode: (id) => request(`/api/teacher/classes/${id}/code`, { method: 'POST' }),
      removeStudent: (id, studentId) => request(`/api/teacher/classes/${id}/students/${studentId}`, { method: 'DELETE' }),
      resetStudentPassword: (id, studentId, password = '') => request(
        `/api/teacher/classes/${id}/students/${studentId}/password`,
        { method: 'POST', body: { password } },
      ),
      rosterCsv: (id) => downloadFile(`/api/teacher/classes/${id}/roster.csv`, '学生名单.csv'),
      importRoster: (id, form) => request(`/api/teacher/classes/${id}/roster`, {
        method: 'POST', body: form, form: true,
      }),
      exportCsv: (id) => downloadFile(`/api/teacher/classes/${id}/export.csv`, '班级成绩.csv'),
      exportReport: (id) => downloadFile(`/api/teacher/classes/${id}/report.html`, '班级成绩报告.html'),
    },
    assignments: {
      list: (classId = '') => request(classId
        ? `/api/teacher/assignments?class_id=${encodeURIComponent(classId)}`
        : '/api/teacher/assignments'),
      create: (payload) => request('/api/teacher/assignments', { method: 'POST', body: payload }),
      detail: (id) => request(`/api/teacher/assignments/${id}`),
      update: (id, payload) => request(`/api/teacher/assignments/${id}`, { method: 'PATCH', body: payload }),
      remove: (id) => request(`/api/teacher/assignments/${id}`, { method: 'DELETE' }),
      practice: (id, payload) => request(`/api/teacher/assignments/${id}/practice`, { method: 'POST', body: payload }),
      exportCsv: (id) => downloadFile(`/api/teacher/assignments/${id}/export.csv`, '作业明细.csv'),
    },
    studentReport: (studentId) => downloadFile(`/api/teacher/students/${studentId}/report.html`, '学习报告.html'),
    groups: {
      list: () => request('/api/teacher/groups'),
      create: (payload) => request('/api/teacher/groups', { method: 'POST', body: payload }),
      update: (id, payload) => request(`/api/teacher/groups/${id}`, { method: 'PATCH', body: payload }),
      remove: (id) => request(`/api/teacher/groups/${id}`, { method: 'DELETE' }),
      addMember: (id, username) => request(`/api/teacher/groups/${id}/members`, {
        method: 'POST', body: { username },
      }),
      removeMember: (id, teacherId) => request(`/api/teacher/groups/${id}/members/${teacherId}`, {
        method: 'DELETE',
      }),
    },
    audit: {
      list: (limit = 100) => request(`/api/teacher/audit?limit=${encodeURIComponent(limit)}`),
    },
    questions: {
      list: (params = {}) => {
        const query = new URLSearchParams()
        if (params.topic) query.set('topic', params.topic)
        if (params.status) query.set('status', params.status)
        if (params.keyword) query.set('keyword', params.keyword)
        const suffix = query.toString() ? `?${query}` : ''
        return request(`/api/teacher/questions${suffix}`)
      },
      create: (payload) => request('/api/teacher/questions', { method: 'POST', body: payload }),
      generate: (payload) => request('/api/teacher/questions/generate', { method: 'POST', body: payload }),
      approve: (ids) => request('/api/teacher/questions/approve', { method: 'POST', body: { ids } }),
      update: (id, payload) => request(`/api/teacher/questions/${id}`, { method: 'PUT', body: payload }),
      remove: (id) => request(`/api/teacher/questions/${id}`, { method: 'DELETE' }),
    },
    submissions: {
      get: (id) => request(`/api/teacher/submissions/${id}`),
      grade: (id, payload) => request(`/api/teacher/submissions/${id}`, { method: 'PATCH', body: payload }),
      regradeAi: (id) => request(`/api/teacher/submissions/${id}/regrade-ai`, { method: 'POST' }),
      downloadFile: (id, fileId, name) => downloadFile(`/api/teacher/submissions/${id}/files/${fileId}`, name || '作业附件'),
    },
  },
  student: {
    login: (payload) => request('/api/student/login', { method: 'POST', body: payload }),
    join: (payload) => request('/api/student/join', { method: 'POST', body: payload }),
    tasks: (studentId, token) => request(
      `/api/student/tasks?student_id=${encodeURIComponent(studentId)}&token=${encodeURIComponent(token || '')}`,
    ),
    start: (assignmentId, studentId, token) => request(`/api/student/tasks/${assignmentId}/start`, {
      method: 'POST',
      body: { student_id: studentId, token },
    }),
    result: (assignmentId, studentId, token) => request(
      `/api/student/tasks/${assignmentId}/result?student_id=${encodeURIComponent(studentId)}&token=${encodeURIComponent(token || '')}`,
    ),
    timeline: (studentId, token) => request(
      `/api/student/timeline?student_id=${encodeURIComponent(studentId)}&token=${encodeURIComponent(token || '')}`,
    ),
    submit: (assignmentId, studentId, token, answers) => request(`/api/student/tasks/${assignmentId}/submit`, {
      method: 'POST',
      body: { student_id: studentId, token, answers },
    }),
    submitFile: (assignmentId, studentId, token, file, note = '') => {
      const form = new FormData()
      form.append('student_id', studentId)
      form.append('token', token)
      form.append('note', note)
      form.append('file', file)
      return request(`/api/student/tasks/${assignmentId}/submit-file`, {
        method: 'POST', body: form, form: true,
      })
    },
    fileUrl: (submissionId, fileId, studentId, token) => (
      `/api/student/submissions/${submissionId}/files/${fileId}`
      + `?student_id=${encodeURIComponent(studentId)}&token=${encodeURIComponent(token || '')}`
    ),
  },
}
