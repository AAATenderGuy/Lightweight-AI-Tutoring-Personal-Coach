<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { notify, refreshProgress, state, switchView } from '../store'
import Icon from '../components/Icon.vue'

const form = reactive({ topic: '', count: 4, difficulty: 'medium' })
const quiz = ref(null)
const answers = reactive({})
const revealed = reactive({})
const result = ref(null)
const generating = ref(false)
const submitting = ref(false)
const similarBusy = ref(false)
const errorText = ref('')

const counts = [3, 4, 5, 6]
const difficulties = [
  { value: 'easy', label: '基础' },
  { value: 'medium', label: '标准' },
  { value: 'hard', label: '挑战' },
]

function difficultyLabel(value) {
  return difficulties.find((item) => item.value === value)?.label || value
}

const answered = computed(() => {
  if (!quiz.value) return 0
  return quiz.value.questions.filter((question) => String(answers[question.id] ?? '').trim() !== '').length
})

const progressPercent = computed(() => {
  if (!quiz.value?.questions?.length) return 0
  return Math.round((answered.value / quiz.value.questions.length) * 100)
})

onMounted(() => {
  if (state.pendingQuizTopic) {
    form.topic = state.pendingQuizTopic
    state.pendingQuizTopic = ''
  }
})

function clearState() {
  Object.keys(answers).forEach((key) => delete answers[key])
  Object.keys(revealed).forEach((key) => delete revealed[key])
}

function clearQuiz() {
  quiz.value = null
  result.value = null
  errorText.value = ''
  clearState()
}

async function generate() {
  if (!form.topic.trim()) {
    notify('先写一个测验主题')
    return
  }
  generating.value = true
  errorText.value = ''
  result.value = null
  try {
    const data = await api.quiz.generate({
      topic: form.topic.trim(),
      material_ids: [],
      count: Number(form.count),
      difficulty: form.difficulty,
    })
    quiz.value = data.quiz
    clearState()
  } catch (error) {
    errorText.value = error.message
    notify(error.message, 'error')
  } finally {
    generating.value = false
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
    const data = await api.quiz.submit(quiz.value.id, payload)
    result.value = data
    quiz.value = null
    await refreshProgress()
    notify(`本次得分 ${Math.round(data.score * 100)} 分`)
    window.scrollTo({ top: 0 })
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    submitting.value = false
  }
}

async function similarQuestions() {
  const sourceId = result.value?.quiz_id || quiz.value?.id
  if (!sourceId || similarBusy.value) return
  similarBusy.value = true
  try {
    const focusPoints = result.value
      ? [...new Set(
          result.value.results
            .filter((item) => !item.correct)
            .map((item) => item.knowledge_point)
            .filter(Boolean),
        )]
      : []
    const data = await api.quiz.similar(sourceId, { count: 4, focus_points: focusPoints })
    result.value = null
    quiz.value = data.quiz
    errorText.value = ''
    clearState()
    notify('已生成相似题，可先作答，也可直接查看详解')
    window.scrollTo({ top: 0 })
  } catch (error) {
    notify(error.message, 'error')
  } finally {
    similarBusy.value = false
  }
}

function again() {
  clearQuiz()
}

function toggleReveal(questionId) {
  revealed[questionId] = !revealed[questionId]
}

function isRevealed(questionId) {
  return Boolean(revealed[questionId])
}

function revealAll() {
  if (!quiz.value) return
  quiz.value.questions.forEach((question) => {
    revealed[question.id] = true
  })
}

function displayAnswer(item) {
  if (item.type === 'single') {
    const index = Number(item.submitted)
    if (!Number.isInteger(index) || index < 0) return '未作答'
    const text = item.options?.[index]
    if (text) return `${'ABCDEF'[index]}. ${text}`
    return `选项 ${'ABCDEF'[index]}`
  }
  return item.submitted || '未作答'
}

function correctDisplay(item) {
  if (item.type === 'single') {
    const index = Number(item.correct_index)
    if (Number.isInteger(index) && item.options?.[index]) {
      return `${'ABCDEF'[index]}. ${item.options[index]}`
    }
  }
  return item.correct_answer || '（未提供）'
}

function scorePercent() {
  return Math.round((result.value?.score || 0) * 100)
}
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h1>随堂测验</h1>
        <p>提交后逐题查看答案与详解；还能让 AI 按薄弱知识点继续出「举一反三」的变式题。</p>
      </div>
      <div class="page-actions">
        <span v-if="state.settings.demo" class="chip">演示模式 · 关键词评分</span>
        <button v-if="quiz || result" class="btn btn-sm" type="button" @click="again">
          <Icon name="refresh" :size="13" />
          重新出题
        </button>
      </div>
    </header>

    <div class="content">
      <div class="wide">
        <div v-if="result" class="stack">
          <div class="result-head">
            <div class="row" style="justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap">
              <div>
                <div class="small muted">{{ result.topic }}</div>
                <div class="result-score">
                  {{ scorePercent() }}<span style="font-size: 14px; color: var(--ink-3); font-weight: 400"> / 100</span>
                </div>
                <div class="small muted">
                  答对 {{ result.correct_count }} / {{ result.total }} 题 · 已计入学习进度
                </div>
              </div>
              <div class="result-actions">
                <button class="btn btn-sm" type="button" @click="switchView('progress')">查看进度</button>
                <button class="btn btn-sm" type="button" @click="again">重新出题</button>
                <button class="btn btn-sm btn-primary" type="button" :disabled="similarBusy" @click="similarQuestions">
                  <Icon name="spark" :size="13" />
                  {{ similarBusy ? '生成中…' : '举一反三' }}
                </button>
              </div>
            </div>
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
              <span class="small muted">得分 {{ Math.round(item.score * 100) }}%</span>
            </div>

            <div class="q">{{ index + 1 }}. {{ item.question }}</div>

            <div class="answer-grid">
              <div class="answer-cell">
                <span class="answer-label">你的作答</span>
                <div class="answer-text">{{ displayAnswer(item) }}</div>
              </div>
              <div class="answer-cell">
                <span class="answer-label">正确答案</span>
                <div class="answer-text strong">{{ correctDisplay(item) }}</div>
              </div>
            </div>

            <div class="explain-block">
              <span class="answer-label">解析</span>{{ item.explanation || '暂无解析' }}
            </div>

            <div v-if="item.type !== 'single' && item.feedback" class="feedback-line">
              {{ item.feedback }}
            </div>
          </div>
        </div>

        <div v-else-if="quiz" class="quiz-layout">
          <div class="quiz-main">
            <div class="result-head">
              <div class="row" style="gap: 8px; flex-wrap: wrap">
                <span class="small muted">{{ quiz.topic }} · {{ difficultyLabel(quiz.difficulty) }}</span>
                <span v-if="quiz.practice" class="chip accent">举一反三</span>
              </div>
              <div style="font-size: 17px; font-weight: 650; margin-top: 2px">{{ quiz.title }}</div>
              <div class="small muted">
                {{
                  quiz.practice
                    ? '根据上一组题的薄弱知识点生成，可先作答，也可直接查看答案与详解。'
                    : `共 ${quiz.questions.length} 题，提交后显示逐题答案与详解。`
                }}
              </div>
            </div>

            <div v-for="(question, index) in quiz.questions" :key="question.id" class="quiz-card">
              <div class="quiz-q-title">{{ index + 1 }}. {{ question.question }}</div>
              <div v-if="question.type === 'single'" class="quiz-options" style="margin-top: 10px">
                <button
                  v-for="(option, optionIndex) in question.options"
                  :key="optionIndex"
                  type="button"
                  class="quiz-option"
                  :class="{
                    selected: answers[question.id] === optionIndex,
                    correct:
                      quiz.practice && isRevealed(question.id) && optionIndex === question.answer_index,
                    wrong:
                      quiz.practice &&
                      isRevealed(question.id) &&
                      answers[question.id] === optionIndex &&
                      optionIndex !== question.answer_index,
                  }"
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

              <div class="row" style="margin-top: 10px; gap: 8px; flex-wrap: wrap">
                <span v-if="question.knowledge_point" class="small muted">
                  知识点：{{ question.knowledge_point }}
                </span>
                <span class="spacer" />
                <button
                  v-if="quiz.practice"
                  class="btn btn-sm"
                  type="button"
                  @click="toggleReveal(question.id)"
                >
                  {{ isRevealed(question.id) ? '收起详解' : '查看答案与详解' }}
                </button>
              </div>

              <div v-if="quiz.practice && isRevealed(question.id)" class="quiz-explain">
                <template v-if="question.type === 'single'">
                  正确答案：{{ 'ABCDEF'[question.answer_index] }}. {{ question.options[question.answer_index] }}
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

          <aside class="quiz-side">
            <div class="quiz-card stack">
              <div>
                <div class="small muted">作答进度</div>
                <div style="font-size: 20px; font-weight: 600">{{ answered }} / {{ quiz.questions.length }}</div>
              </div>
              <div class="bar" style="margin: 0"><span :style="{ width: `${progressPercent}%` }" /></div>
              <button class="btn btn-primary" type="button" :disabled="submitting || !answered" @click="submit">
                {{ submitting ? '评分中…' : '提交并评分' }}
              </button>
              <p class="small muted" style="margin: 0">提交后不可修改，未作答按 0 分计。</p>
            </div>
            <button v-if="quiz.practice" class="btn btn-sm" type="button" @click="revealAll">
              查看全部答案与详解
            </button>
            <div class="hint-box">
              简答题会由模型按评分要点批改；没有配置 API Key 时使用关键词匹配，反馈仅供参考。
            </div>
          </aside>
        </div>

        <div v-else>
          <form class="quiz-form" @submit.prevent="generate">
            <div class="field">
              <label for="quiz-topic">测验主题</label>
              <input
                id="quiz-topic"
                v-model="form.topic"
                class="input"
                placeholder="例：牛顿第二定律的应用"
              />
            </div>
            <div class="grid">
              <div class="field">
                <label for="quiz-count">题量</label>
                <select id="quiz-count" v-model.number="form.count" class="select">
                  <option v-for="value in counts" :key="value" :value="value">{{ value }} 题</option>
                </select>
              </div>
              <div class="field">
                <label for="quiz-difficulty">难度</label>
                <select id="quiz-difficulty" v-model="form.difficulty" class="select">
                  <option v-for="item in difficulties" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </div>
            </div>
            <p class="small muted" style="margin: 0">
              会优先检索资料库中的相关内容；如果资料不足，将基于通用知识出题。
            </p>
            <div class="row">
              <button class="btn btn-primary" type="submit" :disabled="generating || !form.topic.trim()">
                <Icon name="spark" :size="14" />
                {{ generating ? '正在出题…' : '生成测验' }}
              </button>
              <span v-if="state.settings.demo" class="small muted">演示模式会生成简答题，便于走通评分流程</span>
            </div>
          </form>

          <div v-if="generating" class="loading-stage" style="margin-top: 16px; min-height: 220px">
            <div class="spinner" />
            <strong>正在命题</strong>
            <span class="small muted">阅读资料、设计干扰项与解析…</span>
          </div>

          <div v-else class="feature-list">
            <div class="feature">
              <strong>答完能看详解</strong>
              <span>每题给出正确答案、你的作答、解析和知识点，而不只是一个分数。</span>
            </div>
            <div class="feature">
              <strong>举一反三</strong>
              <span>按错题知识点继续出变式题，练到会为止，详解随题可见。</span>
            </div>
            <div class="feature">
              <strong>记录掌握度</strong>
              <span>按最近表现加权，薄弱知识点会进入下一步建议。</span>
            </div>
          </div>

          <div v-if="errorText" class="msg-error" style="margin-top: 16px">{{ errorText }}</div>
        </div>
      </div>
    </div>
  </section>
</template>
