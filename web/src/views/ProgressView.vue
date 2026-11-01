<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { notify, refreshProgress, state, switchView } from '../store'
import Icon from '../components/Icon.vue'

const progress = computed(() => state.progress)

const scroller = ref(null)
const track = ref(null)
const linePath = ref('')
const lineSize = ref({ w: 0, h: 0 })
const drawn = ref(false)

let lastSnap = -1
let drawTimer = 0
let snapTimer = 0
let observer = null
const reduceMotion =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : { matches: false }

function cards() {
  if (!track.value) return []
  return Array.from(track.value.querySelectorAll('.topic-card'))
}

/** 用首尾卡片中心连一条水平基线，卡片本身不透明，线只在缝隙里露出来。 */
function measure() {
  const el = track.value
  if (!el) return
  const width = el.offsetWidth
  const height = el.offsetHeight
  if (!width || !height) return
  lineSize.value = { w: width, h: height }
  const list = cards()
  if (list.length < 2) {
    linePath.value = ''
    return
  }
  const y = Math.round(height / 2)
  const first = list[0]
  const last = list[list.length - 1]
  const x0 = Math.round(first.offsetLeft + first.offsetWidth / 2)
  const x1 = Math.round(last.offsetLeft + last.offsetWidth / 2)
  linePath.value = `M ${x0} ${y} L ${x1} ${y}`
  replay()
}

/** 重放画线：先把 pathLength 归零，下一帧再推到 1，让过渡重新跑一遍。 */
function replay() {
  window.clearTimeout(drawTimer)
  if (reduceMotion.matches) {
    drawn.value = true
    return
  }
  drawn.value = false
  drawTimer = window.setTimeout(() => {
    drawn.value = true
  }, 40)
}

function nearestIndex() {
  const el = scroller.value
  const list = cards()
  if (!el || !list.length) return -1
  const center = el.scrollLeft + el.clientWidth / 2
  let best = 0
  let bestDistance = Infinity
  list.forEach((card, index) => {
    const cardCenter = card.offsetLeft + card.offsetWidth / 2
    const distance = Math.abs(cardCenter - center)
    if (distance < bestDistance) {
      bestDistance = distance
      best = index
    }
  })
  return best
}

/** 滚动停稳后再判断吸到了哪张卡，换卡才重画，避免滚动中反复触发。 */
function onScroll() {
  window.clearTimeout(snapTimer)
  snapTimer = window.setTimeout(() => {
    const index = nearestIndex()
    if (index === lastSnap) return
    lastSnap = index
    replay()
  }, 120)
}

onMounted(async () => {
  await refreshProgress()
  await nextTick()
  measure()
  if (typeof ResizeObserver !== 'undefined' && track.value) {
    observer = new ResizeObserver(() => measure())
    observer.observe(track.value)
  }
})

onBeforeUnmount(() => {
  window.clearTimeout(drawTimer)
  window.clearTimeout(snapTimer)
  if (observer) observer.disconnect()
})

watch(
  () => progress.value.topics?.length || 0,
  async () => {
    await nextTick()
    measure()
  },
)

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
            <span class="small muted">左右滑动，卡片会吸附到中间</span>
          </div>

          <div v-if="!progress.topics?.length" class="empty-state">
            <p>还没有记录。做一次随堂测验，这里就会生成你的掌握度曲线。</p>
          </div>

          <div v-else ref="scroller" class="topic-scroller" @scroll.passive="onScroll">
            <div ref="track" class="topic-track">
              <svg
                v-if="linePath"
                class="topic-line"
                :width="lineSize.w"
                :height="lineSize.h"
                :viewBox="`0 0 ${lineSize.w} ${lineSize.h}`"
                aria-hidden="true"
              >
                <path :d="linePath" pathLength="1" :class="{ 'is-drawn': drawn }" />
              </svg>
              <article v-for="item in progress.topics" :key="item.topic" class="topic topic-card">
                <div class="topic-head">
                  <div class="topic-name">{{ item.topic }}</div>
                  <div class="topic-meta">{{ item.label }}</div>
                </div>
                <div class="bar"><span :style="{ width: pct(item.mastery) }" /></div>
                <div class="topic-meta">{{ pct(item.mastery) }} · {{ item.attempts }} 次作答</div>
                <div v-if="item.points?.length" class="points">
                  <span v-for="point in item.points" :key="point.name" class="point-chip">
                    {{ point.name }}
                    <b>{{ pct(point.mastery) }}</b>
                  </span>
                </div>
                <div class="topic-meta">更新于 {{ formatTime(item.updated_at) }}</div>
              </article>
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
