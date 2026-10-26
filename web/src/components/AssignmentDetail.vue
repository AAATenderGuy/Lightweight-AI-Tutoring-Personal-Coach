<script setup>
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { notify } from '../store'
import Icon from './Icon.vue'

const props = defineProps({
  detail: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['refresh', 'practice', 'remove', 'export', 'toggle'])

const kindLabel = computed(() => (props.detail?.kind === 'quiz' ? '随堂测验' : '课后作业'))
const isFile = computed(() => props.detail?.submission_mode === 'file')

const gradeOpen = ref(false)
const grading = reactive({
  submission: null,
  score: 100,
  feedback: '',
  note: '',
  busy: false,
  error: '',
})

function openGrade(submission) {
  grading.submission = submission
  grading.score = Math.round((submission.teacher_score ?? submission.score ?? 0) * 100)
  grading.feedback = submission.teacher_feedback || ''
  grading.note = ''
  grading.error = ''
  gradeOpen.value = true
}

function closeGrade() {
  if (!grading.busy) gradeOpen.value = false
}

async function submitGrade() {
  if (!grading.submission || grading.busy) return
  const score = Number(grading.score)
  if (!Number.isFinite(score) || score < 0 || score > 100) {
    grading.error = '分数需要在 0–100 之间。'
    return
  }
  grading.busy = true
  grading.error = ''
  try {
    await api.teacher.submissions.grade(grading.submission.id, {
      score,
      feedback: grading.feedback.trim(),
      note: grading.note.trim(),
    })
    gradeOpen.value = false
    notify('复核分数已保存，学生端立即生效')
    emit('refresh')
  } catch (error) {
    grading.error = error.message
  } finally {
    grading.busy = false
  }
}

async function regradeAi(submission) {
  try {
    await api.teacher.submissions.regradeAi(submission.id)
    notify('已重新批改')
    emit('refresh')
  } catch (error) {
    notify(error.message, 'error')
  }
}

async function downloadSub(submission, file) {
  try {
    const name = await api.teacher.submissions.downloadFile(submission.id, file.id, file.filename)
    notify(`已下载 ${name}`)
  } catch (error) {
    notify(error.message, 'error')
  }
}

const stateInfo = computed(() => {
  const map = {
    open: { label: '进行中', cls: 'accent' },
    expired: { label: '已过截止', cls: '' },
    closed: { label: '已关闭', cls: '' },
  }
  return map[props.detail?.state] || { label: '进行中', cls: 'accent' }
})

const weakPoints = computed(() =>
  (props.detail?.knowledge || []).filter((item) => item.wrong > 0).slice(0, 3).map((item) => item.point),
)

function pct(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function scorePct(value) {
  return Math.round((Number(value) || 0) * 100)
}

function formatTime(ts) {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function confirmRemove() {
  if (!props.detail) return
  if (!window.confirm(`删除作业《${props.detail.title}》？学生的提交记录会一起删除，且不可恢复。`)) return
  emit('remove')
}
</script>

<template>
  <div class="panel assignment-detail">
    <div v-if="loading" class="loading-stage" style="min-height: 320px; border: 0">
      <div class="spinner" />
      <strong>正在读取作业数据</strong>
      <span class="small muted">统计每道题的错误率和提交情况…</span>
    </div>

    <div v-else-if="!detail" class="empty-state" style="padding: 70px 20px">
      <p>从左侧选择一份作业，查看提交进度与错题分布。</p>
    </div>

    <template v-else>
      <div class="detail-head">
        <div style="min-width: 0">
          <div class="row" style="gap: 6px; flex-wrap: wrap; margin-bottom: 6px">
            <span class="chip">{{ detail.class_name }}</span>
            <span class="chip">{{ kindLabel }}</span>
            <span class="chip" :class="stateInfo.cls">{{ stateInfo.label }}</span>
            <span class="chip">{{ isFile ? '文件提交' : `共 ${detail.question_count} 题` }}</span>
          </div>
          <h2 class="detail-title">{{ detail.title }}</h2>
          <p class="small muted" style="margin: 4px 0 0">
            主题：{{ detail.topic }} · 布置于 {{ formatTime(detail.created_at) }}
            <template v-if="detail.due_at"> · 截止 {{ formatTime(detail.due_at) }}</template>
            <template v-else> · 未设截止</template>
          </p>
          <p v-if="detail.instructions" class="detail-note">{{ detail.instructions }}</p>
          <p v-if="detail.rubric" class="detail-note"><b>评分要点：</b>{{ detail.rubric }}</p>
        </div>
        <div class="detail-actions">
          <button class="btn btn-sm" type="button" @click="emit('refresh')">
            <Icon name="refresh" :size="13" />
            刷新
          </button>
          <button class="btn btn-sm" type="button" @click="emit('export')">
            <Icon name="download" :size="13" />
            导出明细
          </button>
          <button
            v-if="!isFile"
            class="btn btn-sm"
            type="button"
            :disabled="!detail.submissions?.length"
            @click="emit('practice', weakPoints)"
          >
            <Icon name="spark" :size="13" />
            薄弱点补练
          </button>
          <button class="btn btn-sm" type="button" @click="emit('toggle')">
            {{ detail.closed ? '重新开放' : '关闭作业' }}
          </button>
          <button class="btn btn-sm btn-danger" type="button" @click="confirmRemove">
            <Icon name="trash" :size="13" />
          </button>
        </div>
      </div>

      <div class="stat-grid stat-grid-3" style="margin-top: 16px">
        <div class="stat">
          <div class="value">{{ detail.submitted }}<span class="unit">/ {{ detail.total }}</span></div>
          <div class="label">已提交人数</div>
        </div>
        <div class="stat">
          <div class="value">{{ pct(detail.completion) }}</div>
          <div class="label">提交率</div>
        </div>
        <div class="stat">
          <div class="value">{{ scorePct(detail.avg_score) }}<span class="unit">分</span></div>
          <div class="label">班级平均分</div>
        </div>
      </div>

      <div v-if="detail.missing?.length" class="missing-box">
        <div class="small muted" style="margin-bottom: 6px">未提交（{{ detail.missing.length }} 人）</div>
        <div class="chips">
          <span v-for="student in detail.missing" :key="student.id" class="chip">
            {{ student.name }}<template v-if="student.number"> · {{ student.number }}</template>
          </span>
        </div>
      </div>
      <div v-else-if="detail.total" class="missing-box done">
        <Icon name="check" :size="14" />
        全班已提交，可以开始讲评了。
      </div>

      <div v-if="!isFile" class="section" style="margin-top: 22px">
        <div class="section-head">
          <h2>错题分布</h2>
          <span class="small muted">按答错人数占已作答人数的比例排序</span>
        </div>
        <div v-if="!detail.questions?.length" class="empty-state"><p>这份作业没有题目数据。</p></div>
        <div v-else class="question-list">
          <div v-for="item in detail.questions" :key="item.id" class="question-row">
            <div class="question-main">
              <div class="question-text">{{ item.index }}. {{ item.question }}</div>
              <div class="small muted">
                知识点：{{ item.knowledge_point || '未标注' }} · 已答 {{ item.answered }} 人 · 答错 {{ item.wrong }} 人
              </div>
              <div v-if="item.correct_text" class="small muted" style="margin-top: 2px">
                参考答案：{{ item.correct_text }}
              </div>
            </div>
            <div class="question-rate">
              <div class="bar error" style="margin: 0 0 4px"><span :style="{ width: pct(item.error_rate) }" /></div>
              <span class="small" :class="item.error_rate >= 0.5 ? 'rate-high' : 'muted'">
                错误率 {{ pct(item.error_rate) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!isFile" class="section">
        <div class="section-head">
          <h2>知识点统计</h2>
          <button
            class="btn btn-sm btn-ghost"
            type="button"
            :disabled="!detail.knowledge?.length"
            @click="emit('practice', detail.knowledge.filter((k) => k.wrong).slice(0, 4).map((k) => k.point))"
          >
            按薄弱点补练
          </button>
        </div>
        <div v-if="!detail.knowledge?.length" class="empty-state"><p>还没有提交记录。</p></div>
        <table v-else class="data-table">
          <thead>
            <tr><th>知识点</th><th class="num">作答</th><th class="num">答错</th><th class="num">平均分</th><th style="width: 120px">错误率</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in detail.knowledge" :key="item.point">
              <td>{{ item.point }}</td>
              <td class="num">{{ item.attempts }}</td>
              <td class="num">{{ item.wrong }}</td>
              <td class="num">{{ scorePct(item.avg_score) }}</td>
              <td>
                <div class="bar error" style="margin: 0"><span :style="{ width: pct(item.error_rate) }" /></div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="isFile" class="section">
        <div class="section-head">
          <h2>提交与批改</h2>
          <span class="small muted">
            AI 初评 {{ detail.graded_ai || 0 }} 份 · 已复核 {{ detail.graded_teacher || 0 }} 份
            <template v-if="detail.needs_review_count"> · {{ detail.needs_review_count }} 份待复核</template>
          </span>
        </div>
        <div v-if="!detail.submissions?.length" class="empty-state"><p>还没有人提交。</p></div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>学生</th><th>文件</th><th class="num">AI 初评</th><th class="num">最终分</th>
              <th>状态</th><th>提交时间</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in detail.submissions" :key="item.id">
              <td>
                <div>{{ item.student_name }}</div>
                <div v-if="item.ai_feedback" class="small muted" style="max-width: 260px">
                  {{ item.ai_feedback.slice(0, 60) }}<template v-if="item.ai_feedback.length > 60">…</template>
                </div>
              </td>
              <td>
                <div v-for="file in item.files" :key="file.id">
                  <a href="#" @click.prevent="downloadSub(item, file)">{{ file.filename }}</a>
                </div>
                <span v-if="!item.files?.length" class="muted">—</span>
              </td>
              <td class="num">{{ item.ai_score != null ? scorePct(item.ai_score) : '—' }}</td>
              <td class="num"><b>{{ scorePct(item.score) }}</b></td>
              <td>
                <span v-if="item.teacher_score != null" class="chip accent">已复核</span>
                <span v-else-if="item.needs_review" class="chip">待复核</span>
                <span v-else class="chip">AI 已评</span>
              </td>
              <td class="muted">{{ formatTime(item.submitted_at) }}</td>
              <td class="row-actions">
                <button class="btn btn-sm" type="button" @click="openGrade(item)">改分</button>
                <button class="btn btn-sm btn-ghost" type="button" @click="regradeAi(item)">AI 重批</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="!isFile" class="section">
        <div class="section-head">
          <h2>学生成绩</h2>
          <span class="small muted">同一学生重复提交只保留最后一次</span>
        </div>
        <div v-if="!detail.submissions?.length" class="empty-state"><p>还没有人提交。</p></div>
        <table v-else class="data-table">
          <thead>
            <tr><th>姓名</th><th>学号</th><th class="num">得分</th><th class="num">答对</th><th class="num">提交次数</th><th>提交时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in detail.submissions" :key="item.student_id">
              <td>{{ item.student_name }}</td>
              <td class="muted">{{ item.number || '—' }}</td>
              <td class="num"><b>{{ scorePct(item.score) }}</b></td>
              <td class="num">{{ item.correct_count }} / {{ item.total }}</td>
              <td class="num">{{ item.attempts }}</td>
              <td class="muted">{{ formatTime(item.submitted_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-if="gradeOpen" class="overlay" @mousedown.self="closeGrade">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="grade-title">
        <div class="modal-head">
          <div>
            <h2 id="grade-title">复核成绩</h2>
            <p>
              {{ grading.submission?.student_name }} · AI 初评
              {{ grading.submission?.ai_score != null ? scorePct(grading.submission.ai_score) : '—' }} 分
            </p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="closeGrade">
            <Icon name="close" :size="17" />
          </button>
        </div>
        <div class="modal-body stack">
          <div class="field">
            <label for="grade-score">最终分数（0–100）</label>
            <input id="grade-score" v-model.number="grading.score" class="input" type="number" min="0" max="100" step="1" />
          </div>
          <div class="field">
            <label for="grade-feedback">评语（学生可见）</label>
            <textarea
              id="grade-feedback"
              v-model="grading.feedback"
              class="textarea"
              rows="4"
              maxlength="2000"
              placeholder="写给学生看的反馈：哪里做得好、哪里还需要补充。"
            />
          </div>
          <div class="field">
            <label for="grade-note">内部备注（学生不可见）</label>
            <input id="grade-note" v-model="grading.note" class="input" maxlength="300" placeholder="例：与上次相比结构清楚很多" />
          </div>
          <div class="hint-box">
            保存后学生端立即看到新的分数和评语；AI 初评分与修改记录会保留在提交记录里。
          </div>
          <div v-if="grading.error" class="msg-error">{{ grading.error }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeGrade">取消</button>
          <button class="btn btn-primary" type="button" :disabled="grading.busy" @click="submitGrade">
            {{ grading.busy ? '保存中…' : '保存复核' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
