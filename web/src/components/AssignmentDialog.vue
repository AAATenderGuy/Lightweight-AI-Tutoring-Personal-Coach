<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { notify } from '../store'
import Icon from './Icon.vue'

const props = defineProps({
  classes: { type: Array, default: () => [] },
  defaultClassId: { type: String, default: '' },
  mode: { type: String, default: 'create' },
  target: { type: Object, default: null },
  focusPoints: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'created'])

const busy = ref(false)
const errorText = ref('')
const form = reactive({
  class_id: props.defaultClassId || props.classes[0]?.id || '',
  kind: 'homework',
  submission_mode: 'quiz',
  source: 'ai',
  title: '',
  topic: '',
  count: 4,
  difficulty: 'medium',
  due: '',
  instructions: '',
  rubric: '',
  reveal: false,
  draft: false,
})

// 题库选题模式：只列已审核的题，勾选后按勾选题数生成
const bankLoading = ref(false)
const bankItems = ref([])
const bankPicked = ref(new Set())
const bankKeyword = ref('')

const isPractice = computed(() => props.mode === 'practice')
const isFile = computed(() => form.submission_mode === 'file')
const isBank = computed(() => form.submission_mode === 'quiz' && form.source === 'bank')
const title = computed(() => (isPractice.value ? '生成薄弱点补练' : '布置新作业'))

const bankFiltered = computed(() => {
  const needle = bankKeyword.value.trim().toLowerCase()
  if (!needle) return bankItems.value
  return bankItems.value.filter((item) => (
    item.question.toLowerCase().includes(needle)
    || (item.knowledge_point || '').toLowerCase().includes(needle)
    || (item.topic || '').toLowerCase().includes(needle)
  ))
})

async function loadBank() {
  if (bankLoading.value) return
  bankLoading.value = true
  try {
    const data = await api.teacher.questions.list({ status: 'approved' })
    bankItems.value = data.items
  } catch (error) {
    errorText.value = error.message
  } finally {
    bankLoading.value = false
  }
}

watch(() => form.source, (value) => {
  if (value === 'bank' && !bankItems.value.length) loadBank()
})
watch(() => form.submission_mode, (value) => {
  if (value === 'file') form.source = 'ai'
})

function togglePick(id) {
  const next = new Set(bankPicked.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  bankPicked.value = next
}

watch(() => props.classes, (items) => {
  if (!form.class_id && items.length) form.class_id = items[0].id
})

function toTimestamp(value) {
  if (!value) return 0
  const stamp = new Date(value).getTime()
  return Number.isFinite(stamp) ? Math.floor(stamp / 1000) : 0
}

function localInput(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function quickDue(kind) {
  const date = new Date()
  if (kind === 'none') {
    form.due = ''
    return
  }
  if (kind === 'tonight') {
    date.setHours(22, 0, 0, 0)
  } else if (kind === 'tomorrow') {
    date.setDate(date.getDate() + 1)
    date.setHours(20, 0, 0, 0)
  } else {
    date.setDate(date.getDate() + 7)
    date.setHours(20, 0, 0, 0)
  }
  form.due = localInput(date)
}

async function submit() {
  if (busy.value) return
  errorText.value = ''
  if (!isPractice.value) {
    if (!form.class_id) {
      errorText.value = '请先选择一个班级。'
      return
    }
    if (!form.topic.trim()) {
      errorText.value = isFile.value
        ? '请填写作业主题，标题和文件名会用到它。'
        : '请填写作业主题，AI 会围绕它出题。'
      return
    }
    if (isBank.value && !bankPicked.value.size) {
      errorText.value = '请至少勾选一道题。'
      return
    }
  }
  busy.value = true
  try {
    const data = isPractice.value
      ? await api.teacher.assignments.practice(props.target.id, {
          count: Number(form.count),
          focus_points: props.focusPoints,
          due_at: toTimestamp(form.due),
        })
      : await api.teacher.assignments.create({
          class_id: form.class_id,
          title: form.title.trim(),
          topic: form.topic.trim(),
          kind: form.kind,
          submission_mode: form.submission_mode,
          count: Number(form.count),
          difficulty: form.difficulty,
          due_at: toTimestamp(form.due),
          instructions: form.instructions.trim(),
          rubric: form.rubric.trim(),
          reveal: form.reveal,
          draft: form.draft,
          question_ids: isBank.value ? [...bankPicked.value] : [],
        })
    notify(isPractice.value
      ? '补练已布置到班级'
      : form.draft
        ? '作业已存为草稿，学生端暂不可见'
        : '作业已布置，学生端会立即看到')
    emit('created', data.assignment)
  } catch (error) {
    errorText.value = error.message
  } finally {
    busy.value = false
  }
}

function close() {
  if (!busy.value) emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="modal modal-wide modal-flex" role="dialog" aria-modal="true">
      <div class="modal-head">
        <div>
          <h2>{{ title }}</h2>
          <p v-if="isPractice">
            基于《{{ target?.title }}》的错题知识点生成同难度变式题，交卷后直接显示答案解析。
          </p>
          <p v-else>
            {{ isFile ? '学生提交文件后 AI 先给初评，你可以在作业详情里复核改分。' : '填写主题后由 AI 出题；学生交卷后自动判分并计入班级统计。' }}
          </p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <template v-if="!isPractice">
          <div class="grid-2">
            <div class="field">
              <label for="as-class">班级</label>
              <select id="as-class" v-model="form.class_id" class="select">
                <option v-for="item in classes" :key="item.id" :value="item.id">
                  {{ item.name }}（{{ item.student_count }} 人）
                </option>
              </select>
            </div>
            <div class="field">
              <label>类型</label>
              <div class="segmented" style="width: 100%">
                <button type="button" style="flex: 1" :class="{ active: form.kind === 'quiz' }" @click="form.kind = 'quiz'">
                  随堂测验
                </button>
                <button type="button" style="flex: 1" :class="{ active: form.kind === 'homework' }" @click="form.kind = 'homework'">
                  课后作业
                </button>
              </div>
            </div>
          </div>

          <div class="field">
            <label>作业形式</label>
            <div class="segmented" style="width: 100%">
              <button type="button" style="flex: 1" :class="{ active: form.submission_mode === 'quiz' }" @click="form.submission_mode = 'quiz'">
                在线作答
              </button>
              <button type="button" style="flex: 1" :class="{ active: form.submission_mode === 'file' }" @click="form.submission_mode = 'file'">
                文件提交
              </button>
            </div>
          </div>

          <div v-if="!isFile" class="field">
            <label>题目来源</label>
            <div class="segmented" style="width: 100%">
              <button type="button" style="flex: 1" :class="{ active: form.source === 'ai' }" @click="form.source = 'ai'">
                AI 出题
              </button>
              <button type="button" style="flex: 1" :class="{ active: form.source === 'bank' }" @click="form.source = 'bank'">
                题库选题
              </button>
            </div>
          </div>

          <div v-if="isBank" class="field">
            <div class="row" style="justify-content: space-between; gap: 8px">
              <label style="margin: 0">选题（已选 {{ bankPicked.size }} 题）</label>
              <input v-model="bankKeyword" class="input" style="flex: 1; max-width: 220px" placeholder="搜索题干 / 知识点" />
            </div>
            <div v-if="bankLoading" class="panel-empty">正在读取题库…</div>
            <div v-else-if="!bankItems.length" class="panel-empty">
              题库还没有已审核的题目，先去「题库」录题或让 AI 生成草稿。
            </div>
            <div v-else class="mini-list" style="max-height: 260px; overflow: auto">
              <label
                v-for="item in bankFiltered"
                :key="item.id"
                class="mini-row"
                style="cursor: pointer"
              >
                <input
                  type="checkbox"
                  :checked="bankPicked.has(item.id)"
                  @change="togglePick(item.id)"
                />
                <div class="mini-main">
                  <div class="todo-title">{{ item.question }}</div>
                  <div class="small muted" style="margin-top: 2px">
                    <span class="chip">{{ item.type === 'single' ? '选择' : '简答' }}</span>
                    <span v-if="item.topic" class="chip">{{ item.topic }}</span>
                    <span v-if="item.knowledge_point" class="chip">{{ item.knowledge_point }}</span>
                  </div>
                </div>
              </label>
            </div>
          </div>

          <div class="field">
            <label for="as-topic">作业主题</label>
            <input id="as-topic" v-model="form.topic" class="input" :placeholder="isFile ? '例：光合作用实验报告' : '例：光合作用的两个阶段'" maxlength="120" />
          </div>

          <div class="field">
            <label for="as-title">显示标题（可选）</label>
            <input id="as-title" v-model="form.title" class="input" placeholder="留空则使用 AI 生成的标题" maxlength="80" />
          </div>
        </template>

        <div v-else class="practice-box">
          <div class="small muted">本次补练覆盖的知识点</div>
          <div class="chips">
            <span v-for="point in focusPoints" :key="point" class="chip accent">{{ point }}</span>
            <span v-if="!focusPoints.length" class="chip">整份作业的薄弱点</span>
          </div>
        </div>

        <div class="grid-3">
          <div v-if="!isFile && !isBank" class="field">
            <label for="as-count">题量</label>
            <select id="as-count" v-model.number="form.count" class="select">
              <option v-for="value in [3, 4, 5, 6, 8]" :key="value" :value="value">{{ value }} 题</option>
            </select>
          </div>
          <div v-if="!isPractice && !isFile && !isBank" class="field">
            <label for="as-difficulty">难度</label>
            <select id="as-difficulty" v-model="form.difficulty" class="select">
              <option value="easy">基础</option>
              <option value="medium">标准</option>
              <option value="hard">挑战</option>
            </select>
          </div>
          <div class="field">
            <label for="as-due">截止时间（可选）</label>
            <input id="as-due" v-model="form.due" class="input" type="datetime-local" />
          </div>
        </div>

        <div v-if="!isPractice && isFile" class="field">
          <label for="as-rubric">评分要点（可选）</label>
          <textarea
            id="as-rubric"
            v-model="form.rubric"
            class="textarea"
            rows="3"
            maxlength="1500"
            placeholder="例：写出光反应与暗反应的区别；给出至少一个实验现象；结论明确。"
          />
          <span class="small muted">AI 会按这些要点批改，教师可以在此基础上复核改分。</span>
        </div>

        <div class="row small muted" style="flex-wrap: wrap; gap: 6px">
          <button class="btn btn-sm btn-ghost" type="button" @click="quickDue('tonight')">今晚 22:00</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="quickDue('tomorrow')">明天 20:00</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="quickDue('week')">一周后</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="quickDue('none')">不设截止</button>
        </div>

        <div v-if="!isPractice" class="field">
          <label for="as-note">给学生的说明（可选）</label>
          <textarea id="as-note" v-model="form.instructions" class="textarea" rows="2" maxlength="300"
            placeholder="例：先看第 3 页的讲解再作答，允许查资料。" />
        </div>

        <label class="check-line">
          <input v-model="form.reveal" type="checkbox" />
          <span>交卷后向学生显示正确答案与解析（默认关闭，讲评时再打开）</span>
        </label>

        <label v-if="!isPractice" class="check-line">
          <input v-model="form.draft" type="checkbox" />
          <span>先存为草稿：学生端不可见，准备好后再发布</span>
        </label>

        <div v-if="errorText" class="msg-error">{{ errorText }}</div>

        <div class="hint-box">
          <template v-if="busy">正在出题，通常需要几秒到十几秒；请不要关闭窗口。</template>
          <template v-else-if="isBank">从题库选题组卷，题目会整体拷贝进作业；之后改题库不影响这份作业。</template>
          <template v-else-if="isFile">作业发布后学生端会出现「提交附件」入口，AI 初评完成后会实时提示你复核。</template>
          <template v-else>题目生成后会立即出现在学生的「班级」页，无需再单独通知。</template>
        </div>
      </div>

      <div class="modal-foot">
        <button class="btn" type="button" :disabled="busy" @click="close">取消</button>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="submit">
          <Icon :name="busy ? 'refresh' : 'spark'" :size="14" />
          {{ busy ? '出题中…' : isPractice ? '生成并布置' : '布置作业' }}
        </button>
      </div>
    </div>
  </div>
</template>
