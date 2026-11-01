<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { notify } from '../store'
import Icon from './Icon.vue'
import TriCheckbox from './TriCheckbox.vue'

const props = defineProps({
  klass: { type: Object, required: true },
})
const emit = defineEmits(['close', 'imported'])

const text = ref('')
const defaultPassword = ref('')
const file = ref(null)
const busy = ref(false)
const error = ref('')
const result = ref(null)
const copied = ref(false)

// ---- 名单预览：粘贴的文本先在本地解析成行，允许取消勾选个别行不导入
const HEADER_WORDS = [
  '学号', '学籍号', '考号', '账号', 'studentid', 'student_id', 'number', 'id',
  '姓名', 'name', '密码', 'password',
]

function splitCells(line) {
  if (line.includes('\t')) return line.split('\t')
  if (line.includes(';')) return line.split(';')
  return line.split(',')
}

const preview = computed(() => {
  const lines = text.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!lines.length) return { header: '', rows: [] }
  const firstCells = splitCells(lines[0]).map((cell) => cell.trim().toLowerCase())
  const hasHeader = firstCells.some((cell) => HEADER_WORDS.includes(cell))
  const body = hasHeader ? lines.slice(1) : lines
  const rows = body.map((line, index) => {
    const cells = splitCells(line).map((cell) => cell.trim())
    return {
      key: `row-${index}`,
      number: cells[0] || '',
      name: cells[1] || '',
      password: cells[2] || '',
      raw: line,
    }
  }).filter((row) => row.number || row.name)
  return { header: hasHeader ? lines[0] : '', rows }
})

const picked = ref(new Set())
watch(preview, (value) => {
  picked.value = new Set(value.rows.map((row) => row.key))
}, { immediate: true })

const allPicked = computed(() => preview.value.rows.length > 0
  && picked.value.size === preview.value.rows.length)
const somePicked = computed(() => picked.value.size > 0 && !allPicked.value)

function toggleAll(next) {
  picked.value = next ? new Set(preview.value.rows.map((row) => row.key)) : new Set()
}

function toggleRow(key) {
  const next = new Set(picked.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  picked.value = next
}

/** 全部勾选时原样提交，交给后端解析；筛过才按勾选行重组文本。 */
function rosterText() {
  const { header, rows } = preview.value
  if (!rows.length || picked.value.size === rows.length) return text.value
  const chosen = rows.filter((row) => picked.value.has(row.key))
  return [header, ...chosen.map((row) => row.raw)].filter(Boolean).join('\n')
}

const canSubmit = computed(() => Boolean((text.value.trim() && picked.value.size) || file.value))

function onFile(event) {
  file.value = event.target.files?.[0] || null
  error.value = ''
}

async function submit() {
  if (busy.value || !canSubmit.value) return
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('text', rosterText())
    form.append('default_password', defaultPassword.value.trim())
    if (file.value) form.append('file', file.value)
    const data = await api.teacher.classes.importRoster(props.klass.id, form)
    result.value = data
    notify(`已导入 ${data.total} 人（新增 ${data.created}，更新 ${data.updated}）`)
    emit('imported', data)
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function copyAll() {
  if (!result.value) return
  const lines = result.value.credentials.map((item) => `${item.number}\t${item.name}\t${item.password}`)
  const payload = `学号\t姓名\t初始密码\n${lines.join('\n')}`
  try {
    await navigator.clipboard.writeText(payload)
    copied.value = true
    notify('已复制名单与初始密码')
    window.setTimeout(() => { copied.value = false }, 2500)
  } catch {
    window.prompt('复制下面的内容：', payload)
  }
}

async function downloadRoster() {
  try {
    const name = await api.teacher.classes.rosterCsv(props.klass.id)
    notify(`已导出 ${name}`)
  } catch (err) {
    notify(err.message, 'error')
  }
}

function close() {
  if (!busy.value) emit('close')
}
</script>

<template>
  <div class="overlay" @mousedown.self="close">
    <div class="modal modal-wide modal-flex" role="dialog" aria-modal="true" aria-labelledby="roster-title">
      <div class="modal-head">
        <div>
          <h2 id="roster-title">导入学生名单</h2>
          <p>{{ klass.name }} · 学生之后用「学号 + 密码」登录，不再需要邀请码。</p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <template v-if="!result">
          <div class="hint-box">
            支持 CSV / TXT，逗号、分号、制表符都可以。表头顺序不限，列名可用
            <code>学号</code>、<code>姓名</code>、<code>密码</code>；
            没有密码列时按「默认密码」或自动生成 6 位初始密码。
          </div>

          <pre class="roster-sample">学号,姓名,密码
2024001,张三,zhang123
2024002,李四,li456</pre>

          <div class="field">
            <label for="roster-file">上传名单文件（可选）</label>
            <input id="roster-file" class="input" type="file" accept=".csv,.txt" @change="onFile" />
            <span v-if="file" class="small muted">已选择：{{ file.name }}</span>
          </div>

          <div class="field">
            <label for="roster-text">或直接粘贴名单</label>
            <textarea
              id="roster-text"
              v-model="text"
              class="textarea"
              rows="7"
              spellcheck="false"
              placeholder="从 Excel 复制时，可以直接粘贴两列或三列。"
            />
          </div>

          <div class="field">
            <label for="roster-default">默认初始密码（可选）</label>
            <input
              id="roster-default"
              v-model="defaultPassword"
              class="input"
              maxlength="72"
              placeholder="留空则每个学生随机生成 6 位数字"
            />
          </div>

          <div v-if="preview.rows.length" class="roster-preview">
            <div class="bulk-bar">
              <TriCheckbox
                :checked="allPicked"
                :indeterminate="somePicked"
                :label="picked.size ? `已选 ${picked.size}` : `全选 ${preview.rows.length} 人`"
                @change="toggleAll"
              />
              <span class="spacer" />
              <span class="small muted">取消勾选的行不会被导入</span>
            </div>
            <table class="data-table">
              <thead>
                <tr>
                  <th class="check-col"><span class="sr-only">选择</span></th>
                  <th>学号</th>
                  <th>姓名</th>
                  <th>密码</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in preview.rows" :key="row.key" :class="{ 'is-off': !picked.has(row.key) }">
                  <td class="check-col">
                    <TriCheckbox :checked="picked.has(row.key)" @change="toggleRow(row.key)" />
                  </td>
                  <td>{{ row.number || '—' }}</td>
                  <td>{{ row.name || '—' }}</td>
                  <td><code>{{ row.password || '自动生成' }}</code></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="error" class="msg-error">{{ error }}</div>
        </template>

        <template v-else>
          <div class="test-result ok">
            已导入 {{ result.total }} 人（新增 {{ result.created }}，更新 {{ result.updated }}）。
            下面这些初始密码只显示这一次，请及时发给学生。
          </div>
          <div v-if="result.errors?.length" class="msg-error" style="font-weight: 400">
            跳过 {{ result.errors.length }} 行：{{ result.errors.slice(0, 3).join('；') }}
          </div>
          <div v-if="result.duplicates" class="small muted">
            名单里有 {{ result.duplicates }} 个重复学号，已按最后一行处理。
          </div>

          <div class="row" style="gap: 8px; flex-wrap: wrap; margin: 10px 0">
            <button class="btn btn-sm" type="button" @click="copyAll">
              <Icon name="copy" :size="13" />
              {{ copied ? '已复制' : '复制全部' }}
            </button>
            <button class="btn btn-sm" type="button" @click="downloadRoster">
              <Icon name="download" :size="13" />
              下载名单（不含密码）
            </button>
          </div>

          <table class="data-table">
            <thead>
              <tr><th>学号</th><th>姓名</th><th>初始密码</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in result.credentials" :key="item.number">
                <td>{{ item.number }}</td>
                <td>{{ item.name }}</td>
                <td><code>{{ item.password }}</code></td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>

      <div class="modal-foot">
        <template v-if="!result">
          <button class="btn" type="button" :disabled="busy" @click="close">取消</button>
          <button class="btn btn-primary" type="button" :disabled="busy || !canSubmit" @click="submit">
            {{ busy ? '导入中…' : '导入名单' }}
          </button>
        </template>
        <button v-else class="btn btn-primary" type="button" @click="close">完成</button>
      </div>
    </div>
  </div>
</template>
