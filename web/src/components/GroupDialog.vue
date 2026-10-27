<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { notify, state } from '../store'
import Icon from './Icon.vue'

const emit = defineEmits(['close', 'changed'])

const teacher = computed(() => state.teacher.profile || {})
const groups = ref([])
const auditRows = ref([])
const loading = ref(true)
const busy = ref(false)
const newName = ref('')
const invites = reactive({})

const canAudit = computed(() => ['owner', 'lead'].includes(teacher.value.role))

const ACTION_LABELS = {
  'teacher.login': '登录',
  'teacher.logout': '登出',
  'teacher.register': '注册',
  'teacher.password': '修改密码',
  'class.roster_import': '导入名单',
  'class.create': '新建班级',
  'class.delete': '删除班级',
  'assignment.create': '布置作业',
  'assignment.delete': '删除作业',
  'submission.grade': '复核成绩',
  'report.export': '导出报告',
  'group.create': '创建教研组',
  'group.update': '修改教研组',
  'group.member_add': '邀请组员',
  'group.member_remove': '移除组员',
}

function actionLabel(action) {
  return ACTION_LABELS[action] || action
}

function resultLabel(result) {
  if (result === 'failed') return '失败'
  if (result === 'deleted') return '已删除'
  return '成功'
}

function canManage(group) {
  return teacher.value.role === 'owner' || group.owner_id === teacher.value.id
}

async function load() {
  loading.value = true
  try {
    const data = await api.teacher.groups.list()
    groups.value = data.items || []
    if (canAudit.value) {
      try {
        auditRows.value = (await api.teacher.audit.list(50)).items || []
      } catch {
        auditRows.value = []
      }
    }
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    loading.value = false
  }
}

async function create() {
  if (busy.value || newName.value.trim().length < 2) return
  busy.value = true
  try {
    await api.teacher.groups.create({ name: newName.value.trim() })
    newName.value = ''
    await load()
    emit('changed')
    notify('教研组已创建，你成为组长')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = false
  }
}

async function rename(group) {
  const name = window.prompt('新的组名（2–30 个字）', group.name)
  if (name === null || !name.trim() || name.trim() === group.name) return
  busy.value = true
  try {
    await api.teacher.groups.update(group.id, { name: name.trim() })
    await load()
    emit('changed')
    notify('组名已更新')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = false
  }
}

async function dissolve(group) {
  if (!window.confirm(`解散「${group.name}」？组内班级会回到个人班级，组员权限立即失效。`)) return
  busy.value = true
  try {
    await api.teacher.groups.remove(group.id)
    await load()
    emit('changed')
    notify('教研组已解散')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = false
  }
}

async function invite(group) {
  const username = (invites[group.id] || '').trim()
  if (busy.value || !username) return
  busy.value = true
  try {
    await api.teacher.groups.addMember(group.id, username)
    invites[group.id] = ''
    await load()
    emit('changed')
    notify(`已邀请 ${username}`)
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = false
  }
}

async function kick(group, member) {
  if (!window.confirm(`把「${member.name}」移出「${group.name}」？`)) return
  busy.value = true
  try {
    await api.teacher.groups.removeMember(group.id, member.teacher_id)
    await load()
    emit('changed')
    notify('已移出教研组')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    busy.value = false
  }
}

function close() {
  if (!busy.value) emit('close')
}

function formatTime(ts) {
  if (!ts) return '—'
  const date = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

onMounted(load)
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="modal modal-wide modal-flex" role="dialog" aria-modal="true" aria-labelledby="group-title">
      <div class="modal-head">
        <div>
          <h2 id="group-title">教研组</h2>
          <p>组内老师可以互相查看班级与报告；组长还能看分、管组，并查看审计记录。</p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <div v-if="loading" class="panel-empty">正在读取教研组…</div>
        <template v-else>
          <div class="hint-box">
            班级可以在「班级」页挂到教研组。只读的班级会显示「教研组共享」标记，布局与操作会被自动收敛。
          </div>

          <div class="field">
            <label for="group-new">新建教研组</label>
            <div class="row" style="gap: 8px">
              <input
                id="group-new"
                v-model="newName"
                class="input"
                maxlength="30"
                placeholder="例：高一数学备课组"
                @keyup.enter="create"
              />
              <button
                class="btn btn-primary"
                type="button"
                :disabled="busy || newName.trim().length < 2"
                @click="create"
              >
                创建
              </button>
            </div>
          </div>

          <div v-if="!groups.length" class="panel-empty">还没有加入任何教研组。</div>
          <div v-for="group in groups" :key="group.id" class="group-card">
            <div class="row" style="gap: 6px; flex-wrap: wrap; align-items: center">
              <strong>{{ group.name }}</strong>
              <span class="chip">{{ group.member_count }} 人</span>
              <span v-if="group.owner_id === teacher.id" class="chip accent">我是组长</span>
              <span v-else-if="teacher.role === 'owner'" class="chip accent">部署者可见</span>
              <span class="spacer" />
              <span class="small muted">组长：{{ group.owner_name }}</span>
            </div>

            <ul class="member-list">
              <li v-for="member in group.members" :key="member.teacher_id">
                <span>
                  {{ member.name }}
                  <span v-if="member.username" class="small muted"> · @{{ member.username }}</span>
                </span>
                <button
                  v-if="canManage(group)"
                  class="btn btn-sm btn-ghost"
                  type="button"
                  @click="kick(group, member)"
                >
                  移除
                </button>
              </li>
              <li v-if="!group.members.length" class="small muted">还没有组员，邀请一位老师加入吧。</li>
            </ul>

            <div v-if="canManage(group)" class="row" style="gap: 8px; flex-wrap: wrap; margin-top: 10px">
              <input
                v-model="invites[group.id]"
                class="input"
                style="flex: 1; min-width: 160px"
                maxlength="24"
                placeholder="组员的用户名（需先注册）"
                @keyup.enter="invite(group)"
              />
              <button
                class="btn btn-sm"
                type="button"
                :disabled="busy || !(invites[group.id] || '').trim()"
                @click="invite(group)"
              >
                <Icon name="plus" :size="13" />
                邀请
              </button>
              <span class="spacer" />
              <button class="btn btn-sm btn-ghost" type="button" :disabled="busy" @click="rename(group)">
                重命名
              </button>
              <button class="btn btn-sm btn-danger" type="button" :disabled="busy" @click="dissolve(group)">
                解散
              </button>
            </div>
          </div>

          <template v-if="canAudit">
            <div class="section-head" style="margin-top: 18px">
              <h2>最近审计</h2>
              <span class="small muted">只记谁做了什么，不记学生答案与密码</span>
            </div>
            <div v-if="!auditRows.length" class="panel-empty">还没有审计记录。</div>
            <table v-else class="data-table">
              <thead>
                <tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>结果</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in auditRows" :key="index">
                  <td class="muted">{{ formatTime(row.at) }}</td>
                  <td>{{ row.actor_name || '—' }}</td>
                  <td>{{ actionLabel(row.action) }}</td>
                  <td class="muted" style="max-width: 220px; overflow: hidden; text-overflow: ellipsis">
                    {{ row.target || '—' }}
                  </td>
                  <td>
                    <span class="chip" :class="{ accent: row.result === 'ok' }">{{ resultLabel(row.result) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
        </template>
      </div>

      <div class="modal-foot">
        <button class="btn btn-primary" type="button" @click="close">完成</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.group-card {
  border: 1px solid var(--border, #e5e5df);
  border-radius: 12px;
  padding: 14px;
  margin-top: 12px;
}
.member-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.member-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 14px;
}
</style>
