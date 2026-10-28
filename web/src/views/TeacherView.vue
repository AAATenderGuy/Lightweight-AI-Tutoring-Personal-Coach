<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { clearTeacherSession, loadTeacher, notify, state } from '../store'
import { debounce, openStream } from '../realtime'
import Icon from '../components/Icon.vue'
import TeacherLogin from '../components/TeacherLogin.vue'
import AssignmentDialog from '../components/AssignmentDialog.vue'
import AssignmentDetail from '../components/AssignmentDetail.vue'
import RosterDialog from '../components/RosterDialog.vue'
import GroupDialog from '../components/GroupDialog.vue'
import QuestionBankDialog from '../components/QuestionBankDialog.vue'

const tabs = [
  { id: 'overview', label: '概览' },
  { id: 'classes', label: '班级' },
  { id: 'assignments', label: '作业' },
  { id: 'reports', label: '报告' },
]

const tab = ref('overview')
const checking = ref(true)
const teacher = computed(() => state.teacher.profile)

const overview = ref(null)
const classes = ref([])
const groups = ref([])
const groupsOpen = ref(false)
const bankOpen = ref(false)
const assignments = ref([])
const selectedClassId = ref('')
const classDetail = ref(null)
const selectedAssignmentId = ref('')
const assignmentDetail = ref(null)
const assignmentFilter = ref('')
const reportClassId = ref('')

const loading = reactive({
  overview: false,
  classes: false,
  classDetail: false,
  assignments: false,
  assignment: false,
})

const createClassOpen = ref(false)
const rosterOpen = ref(false)
const pwdInfo = ref(null)
const classForm = reactive({ name: '', subject: '', grade: '', group_id: '' })
const creatingClass = ref(false)
const pwdOpen = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '' })
const pwdBusy = ref(false)

const dialog = reactive({ open: false, mode: 'create', target: null, focus: [] })

const filteredAssignments = computed(() =>
  assignments.value.filter((item) => !assignmentFilter.value || item.class_id === assignmentFilter.value),
)

function canManageGroup(group) {
  return teacher.value?.role === 'owner' || group.owner_id === teacher.value?.id
}

const manageableGroups = computed(() => groups.value.filter(canManageGroup))

function groupName(id) {
  return groups.value.find((item) => item.id === id)?.name || '教研组'
}

/** 侧栏按教研组分组：组内班级在上，个人班级垫底。 */
const classSections = computed(() => {
  const sections = []
  const index = new Map()
  for (const item of classes.value) {
    const key = item.group_id || ''
    if (!index.has(key)) {
      const section = { id: key, name: key ? groupName(key) : '个人班级', items: [] }
      index.set(key, section)
      sections.push(section)
    }
    index.get(key).items.push(item)
  }
  return sections.sort((a, b) => (a.id ? 0 : 1) - (b.id ? 0 : 1))
})

const assignmentReadonly = computed(() => {
  const detail = assignmentDetail.value
  if (!detail) return false
  return Boolean(classes.value.find((item) => item.id === detail.class_id)?.readonly)
})

const reportDetail = computed(() => {
  if (!reportClassId.value || !classDetail.value) return null
  return classDetail.value.class.id === reportClassId.value ? classDetail.value : null
})

const reportStudents = computed(() => {
  const detail = reportDetail.value
  if (!detail) return []
  const total = detail.assignments?.length || 0
  return (detail.students || []).map((student) => ({
    ...student,
    completion: total ? Math.round((student.submitted / total) * 100) : 0,
    total,
  }))
})

const canReport = computed(() => Boolean(reportDetail.value) && reportDetail.value.can_view_grades === true)

/** 组内普通教师只能看班级结构，成绩由后端脱敏，前端同步隐藏相关入口。 */
const canViewGrades = computed(() => classDetail.value?.can_view_grades === true)

// ---------------------------------------------------------------- 实时
const live = ref('off')
const onlineIds = ref(new Set())
let stream = null
let openedOnce = false

const onlineCount = computed(() => {
  const students = classDetail.value?.students || []
  return students.filter((item) => onlineIds.value.has(item.id)).length
})

async function refreshPresence() {
  if (!selectedClassId.value) return
  try {
    const data = await api.teacher.presence()
    onlineIds.value = new Set(data.items?.[selectedClassId.value] || [])
  } catch {
    /* 在线名单只是增强信息，失败不影响主流程 */
  }
}

/** 只重拉当前标签页真正在显示的数据，避免一条事件打五个接口。 */
const refreshSoon = debounce(() => {
  if (tab.value === 'overview') return loadOverview()
  if (tab.value === 'classes') {
    return Promise.all([
      loadClasses(),
      selectedClassId.value ? loadClassDetail(selectedClassId.value) : Promise.resolve(),
    ])
  }
  if (tab.value === 'assignments') {
    return Promise.all([
      loadAssignments(),
      loadOverview(),
      selectedAssignmentId.value ? loadAssignmentDetail(selectedAssignmentId.value) : Promise.resolve(),
    ])
  }
  return loadOverview()
}, 400)

function handleRealtime(event) {
  if (event.type === 'unauthorized') {
    clearTeacherSession()
    notify('登录已过期，请重新登录', 'error')
    return
  }
  if (event.type === 'student_online') {
    const next = new Set(onlineIds.value)
    next.add(event.student_id)
    onlineIds.value = next
    return
  }
  if (event.type === 'student_offline') {
    const next = new Set(onlineIds.value)
    next.delete(event.student_id)
    onlineIds.value = next
    return
  }
  if (event.type === 'student_joined' && !event.returning) {
    notify(`${event.name} 加入了班级`)
  } else if (event.type === 'submission_saved') {
    notify(`${event.student_name} 提交了《${event.assignment_title}》 ${score(event.score)} 分`)
  }
  refreshSoon()
}

watch(teacher, (value) => {
  stream?.close()
  stream = null
  live.value = 'off'
  openedOnce = false
  if (!value) return
  stream = openStream('/api/teacher/stream', {
    onStatus: (status) => { live.value = status },
    onOpen: () => {
      // 首次连接由下面的 onMounted 负责加载；重连时整体补一次。
      if (openedOnce) refreshAll()
      openedOnce = true
    },
    onEvent: handleRealtime,
  })
}, { immediate: true })

onUnmounted(() => stream?.close())

onMounted(async () => {
  await loadTeacher()
  checking.value = false
  if (teacher.value) await refreshAll()
})

async function refreshAll() {
  await Promise.all([loadOverview(), loadClasses(), loadAssignments(), loadGroups()])
  if (selectedClassId.value) await loadClassDetail(selectedClassId.value)
  if (reportClassId.value) await ensureReportDetail()
  if (selectedAssignmentId.value) await loadAssignmentDetail(selectedAssignmentId.value)
}

async function loadGroups() {
  try {
    groups.value = (await api.teacher.groups.list()).items || []
  } catch {
    groups.value = []
  }
}

async function loadOverview() {
  loading.overview = true
  try {
    overview.value = await api.teacher.overview()
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    loading.overview = false
  }
}

async function loadClasses() {
  loading.classes = true
  try {
    const data = await api.teacher.classes.list()
    classes.value = data.items || []
    if (!classes.value.length) {
      selectedClassId.value = ''
      classDetail.value = null
      reportClassId.value = ''
      return
    }
    if (!selectedClassId.value || !classes.value.some((item) => item.id === selectedClassId.value)) {
      selectedClassId.value = classes.value[0].id
    }
    if (!reportClassId.value) reportClassId.value = selectedClassId.value
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    loading.classes = false
  }
}

// 快速切换班级 / 作业时，慢的旧请求回来会把新数据覆盖掉；用自增序号丢弃过期响应。
let detailSeq = 0

async function loadClassDetail(classId) {
  if (!classId) return
  const seq = ++detailSeq
  loading.classDetail = true
  try {
    const data = await api.teacher.classes.detail(classId)
    if (seq !== detailSeq) return
    classDetail.value = data
    refreshPresence()
  } catch (error) {
    if (seq !== detailSeq) return
    classDetail.value = null
    notify(error.message, 'error')
  } finally {
    if (seq === detailSeq) loading.classDetail = false
  }
}

async function selectClass(classId) {
  selectedClassId.value = classId
  await loadClassDetail(classId)
}

async function createClass() {
  if (!classForm.name.trim()) {
    notify('请填写班级名称')
    return
  }
  creatingClass.value = true
  try {
    const data = await api.teacher.classes.create({
      name: classForm.name.trim(),
      subject: classForm.subject.trim(),
      grade: classForm.grade.trim(),
      group_id: classForm.group_id,
    })
    createClassOpen.value = false
    classForm.name = ''
    classForm.subject = ''
    classForm.grade = ''
    classForm.group_id = ''
    await loadClasses()
    await selectClass(data.class.id)
    notify(`班级已创建，邀请码 ${data.class.code}`)
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    creatingClass.value = false
  }
}

async function refreshCode() {
  if (!selectedClassId.value) return
  if (!window.confirm('重置后旧邀请码立即失效，已加入的学生不受影响。继续？')) return
  try {
    const data = await api.teacher.classes.refreshCode(selectedClassId.value)
    await Promise.all([loadClasses(), loadClassDetail(selectedClassId.value)])
    notify(`新邀请码：${data.class.code}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function toggleArchive() {
  const detail = classDetail.value
  if (!detail) return
  try {
    await api.teacher.classes.update(detail.class.id, { archived: !detail.class.archived })
    await Promise.all([loadClasses(), loadClassDetail(detail.class.id)])
    notify(detail.class.archived ? '班级已恢复' : '班级已归档')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function changeClassGroup(event) {
  const detail = classDetail.value
  if (!detail) return
  const groupId = typeof event === 'string' ? event : event.target.value
  try {
    await api.teacher.classes.update(detail.class.id, { group_id: groupId })
    await Promise.all([loadClasses(), loadClassDetail(detail.class.id)])
    notify(groupId ? `已挂到「${groupName(groupId)}」` : '班级已回到个人班级')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function removeClass() {
  const detail = classDetail.value
  if (!detail) return
  if (!window.confirm(`删除班级「${detail.class.name}」？该班的作业、学生和成绩会一起删除，不可恢复。`)) return
  try {
    await api.teacher.classes.remove(detail.class.id)
    selectedClassId.value = ''
    classDetail.value = null
    if (reportClassId.value === detail.class.id) reportClassId.value = ''
    await refreshAll()
    notify('班级已删除')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function removeStudent(student) {
  if (!selectedClassId.value) return
  if (!window.confirm(`把「${student.name}」移出班级？该学生的提交记录会一起删除。`)) return
  try {
    await api.teacher.classes.removeStudent(selectedClassId.value, student.id)
    await Promise.all([loadClassDetail(selectedClassId.value), loadClasses()])
    notify('已移出班级')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function openRoster() {
  if (!classDetail.value) return
  rosterOpen.value = true
}

async function onRosterImported() {
  if (!selectedClassId.value) return
  await Promise.all([loadClassDetail(selectedClassId.value), loadClasses()])
}

async function resetPassword(student) {
  if (!selectedClassId.value) return
  if (!window.confirm(`重置「${student.name}」的登录密码？旧密码会立即失效。`)) return
  try {
    const data = await api.teacher.classes.resetStudentPassword(selectedClassId.value, student.id)
    pwdInfo.value = { name: student.name, number: student.number, password: data.password }
    await loadClassDetail(selectedClassId.value)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function exportRoster() {
  if (!selectedClassId.value) return
  try {
    const name = await api.teacher.classes.rosterCsv(selectedClassId.value)
    notify(`已导出 ${name}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function exportClass(classId) {
  if (!classId) return
  try {
    const name = await api.teacher.classes.exportReport(classId)
    notify(`已生成 ${name}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function exportClassCsv(classId) {
  if (!classId) return
  try {
    const name = await api.teacher.classes.exportCsv(classId)
    notify(`已导出 ${name}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function exportAssignment() {
  if (!assignmentDetail.value) return
  try {
    const name = await api.teacher.assignments.exportCsv(assignmentDetail.value.id)
    notify(`已导出 ${name}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function downloadReport(student) {
  try {
    const name = await api.teacher.studentReport(student.id)
    notify(`已生成 ${name}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function loadAssignments() {
  loading.assignments = true
  try {
    const data = await api.teacher.assignments.list()
    assignments.value = data.items || []
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    loading.assignments = false
  }
}

async function selectAssignment(assignmentId) {
  selectedAssignmentId.value = assignmentId
  await loadAssignmentDetail(assignmentId)
}

async function loadAssignmentDetail(assignmentId) {
  const seq = ++detailSeq
  loading.assignment = true
  try {
    const data = await api.teacher.assignments.detail(assignmentId)
    if (seq !== detailSeq) return
    assignmentDetail.value = data
  } catch (error) {
    if (seq !== detailSeq) return
    assignmentDetail.value = null
    notify(error.message, 'error')
  } finally {
    if (seq === detailSeq) loading.assignment = false
  }
}

async function openAssignment(assignmentId) {
  tab.value = 'assignments'
  await selectAssignment(assignmentId)
}

async function toggleAssignment() {
  const detail = assignmentDetail.value
  if (!detail) return
  try {
    await api.teacher.assignments.update(detail.id, { closed: !detail.closed })
    await Promise.all([
      loadAssignmentDetail(detail.id),
      loadAssignments(),
      loadOverview(),
      selectedClassId.value ? loadClassDetail(selectedClassId.value) : Promise.resolve(),
    ])
    notify(detail.closed ? '作业已重新开放' : '作业已关闭，学生不能再提交')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function removeAssignment() {
  const detail = assignmentDetail.value
  if (!detail) return
  try {
    await api.teacher.assignments.remove(detail.id)
    selectedAssignmentId.value = ''
    assignmentDetail.value = null
    await refreshAll()
    notify('作业已删除')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function openCreateDialog() {
  dialog.mode = 'create'
  dialog.target = null
  dialog.focus = []
  dialog.open = true
}

async function publishAssignment(item) {
  try {
    await api.teacher.assignments.update(item.id, { draft: false })
    notify(`《${item.title}》已发布，学生端现在可以看到了`)
    await loadAssignments()
    if (selectedClassId.value) await loadClassDetail(selectedClassId.value)
  } catch (error) {
    notify(error.message, 'error')
  }
}

function openPractice(target, points = []) {
  if (!target?.id) return
  dialog.mode = 'practice'
  dialog.target = target
  dialog.focus = points.filter(Boolean)
  dialog.open = true
}

async function onCreated(assignment) {
  dialog.open = false
  tab.value = 'assignments'
  await refreshAll()
  await selectAssignment(assignment.id)
}

async function ensureReportDetail() {
  if (!reportClassId.value) return
  if (reportClassId.value !== selectedClassId.value) selectedClassId.value = reportClassId.value
  if (!classDetail.value || classDetail.value.class.id !== reportClassId.value) {
    await loadClassDetail(reportClassId.value)
  }
}

async function switchTab(next) {
  tab.value = next
  if (next === 'overview') await loadOverview()
  if (next === 'classes' && selectedClassId.value) await loadClassDetail(selectedClassId.value)
  if (next === 'assignments') {
    await loadAssignments()
    if (selectedAssignmentId.value) await loadAssignmentDetail(selectedAssignmentId.value)
  }
  if (next === 'reports') {
    if (!reportClassId.value && classes.value.length) reportClassId.value = classes.value[0].id
    await ensureReportDetail()
  }
}

async function onReportClassChange() {
  await ensureReportDetail()
}

async function copy(text, message) {
  try {
    await navigator.clipboard.writeText(text)
    notify(message)
  } catch {
    window.prompt('复制下面的内容：', text)
  }
}

function inviteLink(code) {
  return `${window.location.origin}/?join=${code}`
}

async function logout() {
  try {
    await api.teacher.logout()
  } catch {
    /* 即使请求失败也清掉本地登录态 */
  }
  clearTeacherSession()
  overview.value = null
  classes.value = []
  assignments.value = []
  classDetail.value = null
  assignmentDetail.value = null
  notify('已退出登录')
}

async function changePassword() {
  if (!pwdForm.old_password || pwdForm.new_password.length < 6) {
    notify('新密码至少 6 位')
    return
  }
  pwdBusy.value = true
  try {
    await api.teacher.password({ old_password: pwdForm.old_password, new_password: pwdForm.new_password })
    pwdOpen.value = false
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    notify('密码已更新')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    pwdBusy.value = false
  }
}

function pct(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function score(value) {
  // 组员看不到分数时后端返回 null，这里直接显示占位符，避免误读成 0 分。
  if (value === null || value === undefined || value === '') return '—'
  return Math.round((Number(value) || 0) * 100)
}

function formatTime(ts) {
  if (!ts) return '未设置'
  return new Date(ts * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function dueText(item) {
  if (!item.due_at) return '不限时'
  const overdue = item.due_at < Date.now() / 1000
  return `${overdue ? '已截止' : '截止'} ${formatTime(item.due_at)}`
}

function kindLabel(kind) {
  return kind === 'quiz' ? '随堂测验' : '课后作业'
}
</script>

<template>
  <section class="page">
    <div v-if="checking" class="content">
      <div class="loading-stage"><div class="spinner" /><strong>正在确认登录状态</strong></div>
    </div>

    <TeacherLogin v-else-if="!teacher" @done="refreshAll" />

    <template v-else>
      <header class="page-head teacher-head">
        <div>
          <h1>教师工作台</h1>
          <p>建班、发邀请码、布置随堂测验与课后作业，并随时看到每个学生的完成情况。</p>
        </div>
        <div class="page-actions">
          <span v-if="live === 'live'" class="live-pill" title="学生加入、交卷会实时出现在这里">
            <span class="dot live" />实时
          </span>
          <span v-else-if="live === 'offline'" class="live-pill" title="正在重新连接">
            <span class="dot" />重连中
          </span>
          <button class="btn btn-sm" type="button" @click="bankOpen = true">
            <Icon name="book" :size="13" />
            题库
          </button>
          <button class="btn btn-sm" type="button" @click="groupsOpen = true">
            <Icon name="users" :size="13" />
            教研组
          </button>
          <button class="btn btn-sm" type="button" @click="pwdOpen = true">修改密码</button>
          <span class="teacher-badge">
            <span class="avatar">{{ (teacher.name || teacher.username).slice(0, 1) }}</span>
            {{ teacher.name || teacher.username }}
          </span>
          <button class="btn btn-sm btn-ghost" type="button" @click="logout">退出</button>
        </div>
      </header>

      <div class="tabs-bar">
        <div class="segmented tabs">
          <button
            v-for="item in tabs"
            :key="item.id"
            type="button"
            :class="{ active: tab === item.id }"
            @click="switchTab(item.id)"
          >
            {{ item.label }}
          </button>
        </div>
        <span class="spacer" />
        <span v-if="state.settings.demo" class="chip">演示模式 · 出题与批改走本地规则</span>
      </div>

      <div class="content teacher-content">
        <!-- 概览 -->
        <div v-if="tab === 'overview'" class="wide-lg">
          <div class="stat-grid stat-grid-4">
            <div class="stat">
              <div class="value">{{ overview?.stats.classes ?? 0 }}</div>
              <div class="label">班级</div>
            </div>
            <div class="stat">
              <div class="value">{{ overview?.stats.students ?? 0 }}</div>
              <div class="label">学生</div>
            </div>
            <div class="stat">
              <div class="value">{{ overview?.stats.open ?? 0 }}</div>
              <div class="label">进行中作业</div>
            </div>
            <div class="stat">
              <div class="value">{{ pct(overview?.stats.submission_rate) }}</div>
              <div class="label">
                总体提交率<template v-if="overview?.stats.avg_score != null"> · 平均 {{ score(overview?.stats.avg_score) }} 分</template>
              </div>
            </div>
          </div>

          <div v-if="!classes.length" class="empty-card">
            <h2>先建一个班级</h2>
            <p>班级创建后会得到一个 6 位邀请码，学生输入邀请码和姓名即可加入，不需要注册账号。</p>
            <button class="btn btn-primary" type="button" @click="createClassOpen = true">
              <Icon name="plus" :size="14" />
              新建班级
            </button>
          </div>

          <template v-else>
            <div class="overview-grid">
              <div class="panel">
                <div class="panel-head">
                  <h2>待处理作业</h2>
                  <span class="small muted">{{ overview?.upcoming.length || 0 }} 份进行中</span>
                </div>
                <div v-if="!overview?.upcoming.length" class="panel-empty">所有作业都已截止或关闭。</div>
                <div v-else class="todo-list">
                  <button
                    v-for="item in overview.upcoming"
                    :key="item.id"
                    class="todo-row"
                    type="button"
                    @click="openAssignment(item.id)"
                  >
                    <div class="todo-main">
                      <div class="todo-title">{{ item.title }}</div>
                      <div class="small muted">
                        {{ item.class_name }} · {{ kindLabel(item.kind) }} · {{ dueText(item) }}
                      </div>
                    </div>
                    <div class="todo-side">
                      <span class="chip" :class="{ accent: item.missing === 0 }">
                        {{ item.missing === 0 ? '已交齐' : `${item.missing} 人未交` }}
                      </span>
                      <span class="small muted">{{ item.submitted }}/{{ item.total }}</span>
                    </div>
                  </button>
                </div>
              </div>

              <div class="panel">
                <div class="panel-head">
                  <h2>薄弱知识点</h2>
                  <span class="small muted">按错误率排序</span>
                </div>
                <div v-if="!overview?.weak_points.length" class="panel-empty">
                  还没有错题数据。学生提交作业后这里会自动汇总。
                </div>
                <div v-else class="weak-list">
                  <div v-for="item in overview.weak_points" :key="item.point" class="weak-row">
                    <div class="weak-main">
                      <div class="weak-name">{{ item.point }}</div>
                      <div class="small muted">
                        答错 {{ item.wrong }} / {{ item.attempts }} 次
                        <template v-if="item.assignment_title"> · 来自《{{ item.assignment_title }}》</template>
                      </div>
                      <div class="bar error" style="margin: 6px 0 0"><span :style="{ width: pct(item.error_rate) }" /></div>
                    </div>
                    <button
                      class="btn btn-sm"
                      type="button"
                      @click="openPractice({ id: item.assignment_id, title: item.assignment_title }, [item.point])"
                    >
                      补练
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div class="panel" style="margin-top: 16px">
              <div class="panel-head">
                <h2>最近提交</h2>
                <button class="btn btn-sm btn-ghost" type="button" @click="switchTab('assignments')">
                  全部作业
                  <Icon name="arrow" :size="12" />
                </button>
              </div>
              <div v-if="!overview?.recent.length" class="panel-empty">还没有学生提交。</div>
              <table v-else class="data-table">
                <thead>
                  <tr><th>学生</th><th>作业</th><th>班级</th><th class="num">得分</th><th>时间</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(item, index) in overview.recent" :key="index">
                    <td>{{ item.student_name }}</td>
                    <td>{{ item.assignment_title }}</td>
                    <td class="muted">{{ item.class_name }}</td>
                    <td class="num"><b>{{ score(item.score) }}</b></td>
                    <td class="muted">{{ formatTime(item.submitted_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>

        <!-- 班级 -->
        <div v-else-if="tab === 'classes'" class="t-split">
          <aside class="class-list">
            <button class="btn btn-primary btn-block" type="button" @click="createClassOpen = true">
              <Icon name="plus" :size="14" />
              新建班级
            </button>
            <div v-if="loading.classes && !classes.length" class="panel-empty">正在读取班级…</div>
            <div v-else-if="!classes.length" class="panel-empty">还没有班级。</div>
            <template v-else>
              <div v-for="section in classSections" :key="section.id || 'personal'">
                <div class="small muted class-section-title">{{ section.name }}</div>
                <button
                  v-for="item in section.items"
                  :key="item.id"
                  class="class-item"
                  :class="{ active: selectedClassId === item.id }"
                  type="button"
                  @click="selectClass(item.id)"
                >
                  <div class="row" style="justify-content: space-between; gap: 8px">
                    <strong>{{ item.name }}</strong>
                    <span v-if="item.readonly" class="chip accent">只读</span>
                    <span v-else-if="item.archived" class="chip">已归档</span>
                  </div>
                  <div class="small muted">{{ item.subject || '未填科目' }} · {{ item.student_count }} 人</div>
                  <div class="small muted">邀请码 {{ item.code }} · {{ item.open_count }} 份进行中</div>
                </button>
              </div>
            </template>
          </aside>

          <div class="panel class-detail">
            <div v-if="loading.classDetail && !classDetail" class="loading-stage" style="border: 0">
              <div class="spinner" /><strong>正在读取班级</strong>
            </div>
            <div v-else-if="!classDetail" class="empty-state"><p>在左侧选择一个班级。</p></div>
            <template v-else>
              <div class="detail-head">
                <div>
                  <div class="row" style="gap: 6px; flex-wrap: wrap; margin-bottom: 4px">
                    <span class="chip">{{ classDetail.class.student_count }} 名学生</span>
                    <span class="chip">{{ classDetail.class.assignment_count }} 份作业</span>
                    <span v-if="classDetail.class.readonly" class="chip accent">教研组共享 · 只读</span>
                    <span v-else-if="classDetail.class.group_id" class="chip">
                      {{ groupName(classDetail.class.group_id) }}
                    </span>
                    <span v-if="classDetail.class.archived" class="chip">已归档</span>
                  </div>
                  <h2 class="detail-title">{{ classDetail.class.name }}</h2>
                  <p class="small muted" style="margin: 4px 0 0">
                    {{ classDetail.class.subject || '未填科目' }}
                    <template v-if="classDetail.class.grade"> · {{ classDetail.class.grade }}</template>
                    · 创建于 {{ formatTime(classDetail.class.created_at) }}
                  </p>
                  <div v-if="!classDetail.class.readonly && manageableGroups.length" class="row" style="gap: 8px; margin-top: 8px">
                    <span class="small muted">教研组</span>
                    <select class="select" style="width: 180px" :value="classDetail.class.group_id" @change="changeClassGroup">
                      <option value="">不归属教研组</option>
                      <option v-for="item in manageableGroups" :key="item.id" :value="item.id">{{ item.name }}</option>
                    </select>
                  </div>
                </div>
                <div class="detail-actions">
                  <button v-if="!classDetail.class.readonly" class="btn btn-sm" type="button" @click="openRoster">
                    <Icon name="users" :size="13" />
                    导入名单
                  </button>
                  <button v-if="canViewGrades" class="btn btn-sm" type="button" @click="exportClass(classDetail.class.id)">
                    <Icon name="download" :size="13" />
                    成绩报告
                  </button>
                  <button v-if="!classDetail.class.readonly" class="btn btn-sm" type="button" @click="toggleArchive">
                    {{ classDetail.class.archived ? '恢复班级' : '归档' }}
                  </button>
                  <button
                    v-if="!classDetail.class.readonly"
                    class="btn btn-sm btn-danger"
                    type="button"
                    @click="removeClass"
                  >
                    删除班级
                  </button>
                </div>
              </div>

              <div class="invite-card">
                <div>
                  <div class="small muted">班级邀请码</div>
                  <div class="invite-code">{{ classDetail.class.code }}</div>
                  <div class="small muted">
                    学生在「班级」页输入邀请码 + 姓名即可加入；也可以直接发链接。
                  </div>
                </div>
                <div class="invite-actions">
                  <button class="btn btn-sm" type="button" @click="copy(classDetail.class.code, '邀请码已复制')">
                    <Icon name="copy" :size="13" />
                    复制邀请码
                  </button>
                  <button
                    class="btn btn-sm"
                    type="button"
                    @click="copy(inviteLink(classDetail.class.code), '邀请链接已复制')"
                  >
                    <Icon name="link" :size="13" />
                    复制邀请链接
                  </button>
                  <button
                    v-if="!classDetail.class.readonly"
                    class="btn btn-sm btn-ghost"
                    type="button"
                    @click="refreshCode"
                  >
                    重置
                  </button>
                </div>
              </div>

              <div class="stat-grid stat-grid-3" style="margin-top: 16px">
                <div class="stat">
                  <div class="value">{{ classDetail.stats.students }}</div>
                  <div class="label">学生</div>
                </div>
                <div class="stat">
                  <div class="value">{{ classDetail.stats.submissions }}</div>
                  <div class="label">累计提交</div>
                </div>
                <div v-if="canViewGrades" class="stat">
                  <div class="value">{{ score(classDetail.stats.avg_score) }}<span class="unit">分</span></div>
                  <div class="label">班级平均分</div>
                </div>
              </div>

              <div class="section">
                <div class="section-head">
                  <h2>学生名单</h2>
                  <div class="row" style="gap: 8px; align-items: center">
                    <span class="small muted">
                      {{ classDetail.students.length }} 人<template v-if="onlineCount"> · {{ onlineCount }} 人在线</template>
                    </span>
                    <button class="btn btn-sm btn-ghost" type="button" @click="exportRoster">导出名单</button>
                  </div>
                </div>
                <div v-if="!classDetail.students.length" class="panel-empty">
                  还没有学生加入。把邀请码发给学生，他们输入后会立刻出现在这里。
                </div>
                <table v-else class="data-table">
                  <thead>
                    <tr>
                      <th>姓名</th><th>学号</th><th>密码</th>
                      <th class="num">已交</th><th v-if="canViewGrades" class="num">平均分</th>
                      <th>最后登录</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="student in classDetail.students" :key="student.id">
                      <td>
                        <span class="student-name">
                          <span v-if="onlineIds.has(student.id)" class="dot live" title="正在查看班级" />
                          {{ student.name }}
                        </span>
                      </td>
                      <td class="muted">{{ student.number || '—' }}</td>
                      <td>
                        <span v-if="student.has_password" class="chip accent">已设置</span>
                        <span v-else class="chip">未设置</span>
                      </td>
                      <td class="num">{{ student.submitted }}</td>
                      <td v-if="canViewGrades" class="num">{{ student.submitted ? score(student.avg_score) : '—' }}</td>
                      <td class="muted">{{ student.last_login ? formatTime(student.last_login) : '—' }}</td>
                      <td class="row-actions">
                        <button
                          v-if="canViewGrades"
                          class="btn btn-sm btn-ghost"
                          type="button"
                          @click="downloadReport(student)"
                        >
                          报告
                        </button>
                        <template v-if="!classDetail.class.readonly">
                          <button class="btn btn-sm btn-ghost" type="button" @click="resetPassword(student)">重置密码</button>
                          <button class="btn btn-sm btn-ghost" type="button" @click="removeStudent(student)">移出</button>
                        </template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div class="section">
                <div class="section-head">
                  <h2>本班作业</h2>
                  <button
                    v-if="!classDetail.class.readonly"
                    class="btn btn-sm"
                    type="button"
                    @click="openCreateDialog"
                  >
                    <Icon name="plus" :size="13" />
                    布置作业
                  </button>
                </div>
                <div v-if="!classDetail.assignments.length" class="panel-empty">还没有布置作业。</div>
                <div v-else class="mini-list">
                  <button
                    v-for="item in classDetail.assignments"
                    :key="item.id"
                    class="mini-row"
                    type="button"
                    @click="openAssignment(item.id)"
                  >
                    <div class="mini-main">
                      <div class="todo-title">{{ item.title }}</div>
                      <div class="small muted">
                        {{ kindLabel(item.kind) }} · {{ dueText(item) }} · 已交 {{ item.submitted }}/{{ item.total }}
                      </div>
                    </div>
                    <div class="mini-bar">
                      <div class="bar"><span :style="{ width: pct(item.completion) }" /></div>
                      <span v-if="canViewGrades" class="small muted">{{ score(item.avg_score) }} 分</span>
                    </div>
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- 作业 -->
        <div v-else-if="tab === 'assignments'" class="t-split t-split-wide">
          <aside class="as-list">
            <div class="as-list-head">
              <select v-model="assignmentFilter" class="select" style="flex: 1">
                <option value="">全部班级</option>
                <option v-for="item in classes" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
              <button class="icon-btn" type="button" aria-label="刷新" @click="loadAssignments">
                <Icon name="refresh" :size="15" />
              </button>
            </div>
            <button class="btn btn-primary btn-block" type="button" @click="openCreateDialog">
              <Icon name="plus" :size="14" />
              布置新作业
            </button>
            <div v-if="loading.assignments && !assignments.length" class="panel-empty">正在读取作业…</div>
            <div v-else-if="!filteredAssignments.length" class="panel-empty">这里还没有作业。</div>
            <button
              v-for="item in filteredAssignments"
              :key="item.id"
              class="as-card"
              :class="{ active: selectedAssignmentId === item.id }"
              type="button"
              @click="selectAssignment(item.id)"
            >
              <div class="row" style="justify-content: space-between; gap: 8px; align-items: flex-start">
                <strong>{{ item.title }}</strong>
                <span class="chip">{{ kindLabel(item.kind) }}</span>
                <span v-if="item.submission_mode === 'file'" class="chip accent">文件</span>
                <span v-if="item.draft" class="chip accent">草稿</span>
              </div>
              <div class="small muted">{{ item.class_name }} · {{ item.draft ? '未发布' : dueText(item) }}</div>
              <template v-if="!item.draft">
                <div class="bar" style="margin: 8px 0 5px"><span :style="{ width: pct(item.completion) }" /></div>
                <div class="small muted">
                  已交 {{ item.submitted }}/{{ item.total }}
                  <template v-if="item.avg_score != null"> · 平均 {{ score(item.avg_score) }} 分</template>
                </div>
              </template>
              <div v-else class="row" style="margin-top: 8px">
                <button class="btn btn-sm btn-primary" type="button" @click.stop="publishAssignment(item)">
                  发布到班级
                </button>
              </div>
            </button>
          </aside>

          <AssignmentDetail
            :detail="assignmentDetail"
            :loading="loading.assignment"
            :readonly="assignmentReadonly"
            @refresh="selectedAssignmentId && loadAssignmentDetail(selectedAssignmentId)"
            @export="exportAssignment"
            @toggle="toggleAssignment"
            @remove="removeAssignment"
            @practice="(points) => openPractice(assignmentDetail, points)"
          />
        </div>

        <!-- 报告 -->
        <div v-else class="wide-lg">
          <div class="panel">
            <div class="panel-head" style="flex-wrap: wrap; gap: 10px">
              <div>
                <h2>学生报告</h2>
                <p class="small muted" style="margin: 2px 0 0">
                  整班导出为带图表的 HTML 报告，单个学生导出为个人学习报告；两者都能直接打印或另存为 PDF。
                </p>
              </div>
              <div class="row" style="gap: 8px; flex-wrap: wrap">
                <select v-model="reportClassId" class="select" style="width: 180px" @change="onReportClassChange">
                  <option value="" disabled>选择班级</option>
                  <option v-for="item in classes" :key="item.id" :value="item.id">{{ item.name }}</option>
                </select>
                <button class="btn btn-sm" type="button" :disabled="!canReport" @click="exportClass(reportClassId)">
                  <Icon name="download" :size="13" />
                  整班成绩报告
                </button>
                <button
                  class="btn btn-sm btn-ghost"
                  type="button"
                  :disabled="!canReport"
                  title="需要原始表格数据做二次处理时用"
                  @click="exportClassCsv(reportClassId)"
                >
                  CSV
                </button>
              </div>
            </div>

            <div v-if="!classes.length" class="empty-state"><p>还没有班级。</p></div>
            <div v-else-if="!reportDetail" class="panel-empty">正在读取班级数据…</div>
            <div v-else-if="!canReport" class="panel-empty">
              组内班级的成绩与报告只对班级创建者或组长开放。想导出自己班的成绩，请在上方切换到该班级。
            </div>
            <template v-else>
              <div class="stat-grid stat-grid-3" style="margin-top: 14px">
                <div class="stat">
                  <div class="value">{{ reportDetail.stats.students }}</div>
                  <div class="label">学生</div>
                </div>
                <div class="stat">
                  <div class="value">{{ reportDetail.stats.assignments }}</div>
                  <div class="label">作业</div>
                </div>
                <div class="stat">
                  <div class="value">{{ score(reportDetail.stats.avg_score) }}<span class="unit">分</span></div>
                  <div class="label">班级平均分</div>
                </div>
              </div>

              <div v-if="!reportStudents.length" class="panel-empty">这个班还没有学生。</div>
              <table v-else class="data-table" style="margin-top: 14px">
                <thead>
                  <tr>
                    <th>姓名</th><th>学号</th><th class="num">已交 / 应交</th>
                    <th style="width: 120px">完成率</th><th class="num">平均分</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="student in reportStudents" :key="student.id">
                    <td>{{ student.name }}</td>
                    <td class="muted">{{ student.number || '—' }}</td>
                    <td class="num">{{ student.submitted }} / {{ student.total }}</td>
                    <td>
                      <div class="bar" style="margin: 0"><span :style="{ width: `${student.completion}%` }" /></div>
                    </td>
                    <td class="num"><b>{{ student.submitted ? score(student.avg_score) : '—' }}</b></td>
                    <td class="row-actions">
                      <button class="btn btn-sm" type="button" @click="downloadReport(student)">
                        <Icon name="download" :size="13" />
                        学习报告
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>

              <div class="hint-box" style="margin-top: 14px">
                整班报告包含：六项概览指标、成绩分布直方图、平均分趋势折线、作业完成率、
                学生排名、成绩矩阵热力表和薄弱知识点排行。个人报告包含：完成率与平均分、
                每份作业的提交情况、知识点掌握度、错题回顾和下一步建议。
                掌握度按最近表现加权，单次成绩不会直接判定为「已掌握」。
              </div>
            </template>
          </div>
        </div>
      </div>
    </template>

    <!-- 新建班级 -->
    <div v-if="createClassOpen" class="overlay" @mousedown.self="createClassOpen = false">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h2>新建班级</h2>
            <p>创建后会生成一个 6 位邀请码，学生用它加入。</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="createClassOpen = false">
            <Icon name="close" :size="17" />
          </button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label for="class-name">班级名称</label>
            <input id="class-name" v-model="classForm.name" class="input" placeholder="例：高一(3)班" maxlength="40" />
          </div>
          <div class="grid-2">
            <div class="field">
              <label for="class-subject">科目</label>
              <input id="class-subject" v-model="classForm.subject" class="input" placeholder="例：生物" maxlength="40" />
            </div>
            <div class="field">
              <label for="class-grade">年级</label>
              <input id="class-grade" v-model="classForm.grade" class="input" placeholder="例：高一" maxlength="40" />
            </div>
          </div>
          <div v-if="manageableGroups.length" class="field">
            <label for="class-group">归属教研组（可选）</label>
            <select id="class-group" v-model="classForm.group_id" class="select">
              <option value="">不归属教研组</option>
              <option v-for="item in manageableGroups" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
            <span class="small muted">挂到教研组后，组内其他老师可以只读查看这个班。</span>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="createClassOpen = false">取消</button>
          <button class="btn btn-primary" type="button" :disabled="creatingClass" @click="createClass">
            {{ creatingClass ? '创建中…' : '创建班级' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 修改密码 -->
    <div v-if="pwdOpen" class="overlay" @mousedown.self="pwdOpen = false">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h2>修改密码</h2>
            <p>密码只保存在本机，忘记后需要删除 data/teachers 重新创建账号。</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="pwdOpen = false">
            <Icon name="close" :size="17" />
          </button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label for="old-pwd">原密码</label>
            <input id="old-pwd" v-model="pwdForm.old_password" class="input" type="password" autocomplete="current-password" />
          </div>
          <div class="field">
            <label for="new-pwd">新密码</label>
            <input id="new-pwd" v-model="pwdForm.new_password" class="input" type="password" autocomplete="new-password" placeholder="至少 6 位" />
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="pwdOpen = false">取消</button>
          <button class="btn btn-primary" type="button" :disabled="pwdBusy" @click="changePassword">
            {{ pwdBusy ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <RosterDialog
      v-if="rosterOpen && classDetail"
      :klass="classDetail.class"
      @close="rosterOpen = false"
      @imported="onRosterImported"
    />

    <div v-if="pwdInfo" class="overlay" @mousedown.self="pwdInfo = null">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="pwd-info-title">
        <div class="modal-head">
          <div>
            <h2 id="pwd-info-title">新的登录密码</h2>
            <p>{{ pwdInfo.name }}<template v-if="pwdInfo.number"> · {{ pwdInfo.number }}</template></p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="pwdInfo = null">
            <Icon name="close" :size="17" />
          </button>
        </div>
        <div class="modal-body stack">
          <div class="hint-box">这个密码只显示一次，请转告学生。学生用「学号 + 这个密码」登录。</div>
          <div class="invite-code">{{ pwdInfo.password }}</div>
          <div class="row" style="gap: 8px">
            <button class="btn btn-sm" type="button" @click="copy(pwdInfo.password, '密码已复制')">
              <Icon name="copy" :size="13" />
              复制密码
            </button>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-primary" type="button" @click="pwdInfo = null">知道了</button>
        </div>
      </div>
    </div>

    <AssignmentDialog
      v-if="dialog.open"
      :classes="classes"
      :default-class-id="selectedClassId"
      :mode="dialog.mode"
      :target="dialog.target"
      :focus-points="dialog.focus"
      @close="dialog.open = false"
      @created="onCreated"
    />

    <GroupDialog
      v-if="groupsOpen"
      @close="groupsOpen = false"
      @changed="refreshAll"
    />

    <QuestionBankDialog
      v-if="bankOpen"
      @close="bankOpen = false"
    />
  </section>
</template>
