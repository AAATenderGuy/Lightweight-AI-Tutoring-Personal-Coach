<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api, streamJSON } from '../api'
import { loadLessons, notify, refreshProgress, state, switchView } from '../store'
import Icon from '../components/Icon.vue'
import GroupSettingsDialog from '../components/GroupSettingsDialog.vue'

const form = reactive({ topic: '', level: 'beginner', duration: 20, sceneCount: 6 })
const generating = ref(false)
const statusText = ref('')
const lesson = ref(null)
const sceneIndex = ref(0)
const showNotes = ref(true)
const selectedLessonId = ref('')
const discussion = ref([])
const discInput = ref('')
const discBusy = ref(false)
const discEl = ref(null)
const mainEl = ref(null)
const quizAnswers = reactive({})
const quizRevealed = reactive({})
const sideTab = ref('teacher')
const groupMessages = ref([])
const groupInput = ref('')
const groupBusy = ref(false)
const groupEl = ref(null)
const groupSettingsOpen = ref(false)
const groupPlan = ref('')
const exporting = ref(false)
const groupAgents = ref([
  { id: 'xiaowen', name: '小问', role: '追问者' },
  { id: 'xiaosi', name: '小思', role: '梳理者' },
  { id: 'xiaoli', name: '小理', role: '质疑者' },
])

const scene = computed(() => lesson.value?.scenes?.[sceneIndex.value] || null)
const sceneTotal = computed(() => lesson.value?.scenes?.length || 0)
const isLast = computed(() => sceneIndex.value >= sceneTotal.value - 1)
const typeLabel = computed(() => ({
  cover: '开场',
  content: '讲解',
  discussion: '讨论',
  quiz: '检测',
  summary: '回顾',
}[scene.value?.type] || '讲解'))

const levels = [
  { value: 'beginner', label: '入门' },
  { value: 'intermediate', label: '进阶' },
  { value: 'advanced', label: '挑战' },
]
const durations = [10, 20, 30, 45]
const sceneCounts = [5, 6, 7, 8]

function levelLabel(value) {
  return levels.find((item) => item.value === value)?.label || value
}

function scrollMainTop() {
  nextTick(() => {
    if (mainEl.value) mainEl.value.scrollTop = 0
  })
}

function scrollDiscussion() {
  nextTick(() => {
    const el = discEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function scrollGroup() {
  nextTick(() => {
    const el = groupEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function loadGroupAgents() {
  try {
    const data = await api.lessons.groupAgents()
    if (data.agents?.length) groupAgents.value = data.agents
  } catch {
    /* 使用内置的默认角色，不阻塞课堂 */
  }
}

onMounted(loadGroupAgents)

function resetQuizState() {
  Object.keys(quizAnswers).forEach((key) => delete quizAnswers[key])
  Object.keys(quizRevealed).forEach((key) => delete quizRevealed[key])
}

function applyLesson(data) {
  lesson.value = data
  selectedLessonId.value = data.id
  sceneIndex.value = 0
  showNotes.value = true
  discussion.value = []
  discInput.value = ''
  groupMessages.value = []
  groupInput.value = ''
  resetQuizState()
  scrollMainTop()
}

async function generate() {
  const topic = form.topic.trim()
  if (!topic) {
    notify('先写一个课堂主题')
    return
  }
  generating.value = true
  statusText.value = '正在连接模型…'
  lesson.value = null
  discussion.value = []
  try {
    let data = null
    let errorMessage = ''
    await streamJSON(
      '/api/classroom/generate',
      {
        topic,
        level: form.level,
        duration: Number(form.duration),
        scene_count: Number(form.sceneCount),
        material_ids: [],
      },
      (event) => {
        if (event.type === 'status') statusText.value = event.text
        else if (event.type === 'lesson') data = event.lesson
        else if (event.type === 'error') errorMessage = event.message
      },
    )
    if (errorMessage) throw new Error(errorMessage)
    if (!data) throw new Error('没有收到课堂内容，请重试。')
    applyLesson(data)
    await loadLessons()
    refreshProgress()
    notify('课堂已生成')
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    generating.value = false
  }
}

async function openLesson() {
  if (!selectedLessonId.value) return
  try {
    const data = await api.lessons.get(selectedLessonId.value)
    applyLesson(data.lesson)
    form.topic = data.lesson.topic || data.lesson.title || form.topic
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function removeLesson() {
  if (!lesson.value) return
  if (!window.confirm(`删除课堂《${lesson.value.title}》？`)) return
  try {
    await api.lessons.remove(lesson.value.id)
    lesson.value = null
    selectedLessonId.value = ''
    await loadLessons()
    notify('课堂已删除')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function go(index) {
  sceneIndex.value = Math.max(0, Math.min(sceneTotal.value - 1, index))
  scrollMainTop()
}

function goQuiz() {
  if (!lesson.value) return
  state.pendingQuizTopic = lesson.value.topic || lesson.value.title || form.topic
  switchView('quiz')
}

function key(sceneId, index) {
  return `${sceneId}:${index}`
}

function choose(sceneId, index, optionIndex) {
  const itemKey = key(sceneId, index)
  if (quizRevealed[itemKey]) return
  quizAnswers[itemKey] = optionIndex
}

function isRevealed(sceneId, index) {
  return Boolean(quizRevealed[key(sceneId, index)])
}

function reveal(sceneId, index) {
  quizRevealed[key(sceneId, index)] = true
}

async function ask() {
  const question = discInput.value.trim()
  if (!question || !lesson.value || !scene.value || discBusy.value) return

  const history = discussion.value
    .filter((item) => item.content && !item.error)
    .slice(-8)
    .map((item) => ({
      role: item.role === 'teacher' ? 'assistant' : 'user',
      content: item.content,
    }))

  discInput.value = ''
  discussion.value.push({ role: 'user', content: question, streaming: false, error: '' })
  const reply = reactive({ role: 'teacher', content: '', streaming: true, error: '' })
  discussion.value.push(reply)
  discBusy.value = true
  scrollDiscussion()

  try {
    await streamJSON(
      '/api/classroom/discuss',
      {
        lesson_id: lesson.value.id,
        scene_id: scene.value.id,
        question,
        history,
      },
      (event) => {
        if (event.type === 'delta') {
          reply.content += event.text
          scrollDiscussion()
        } else if (event.type === 'error') {
          reply.error = event.message
        }
      },
    )
  } catch (error) {
    reply.error = error.message
  } finally {
    reply.streaming = false
    discBusy.value = false
    scrollDiscussion()
  }
}

function clearDiscussion() {
  if (discBusy.value) return
  discussion.value = []
  discInput.value = ''
}

function clearGroup() {
  if (groupBusy.value) return
  groupMessages.value = []
  groupInput.value = ''
  groupPlan.value = ''
}

async function onGroupSaved() {
  await loadGroupAgents()
  if (!groupBusy.value) {
    groupMessages.value = []
    groupPlan.value = ''
  }
}

function clearActive() {
  if (sideTab.value === 'teacher') clearDiscussion()
  else clearGroup()
}

function setSideTab(tab) {
  sideTab.value = tab
  if (tab === 'group') scrollGroup()
}

async function askGroup(auto = false) {
  if (!lesson.value || !scene.value || groupBusy.value) return
  const message = auto ? '' : groupInput.value.trim()
  if (!auto && !message) return

  const history = groupMessages.value
    .filter((item) => item.role !== 'system' && item.content && !item.error)
    .slice(-10)
    .map((item) => ({
      role: item.role === 'user' ? 'user' : 'assistant',
      agent: item.role === 'user' ? '' : (item.agent?.name || ''),
      content: item.content,
    }))

  groupInput.value = ''
  if (auto) groupMessages.value.push({ role: 'system', content: '小组开始讨论当前页' })
  else groupMessages.value.push({ role: 'user', content: message })
  groupBusy.value = true
  let current = null
  scrollGroup()

  const startAgent = (agent) => {
    current = reactive({ role: 'assistant', agent, content: '', streaming: true, error: '' })
    groupMessages.value.push(current)
    scrollGroup()
  }

  try {
    await streamJSON(
      '/api/classroom/group-discuss',
      {
        lesson_id: lesson.value.id,
        scene_id: scene.value.id,
        message,
        mode: auto ? 'auto' : 'chat',
        history,
      },
      (event) => {
        if (event.type === 'meta') {
          if (event.agents?.length) groupAgents.value = event.agents
          groupPlan.value = event.reason || ''
        } else if (event.type === 'agent_start') {
          startAgent(event.agent)
        } else if (event.type === 'delta') {
          if (!current) startAgent(event.agent)
          current.content += event.text
          scrollGroup()
        } else if (event.type === 'agent_end') {
          if (current) {
            current.streaming = false
            if (!current.content.trim()) current.error = `${current.agent?.name || '同学'} 没有发言，请再试一次。`
            current = null
          }
        } else if (event.type === 'error') {
          const active = current || groupMessages.value.find((item) => item.streaming)
          if (active) {
            active.error = event.message
            active.streaming = false
          } else {
            notify(event.message, 'error')
          }
        }
      },
    )
  } catch (error) {
    const active = current || groupMessages.value.find((item) => item.streaming)
    if (active) active.error = error.message
    else notify(error.message, 'error')
  } finally {
    groupMessages.value.forEach((item) => {
      if (item.streaming) item.streaming = false
    })
    groupBusy.value = false
    scrollGroup()
  }
}

function exportPptx() {
  if (!lesson.value || exporting.value) return
  exporting.value = true
  const link = document.createElement('a')
  link.href = `/api/classroom/lessons/${lesson.value.id}/export/pptx`
  link.download = `${lesson.value.title || '课堂'}.pptx`
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  notify('正在导出教师版 PPT…')
  window.setTimeout(() => {
    exporting.value = false
  }, 1200)
}
</script>

<template>
  <section class="classroom">
    <div class="class-toolbar">
      <div class="field topic">
        <label for="class-topic">课堂主题</label>
        <input
          id="class-topic"
          v-model="form.topic"
          class="input"
          placeholder="例：用 20 分钟讲清楚光合作用"
          @keydown.enter="generate"
        />
      </div>
      <div class="field compact">
        <label for="class-level">难度</label>
        <select id="class-level" v-model="form.level" class="select">
          <option v-for="item in levels" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>
      <div class="field compact">
        <label for="class-duration">时长</label>
        <select id="class-duration" v-model.number="form.duration" class="select">
          <option v-for="value in durations" :key="value" :value="value">{{ value }} 分钟</option>
        </select>
      </div>
      <div class="field compact">
        <label for="class-scenes">页数</label>
        <select id="class-scenes" v-model.number="form.sceneCount" class="select">
          <option v-for="value in sceneCounts" :key="value" :value="value">{{ value }} 页</option>
        </select>
      </div>
      <div class="field saved">
        <label for="class-saved">我的课堂</label>
        <select id="class-saved" v-model="selectedLessonId" class="select" @change="openLesson">
          <option value="">选择已保存的课堂…</option>
          <option v-for="item in state.lessons" :key="item.id" :value="item.id">{{ item.title }}</option>
        </select>
      </div>
      <div class="actions">
        <button
          v-if="lesson"
          class="btn btn-accent export-btn"
          type="button"
          title="导出教师版 PPTX（含讲解词备注与答案附录）"
          :disabled="exporting"
          @click="exportPptx"
        >
          <Icon name="download" :size="15" />
          {{ exporting ? '准备下载…' : '导出 PPT' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="generating || !form.topic.trim()" @click="generate">
          <Icon name="spark" :size="14" />
          {{ generating ? '生成中…' : '生成课堂' }}
        </button>
      </div>
    </div>

    <div class="class-body">
      <div ref="mainEl" class="class-main">
        <div v-if="generating" class="stage-wrap">
          <div class="loading-stage">
            <div class="spinner" />
            <strong>正在备课</strong>
            <span class="small muted">{{ statusText }}</span>
            <span class="small muted">通常需要 20–60 秒，请保持页面打开</span>
          </div>
        </div>

        <div v-else-if="!lesson" class="class-placeholder">
          <h2>把任何主题变成一堂可交互的课</h2>
          <p>课堂按「开场 → 讲解 → 讨论 → 检测 → 回顾」生成，右侧可以切换答疑和小组互动；生成后还能导出 PPT 直接上课。</p>
          <div class="feature-list">
            <div class="feature">
              <strong>结构先行</strong>
              <span>先给出目标与主线，再逐页展开，避免信息堆砌。</span>
            </div>
            <div class="feature">
              <strong>对话式答疑</strong>
              <span>向 AI 老师追问当前页，老师会记住上文，继续往下讲。</span>
            </div>
            <div class="feature">
              <strong>一键导出 PPT</strong>
              <span>讲解词写进备注，答案与解析放进教师版附录。</span>
            </div>
          </div>
          <p class="small muted" style="margin-top: 20px">
            提示：先在「资料」页上传讲义，再生成课堂，内容会更贴合你的课程。
          </p>
        </div>

        <div v-else-if="scene" class="stage-wrap">
          <div class="stage" :class="{ cover: scene.type === 'cover' }">
            <div class="stage-kicker">
              <span>{{ typeLabel }}</span>
              <span>·</span>
              <span>{{ sceneIndex + 1 }} / {{ sceneTotal }}</span>
              <span class="spacer" />
              <span class="chip">{{ levelLabel(lesson.level) }}</span>
            </div>

            <template v-if="scene.type === 'cover'">
              <h2>{{ scene.title }}</h2>
              <p v-if="scene.subtitle" class="stage-sub">{{ scene.subtitle }}</p>
              <ul v-if="scene.bullets?.length">
                <li v-for="(bullet, index) in scene.bullets" :key="index">{{ bullet }}</li>
              </ul>
              <p v-if="lesson.objectives?.length" class="stage-sub" style="margin-top: auto">
                本课目标：{{ lesson.objectives.join('；') }}
              </p>
            </template>

            <template v-else-if="scene.type === 'content'">
              <h2>{{ scene.title }}</h2>
              <ul v-if="scene.bullets?.length">
                <li v-for="(bullet, index) in scene.bullets" :key="index">{{ bullet }}</li>
              </ul>
              <p v-if="scene.prompt" class="stage-prompt">{{ scene.prompt }}</p>
              <div v-if="showNotes && scene.notes" class="stage-notes">
                <span class="stage-notes-label">讲解词</span>{{ scene.notes }}
              </div>
            </template>

            <template v-else-if="scene.type === 'discussion'">
              <h2>{{ scene.title }}</h2>
              <p class="stage-sub">{{ scene.prompt }}</p>
              <div v-if="scene.hints?.length" class="row" style="flex-wrap: wrap">
                <span v-for="(hint, index) in scene.hints" :key="index" class="chip">{{ hint }}</span>
              </div>
              <p class="stage-sub" style="margin-top: auto">想一想，然后到右侧告诉老师你的答案。</p>
            </template>

            <template v-else-if="scene.type === 'quiz'">
              <h2>{{ scene.title }}</h2>
              <div class="quiz-scene">
                <div v-for="(question, questionIndex) in scene.questions" :key="questionIndex" class="quiz-q">
                  <div class="quiz-q-title">{{ questionIndex + 1 }}. {{ question.question }}</div>
                  <div v-if="question.type === 'single' && question.options?.length" class="quiz-options">
                    <button
                      v-for="(option, optionIndex) in question.options"
                      :key="optionIndex"
                      type="button"
                      class="quiz-option"
                      :class="{
                        selected: quizAnswers[key(scene.id, questionIndex)] === optionIndex,
                        correct: isRevealed(scene.id, questionIndex) && optionIndex === question.answer_index,
                        wrong:
                          isRevealed(scene.id, questionIndex) &&
                          quizAnswers[key(scene.id, questionIndex)] === optionIndex &&
                          optionIndex !== question.answer_index,
                      }"
                      @click="choose(scene.id, questionIndex, optionIndex)"
                    >
                      <span class="key">{{ 'ABCD'[optionIndex] }}</span>
                      <span>{{ option }}</span>
                    </button>
                  </div>
                  <textarea
                    v-else
                    v-model="quizAnswers[key(scene.id, questionIndex)]"
                    class="textarea"
                    rows="2"
                    placeholder="写下你的回答…"
                  />
                  <button class="btn btn-sm" type="button" @click="reveal(scene.id, questionIndex)">
                    查看{{ question.type === 'single' ? '答案与解析' : '参考答案' }}
                  </button>
                  <div v-if="isRevealed(scene.id, questionIndex)" class="quiz-explain">
                    <template v-if="question.type === 'single'">
                      正确答案：{{ 'ABCD'[question.answer_index] }}. {{ question.options[question.answer_index] }}
                      <br />
                    </template>
                    <template v-else>
                      参考答案：{{ question.answer || '（暂无）' }}
                      <br />
                    </template>
                    {{ question.explanation }}
                  </div>
                </div>
              </div>
            </template>

            <template v-else>
              <h2>{{ scene.title }}</h2>
              <ul v-if="scene.bullets?.length">
                <li v-for="(bullet, index) in scene.bullets" :key="index">{{ bullet }}</li>
              </ul>
              <p class="stage-prompt">下一步：用「测验」页做一组新题，系统会记录你的掌握度。</p>
            </template>
          </div>

          <div class="stage-nav">
            <div class="dots">
              <button
                v-for="(item, index) in lesson.scenes"
                :key="item.id"
                type="button"
                :class="{ active: index === sceneIndex, done: index < sceneIndex }"
                :title="item.title"
                :aria-label="`第 ${index + 1} 页：${item.title}`"
                @click="go(index)"
              />
            </div>
            <div class="row">
              <button class="btn btn-sm" type="button" :disabled="sceneIndex === 0" @click="go(sceneIndex - 1)">
                <Icon name="left" :size="12" />
                上一页
              </button>
              <button v-if="!isLast" class="btn btn-sm" type="button" @click="go(sceneIndex + 1)">
                下一页
                <Icon name="right" :size="12" />
              </button>
              <button v-else class="btn btn-sm btn-primary" type="button" @click="goQuiz">
                去测验
                <Icon name="arrow" :size="12" />
              </button>
              <button class="btn btn-sm btn-ghost" type="button" @click="showNotes = !showNotes">
                {{ showNotes ? '隐藏讲解词' : '显示讲解词' }}
              </button>
              <button class="icon-btn" type="button" title="删除这堂课" @click="removeLesson">
                <Icon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <aside class="class-side">
        <div class="side-head side-head-tabs">
          <div class="segmented side-tabs" role="tablist" aria-label="互动模式">
            <button
              type="button"
              role="tab"
              :aria-selected="sideTab === 'teacher'"
              :class="{ active: sideTab === 'teacher' }"
              @click="setSideTab('teacher')"
            >
              答疑
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="sideTab === 'group'"
              :class="{ active: sideTab === 'group' }"
              @click="setSideTab('group')"
            >
              小组
            </button>
          </div>
          <button
            v-if="sideTab === 'group'"
            class="icon-btn"
            type="button"
            title="小组设置"
            :disabled="groupBusy"
            @click="groupSettingsOpen = true"
          >
            <Icon name="settings" :size="14" />
          </button>
          <button
            class="icon-btn"
            type="button"
            title="清空当前对话"
            :disabled="
              sideTab === 'teacher'
                ? !discussion.length || discBusy
                : !groupMessages.length || groupBusy
            "
            @click="clearActive"
          >
            <Icon name="trash" :size="13" />
          </button>
        </div>
        <div class="side-context">
          <span v-if="scene">{{ scene.title }}</span>
          <span v-if="sideTab === 'group'" class="muted">
            · {{ groupPlan || `${groupAgents.length} 位 AI 同学` }}
          </span>
        </div>

        <template v-if="sideTab === 'teacher'">
          <div ref="discEl" class="discussion">
            <p v-if="!discussion.length" class="disc-empty">
              向 AI 老师追问这一页的任何内容。老师会记得上文，可以连续对话。
            </p>
            <div v-for="(item, index) in discussion" :key="index" class="disc-msg" :class="item.role">
              <div class="disc-who">{{ item.role === 'user' ? '我' : 'AI 老师' }}</div>
              <div class="disc-bubble">
                {{ item.content }}<span v-if="item.streaming" class="typing"><i /><i /><i /></span>
              </div>
              <div v-if="item.error" class="msg-error">{{ item.error }}</div>
            </div>
          </div>
          <div class="side-foot">
            <textarea
              v-model="discInput"
              class="textarea"
              rows="2"
              placeholder="向 AI 老师提问…（Enter 发送）"
              @keydown.enter.exact.prevent="ask"
            />
            <div class="row">
              <span class="small muted">带上当前页与上文</span>
              <span class="spacer" />
              <button
                class="btn btn-sm btn-primary"
                type="button"
                :disabled="!lesson || discBusy || !discInput.trim()"
                @click="ask"
              >
                {{ discBusy ? '思考中…' : '发送' }}
              </button>
            </div>
          </div>
        </template>

        <template v-else>
          <div ref="groupEl" class="discussion group-discussion">
            <div v-if="!groupMessages.length" class="group-intro">
              <p class="small muted" style="margin: 0">
                三位 AI 同学会从不同角度加入讨论。你可以先让小组开场，也可以直接发言。
              </p>
              <div class="participants">
                <div v-for="agent in groupAgents" :key="agent.id" class="participant">
                  <span class="avatar">{{ agent.name.slice(1) }}</span>
                  <div class="participant-text">
                    <strong>{{ agent.name }}</strong>
                    <span>{{ agent.role }}</span>
                  </div>
                </div>
              </div>
            </div>

            <template v-for="(item, index) in groupMessages" :key="index">
              <div v-if="item.role === 'system'" class="group-system">{{ item.content }}</div>
              <div v-else-if="item.role === 'user'" class="disc-msg user">
                <div class="disc-who">我</div>
                <div class="disc-bubble">{{ item.content }}</div>
              </div>
              <div v-else class="disc-msg teacher group-msg">
                <div class="disc-who">
                  <span class="avatar avatar-sm">{{ item.agent?.name?.slice(1) }}</span>
                  {{ item.agent?.name || '同学' }}
                  <span class="muted">· {{ item.agent?.role || '' }}</span>
                </div>
                <div class="disc-bubble">
                  {{ item.content }}<span v-if="item.streaming" class="typing"><i /><i /><i /></span>
                </div>
                <div v-if="item.error" class="msg-error">{{ item.error }}</div>
              </div>
            </template>
          </div>
          <div class="side-foot">
            <textarea
              v-model="groupInput"
              class="textarea"
              rows="2"
              placeholder="加入小组讨论…（Enter 发言）"
              @keydown.enter.exact.prevent="askGroup(false)"
            />
            <div class="row">
              <button
                class="btn btn-sm"
                type="button"
                :disabled="!lesson || groupBusy"
                @click="askGroup(true)"
              >
                <Icon name="spark" :size="12" />
                让小组先讨论
              </button>
              <span class="spacer" />
              <button
                class="btn btn-sm btn-primary"
                type="button"
                :disabled="!lesson || groupBusy || !groupInput.trim()"
                @click="askGroup(false)"
              >
                {{ groupBusy ? '讨论中…' : '发言' }}
              </button>
            </div>
          </div>
        </template>
      </aside>
    </div>

    <GroupSettingsDialog
      v-if="groupSettingsOpen"
      @close="groupSettingsOpen = false"
      @saved="onGroupSaved"
    />
  </section>
</template>
