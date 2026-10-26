<script setup>
import { computed, onMounted } from 'vue'
import { api } from '../api'
import { notify, refreshProgress, state, switchView } from '../store'
import Icon from '../components/Icon.vue'

const progress = computed(() => state.progress)

onMounted(refreshProgress)

async function reset() {
  if (!window.confirm('清空所有学习记录？此操作不可撤销。')) return
  try {
    await api.progress.reset()
    await refreshProgress()
    notify('学习记录已清空')
  } catch (error) {
    notify(error.message, 'error')
  }
}

function pct(value) {
  return `${Math.round((value || 0) * 100)}%`
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function goPractice() {
  switchView('quiz')
}
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h1>学习进度</h1>
        <p>掌握度按最近几次作答加权计算；证据不足时不会直接判定为「已掌握」。</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-sm" type="button" @click="refreshProgress">刷新</button>
        <button class="btn btn-sm btn-danger" type="button" @click="reset">清空记录</button>
      </div>
    </header>

    <div class="content">
      <div class="wide">
        <div class="stat-grid">
          <div class="stat">
            <div class="value">{{ progress.stats?.topics || 0 }}</div>
            <div class="label">学习主题</div>
          </div>
          <div class="stat">
            <div class="value">{{ progress.stats?.attempts || 0 }}</div>
            <div class="label">累计作答</div>
          </div>
          <div class="stat">
            <div class="value">{{ pct(progress.stats?.average_mastery) }}</div>
            <div class="label">平均掌握度</div>
          </div>
        </div>

        <div class="section">
          <div class="section-head">
            <h2>下一步建议</h2>
            <button class="btn btn-sm" type="button" @click="goPractice">
              去练习
              <Icon name="arrow" :size="12" />
            </button>
          </div>
          <div class="stack">
            <div v-for="(item, index) in progress.recommendations" :key="index" class="reco">
              <Icon name="spark" :size="14" style="margin-top: 3px; flex: none" />
              <span>{{ item.reason }}</span>
            </div>
          </div>
        </div>

        <div class="section">
          <div class="section-head">
            <h2>主题掌握度</h2>
            <span class="small muted">最近表现权重更高</span>
          </div>

          <div v-if="!progress.topics?.length" class="empty-state">
            <p>还没有记录。做一次随堂测验，这里就会生成你的掌握度曲线。</p>
          </div>

          <div v-else class="topic-list">
            <div v-for="item in progress.topics" :key="item.topic" class="topic">
              <div class="topic-head">
                <div class="topic-name">{{ item.topic }}</div>
                <div class="topic-meta">{{ item.label }} · {{ pct(item.mastery) }} · {{ item.attempts }} 次作答</div>
              </div>
              <div class="bar"><span :style="{ width: pct(item.mastery) }" /></div>
              <div class="topic-meta">更新于 {{ formatTime(item.updated_at) }}</div>
              <div v-if="item.points?.length" class="points">
                <span v-for="point in item.points" :key="point.name" class="point-chip">
                  {{ point.name }}
                  <b>{{ pct(point.mastery) }}</b>
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="section">
          <div class="section-head">
            <h2>最近活动</h2>
          </div>
          <div v-if="!progress.events?.length" class="empty-state">
            <p>暂无活动记录。</p>
          </div>
          <div v-else class="events">
            <div v-for="(event, index) in progress.events" :key="index" class="event">
              <time>{{ formatTime(event.ts) }}</time>
              <span v-if="event.summary">{{ event.summary }}</span>
              <span v-else>{{ event.topic }} · {{ event.point }} · {{ pct(event.score) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
