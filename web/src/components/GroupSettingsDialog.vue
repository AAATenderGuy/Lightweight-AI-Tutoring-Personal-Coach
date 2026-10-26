<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { notify } from '../store'
import Icon from './Icon.vue'

const emit = defineEmits(['close', 'saved'])

const agents = ref([])
const maxSpeakers = ref(2)
const loading = ref(true)
const saving = ref(false)
const resetting = ref(false)
const errorText = ref('')

const canAdd = computed(() => agents.value.length < 6)
const canRemove = computed(() => agents.value.length > 2)

async function applyConfig(data) {
  agents.value = (data.agents || []).map((agent) => ({ ...agent }))
  maxSpeakers.value = Number(data.max_speakers || 2)
}

async function load() {
  loading.value = true
  try {
    await applyConfig(await api.lessons.groupAgents())
  } catch (error) {
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

function addAgent() {
  if (!canAdd.value) return
  agents.value.push({
    id: `agent_${Date.now().toString(36)}`,
    name: '新同学',
    role: '补充者',
    instruction: '你负责从另一个角度补充观点，或提出一个具体例子；不要重复其他同学已经说过的内容。',
  })
}

function removeAgent(index) {
  if (!canRemove.value) return
  agents.value.splice(index, 1)
}

async function save() {
  if (agents.value.length < 2) {
    errorText.value = '至少保留 2 位同学。'
    return
  }
  const empty = agents.value.find(
    (agent) => !agent.name.trim() || !agent.role.trim() || !agent.instruction.trim(),
  )
  if (empty) {
    errorText.value = '名字、分工和角色提示词都不能为空。'
    return
  }
  saving.value = true
  errorText.value = ''
  try {
    const data = await api.lessons.saveGroupAgents({
      agents: agents.value.map(({ id, name, role, instruction }) => ({
        id,
        name: name.trim(),
        role: role.trim(),
        instruction: instruction.trim(),
      })),
      max_speakers: maxSpeakers.value,
    })
    await applyConfig(data)
    notify('小组配置已保存')
    emit('saved', data)
    emit('close')
  } catch (error) {
    errorText.value = error.message
    notify(error.message, 'error')
  } finally {
    saving.value = false
  }
}

async function reset() {
  if (!window.confirm('恢复为默认的三位同学（小问 / 小思 / 小理）？当前自定义配置会丢失。')) return
  resetting.value = true
  errorText.value = ''
  try {
    const data = await api.lessons.resetGroupAgents()
    await applyConfig(data)
    notify('已恢复默认小组')
    emit('saved', data)
  } catch (error) {
    errorText.value = error.message
    notify(error.message, 'error')
  } finally {
    resetting.value = false
  }
}

function close() {
  emit('close')
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
    <div class="modal modal-wide modal-flex" role="dialog" aria-modal="true" aria-labelledby="group-settings-title">
      <div class="modal-head">
        <div>
          <h2 id="group-settings-title">小组设置</h2>
          <p>这些角色会进入多智能体编排：主持人按讨论内容选择发言人，而不是写死在前端。</p>
        </div>
        <button class="icon-btn" type="button" aria-label="关闭" @click="close">
          <Icon name="close" :size="17" />
        </button>
      </div>

      <div class="modal-body">
        <div v-if="loading" class="loading-stage" style="min-height: 160px">
          <div class="spinner" />
          <span class="small muted">正在读取小组配置…</span>
        </div>

        <template v-else>
          <div v-for="(agent, index) in agents" :key="agent.id" class="agent-row">
            <div class="agent-row-head">
              <span class="avatar">{{ (agent.name || '?').slice(-1) }}</span>
              <span class="small muted">角色 {{ index + 1 }}</span>
              <span class="spacer" />
              <button
                class="btn btn-sm btn-ghost"
                type="button"
                :disabled="!canRemove"
                @click="removeAgent(index)"
              >
                移除
              </button>
            </div>
            <div class="agent-fields">
              <div class="field">
                <label :for="`agent-name-${index}`">名字</label>
                <input
                  :id="`agent-name-${index}`"
                  v-model="agent.name"
                  class="input"
                  maxlength="20"
                  placeholder="例：小问"
                />
              </div>
              <div class="field">
                <label :for="`agent-role-${index}`">分工</label>
                <input
                  :id="`agent-role-${index}`"
                  v-model="agent.role"
                  class="input"
                  maxlength="20"
                  placeholder="例：追问者"
                />
              </div>
            </div>
            <div class="field">
              <label :for="`agent-instruction-${index}`">角色提示词</label>
              <textarea
                :id="`agent-instruction-${index}`"
                v-model="agent.instruction"
                class="textarea"
                rows="2"
                maxlength="400"
                placeholder="这个同学负责什么、发言时要注意什么"
              />
            </div>
          </div>

          <button class="btn btn-sm" type="button" :disabled="!canAdd" @click="addAgent">
            <Icon name="plus" :size="13" />
            添加同学
          </button>

          <div class="field">
            <label for="group-max-speakers">每轮发言人数</label>
            <select id="group-max-speakers" v-model.number="maxSpeakers" class="select">
              <option :value="2">2 位</option>
              <option :value="3">3 位</option>
            </select>
          </div>

          <div class="hint-box">
            保存后写入本机 <code>data/agents.json</code>，下一轮讨论立即生效。没有配置 API Key 时，演示模式会按这些角色轮换发言。
          </div>
          <div v-if="errorText" class="msg-error">{{ errorText }}</div>
        </template>
      </div>

      <div class="modal-foot">
        <button
          class="btn btn-sm btn-danger"
          type="button"
          :disabled="loading || saving || resetting"
          @click="reset"
        >
          {{ resetting ? '恢复中…' : '恢复默认' }}
        </button>
        <span class="spacer" />
        <button class="btn" type="button" @click="close">取消</button>
        <button class="btn btn-primary" type="button" :disabled="loading || saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
