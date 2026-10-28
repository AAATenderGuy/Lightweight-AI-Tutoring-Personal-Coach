<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { notify } from '../store'
import Icon from './Icon.vue'

const emit = defineEmits(['close', 'changed'])

const busy = ref(false)
const generating = ref(false)
const errorText = ref('')
const items = ref([])
const topics = ref([])
const drafts = ref(0)
const total = ref(0)

const filter = reactive({ topic: '', status: '', keyword: '' })

// 录题/编辑表单：editing 为 null 表示在新增，否则是在改哪道题
const formOpen = ref(false)
const editing = ref(null)
const form = reactive({
  type: 'single',
  question: '',
  options: ['', '', '', ''],
  answer_index: 0,
  answer: '',
  explanation: '',
  topic: '',
  knowledge_point: '',
  difficulty: 'medium',
})

// AI 批量出题（进草稿箱）
const aiOpen = ref(false)
const ai = reactive({ topic: '', count: 4, difficulty: 'medium' })

const draftItems = computed(() => items.value.filter((item) => item.status === 'draft'))
const checkedDrafts = ref(new Set())

function typeLabel(type) {
  return type === 'single' ? '选择题' : '简答题'
}

function difficultyLabel(value) {
  return { easy: '基础', medium: '标准', hard: '挑战' }[value] || value
}

async function load() {
  try {
    const data = await api.teacher.questions.list({
      topic: filter.topic, status: filter.status, keyword: filter.keyword,
    })
    items.value = data.items
    topics.value = data.topics
    drafts.value = data.drafts
    total.value = data.total
    checkedDrafts.value = new Set()
  } catch (error) {
    notify(error.message, 'error')
  }
}

function resetForm() {
  editing.value = null
  Object.assign(form, {
    type: 'single', question: '', options: ['', '', '', ''],
    answer_index: 0, answer: '', explanation: '', topic: '', knowledge_point: '',
    difficulty: 'medium',
  })
}

function openCreate() {
  resetForm()
  formOpen.value = true
  aiOpen.value = false
}

function openEdit(item) {
  editing.value = item
  Object.assign(form, {
    type: item.type,
    question: item.question,
    options: item.type === 'single'
      ? [...item.options, '', '', '', ''].slice(0, 6)
      : ['', '', '', ''],
    answer_index: item.answer_index ?? 0,
    answer: item.answer || '',
    explanation: item.explanation || '',
    topic: item.topic || '',
    knowledge_point: item.knowledge_point || '',
    difficulty: item.difficulty || 'medium',
  })
  formOpen.value = true
  aiOpen.value = false
}

async function saveForm() {
  if (busy.value) return
  errorText.value = ''
  const payload = {
    type: form.type,
    question: form.question.trim(),
    explanation: form.explanation.trim(),
    topic: form.topic.trim(),
    knowledge_point: form.knowledge_point.trim(),
    difficulty: form.difficulty,
  }
  if (!payload.question) {
    errorText.value = '请填写题干。'
    return
  }
  if (form.type === 'single') {
    payload.options = form.options.map((o) => o.trim()).filter(Boolean)
    payload.answer_index = Number(form.answer_index)
    if (payload.options.length < 2) {
      errorText.value = '选择题至少需要 2 个选项。'
      return
    }
    if (payload.answer_index >= payload.options.length) payload.answer_index = 0
  } else {
    payload.options = []
    payload.answer = form.answer.trim()
  }
  busy.value = true
  try {
    if (editing.value) {
      await api.teacher.questions.update(editing.value.id, payload)
      notify('题目已更新')
    } else {
      await api.teacher.questions.create(payload)
      notify('题目已入库，可直接用于布置作业')
    }
    formOpen.value = false
    await load()
    emit('changed')
  } catch (error) {
    errorText.value = error.message
  } finally {
    busy.value = false
  }
}

async function generate() {
  if (generating.value) return
  if (!ai.topic.trim()) {
    errorText.value = '请填写出题主题。'
    return
  }
  errorText.value = ''
  generating.value = true
  try {
    const data = await api.teacher.questions.generate({
      topic: ai.topic.trim(), count: Number(ai.count), difficulty: ai.difficulty,
    })
    notify(`已生成 ${data.items.length} 道草稿，请逐题审核后入库`)
    aiOpen.value = false
    filter.status = 'draft'
    await load()
    emit('changed')
  } catch (error) {
    errorText.value = error.message
  } finally {
    generating.value = false
  }
}

async function approveOne(item) {
  try {
    await api.teacher.questions.approve([item.id])
    notify('已审核通过，可以用于布置作业')
    await load()
    emit('changed')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function approveChecked() {
  const ids = [...checkedDrafts.value]
  if (!ids.length) return
  try {
    const data = await api.teacher.questions.approve(ids)
    notify(`已审核 ${data.approved} 道题`)
    await load()
    emit('changed')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function toggleDraft(id) {
  const next = new Set(checkedDrafts.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  checkedDrafts.value = next
}

async function remove(item) {
  if (!window.confirm(`删除这道题？\n\n${item.question.slice(0, 60)}`)) return
  try {
    await api.teacher.questions.remove(item.id)
    notify('已删除')
    await load()
    emit('changed')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function close() {
  if (!busy.value && !generating.value) emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="modal modal-wide modal-flex" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div>
          <h2>题库</h2>
          <p>
            共 {{ total }} 题<template v-if="drafts">，其中 {{ drafts }} 道待审核</template>。
            布置作业时可以从这里选题组卷；前后测的平行卷也从这里抽题。
          </p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <div class="row" style="gap: 8px; flex-wrap: wrap">
          <select v-model="filter.topic" class="select" style="width: auto" @change="load">
            <option value="">全部主题</option>
            <option v-for="item in topics" :key="item" :value="item">{{ item }}</option>
          </select>
          <select v-model="filter.status" class="select" style="width: auto" @change="load">
            <option value="">全部状态</option>
            <option value="approved">已审核</option>
            <option value="draft">待审核</option>
          </select>
          <input
            v-model="filter.keyword"
            class="input"
            style="flex: 1; min-width: 160px"
            placeholder="搜索题干或知识点"
            @keyup.enter="load"
          />
          <button class="btn btn-sm" type="button" @click="load">
            <Icon name="refresh" :size="13" />
            搜索
          </button>
          <button class="btn btn-sm" type="button" @click="openCreate">
            <Icon name="plus" :size="13" />
            手工录题
          </button>
          <button class="btn btn-sm btn-primary" type="button" @click="aiOpen = !aiOpen; formOpen = false">
            <Icon name="spark" :size="13" />
            AI 出题
          </button>
        </div>

        <div v-if="aiOpen" class="hint-box" style="margin-top: 10px">
          <div class="row" style="gap: 8px; flex-wrap: wrap">
            <input v-model="ai.topic" class="input" style="flex: 1; min-width: 160px" placeholder="出题主题，例：光合作用" maxlength="120" />
            <select v-model.number="ai.count" class="select" style="width: auto">
              <option v-for="n in [2, 3, 4, 5, 6, 8, 10]" :key="n" :value="n">{{ n }} 题</option>
            </select>
            <select v-model="ai.difficulty" class="select" style="width: auto">
              <option value="easy">基础</option>
              <option value="medium">标准</option>
              <option value="hard">挑战</option>
            </select>
            <button class="btn btn-sm btn-primary" type="button" :disabled="generating" @click="generate">
              {{ generating ? '生成中…' : '生成草稿' }}
            </button>
          </div>
          <div class="small muted" style="margin-top: 6px">
            AI 出的题一律先进「待审核」，教师逐题确认后才会出现在布置作业的选题列表里。
          </div>
        </div>

        <div v-if="formOpen" class="hint-box" style="margin-top: 10px">
          <div class="row" style="justify-content: space-between">
            <strong>{{ editing ? '编辑题目' : '手工录题' }}</strong>
            <button class="icon-btn" type="button" aria-label="收起" @click="formOpen = false">
              <Icon name="close" :size="15" />
            </button>
          </div>
          <div class="field" style="margin-top: 8px">
            <label>题干</label>
            <textarea v-model="form.question" class="textarea" rows="2" maxlength="400" />
          </div>
          <div class="grid-3">
            <div class="field">
              <label>题型</label>
              <select v-model="form.type" class="select">
                <option value="single">选择题</option>
                <option value="short">简答题</option>
              </select>
            </div>
            <div class="field">
              <label>难度</label>
              <select v-model="form.difficulty" class="select">
                <option value="easy">基础</option>
                <option value="medium">标准</option>
                <option value="hard">挑战</option>
              </select>
            </div>
            <div class="field">
              <label>主题</label>
              <input v-model="form.topic" class="input" maxlength="60" placeholder="例：光合作用" />
            </div>
          </div>
          <template v-if="form.type === 'single'">
            <div v-for="(option, index) in form.options" :key="index" class="row" style="gap: 8px; margin-bottom: 6px">
              <span class="chip">{{ 'ABCDEF'[index] }}</span>
              <input v-model="form.options[index]" class="input" style="flex: 1" maxlength="160" placeholder="留空则忽略该选项" />
              <label class="check-line" style="margin: 0">
                <input v-model="form.answer_index" type="radio" :value="index" />
                <span class="small">正确</span>
              </label>
            </div>
          </template>
          <div v-else class="field">
            <label>参考答案</label>
            <textarea v-model="form.answer" class="textarea" rows="2" maxlength="600" />
          </div>
          <div class="grid-2">
            <div class="field">
              <label>知识点</label>
              <input v-model="form.knowledge_point" class="input" maxlength="60" placeholder="留空则按主题归类" />
            </div>
            <div class="field">
              <label>解析（可选）</label>
              <input v-model="form.explanation" class="input" maxlength="400" />
            </div>
          </div>
          <div class="row" style="justify-content: flex-end; gap: 8px">
            <button class="btn btn-sm" type="button" :disabled="busy" @click="formOpen = false">取消</button>
            <button class="btn btn-sm btn-primary" type="button" :disabled="busy" @click="saveForm">
              {{ busy ? '保存中…' : editing ? '保存修改' : '录入题库' }}
            </button>
          </div>
        </div>

        <div v-if="errorText" class="msg-error" style="margin-top: 10px">{{ errorText }}</div>

        <div v-if="filter.status === 'draft' && draftItems.length" class="row" style="margin-top: 10px; gap: 8px">
          <button class="btn btn-sm btn-primary" type="button" :disabled="!checkedDrafts.size" @click="approveChecked">
            审核通过选中项（{{ checkedDrafts.size }}）
          </button>
        </div>

        <div v-if="!items.length" class="panel-empty" style="margin-top: 12px">
          还没有题目。手工录一道，或让 AI 出一批草稿。
        </div>
        <div v-else class="mini-list" style="margin-top: 12px">
          <div v-for="item in items" :key="item.id" class="mini-row" style="cursor: default">
            <label v-if="filter.status === 'draft'" class="check-line" style="margin: 0 8px 0 0">
              <input
                type="checkbox"
                :checked="checkedDrafts.has(item.id)"
                @change="toggleDraft(item.id)"
              />
            </label>
            <div class="mini-main">
              <div class="todo-title">{{ item.question }}</div>
              <div class="small muted" style="margin-top: 4px">
                <span class="chip">{{ typeLabel(item.type) }}</span>
                <span class="chip">{{ difficultyLabel(item.difficulty) }}</span>
                <span v-if="item.status === 'draft'" class="chip accent">待审核</span>
                <span v-if="item.topic" class="chip">{{ item.topic }}</span>
                <span v-if="item.knowledge_point" class="chip">{{ item.knowledge_point }}</span>
                <span v-if="item.source === 'ai'" class="chip">AI</span>
              </div>
              <div v-if="item.type === 'single'" class="small muted" style="margin-top: 4px">
                {{ item.options.map((o, i) => `${'ABCDEF'[i]}. ${o}`).join('　') }}
                <strong>答案：{{ 'ABCDEF'[item.answer_index] }}</strong>
              </div>
              <div v-else-if="item.answer" class="small muted" style="margin-top: 4px">
                参考答案：{{ item.answer.slice(0, 120) }}
              </div>
            </div>
            <div class="row-actions">
              <button v-if="item.status === 'draft'" class="btn btn-sm btn-primary" type="button" @click="approveOne(item)">
                通过
              </button>
              <button class="btn btn-sm btn-ghost" type="button" @click="openEdit(item)">编辑</button>
              <button class="btn btn-sm btn-ghost" type="button" @click="remove(item)">删除</button>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-foot">
        <button class="btn btn-primary" type="button" @click="close">完成</button>
      </div>
    </div>
  </div>
</template>
