<template>
  <section v-if="execution" class="execution-monitor">
    <div class="monitor-heading">
      <strong>执行 #{{ execution.id }} · {{ statusText }}</strong>
      <el-tag size="small" :type="connected ? 'success' : 'info'">
        {{ connected ? '实时连接' : '轮询同步' }}
      </el-tag>
      <el-button v-if="!finished" type="danger" size="small" :loading="cancelling" @click="cancel">
        取消执行
      </el-button>
    </div>
    <el-progress :percentage="execution.progress || 0" :status="progressStatus" />
    <p v-if="execution.error_message" class="execution-error">{{ execution.error_message }}</p>
    <p v-if="syncError" role="alert">状态同步失败，正在重试。{{ syncError }}</p>
    <h4>执行日志</h4>
    <el-table :data="logs" height="240" empty-text="等待执行日志">
      <el-table-column prop="sequence" label="序号" width="70" />
      <el-table-column prop="level" label="级别" width="90" />
      <el-table-column prop="message" label="日志内容" min-width="280" />
    </el-table>
    <small>显示最近 500 条日志；完整记录保存在服务端。</small>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'

const props = defineProps({ executionId: { type: Number, required: true } })
const emit = defineEmits(['updated'])
const execution = ref(null)
const logs = ref([])
const connected = ref(false)
const cancelling = ref(false)
const syncError = ref('')
const terminal = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const finished = computed(() => terminal.has(execution.value?.status))
const statusText = computed(() => ({
  PENDING: '待执行', QUEUED: '排队中', RUNNING: '执行中',
  COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消'
}[execution.value?.status] || execution.value?.status))
const progressStatus = computed(() => execution.value?.status === 'FAILED' ? 'exception'
  : execution.value?.status === 'COMPLETED' ? 'success' : undefined)
let generation = 0
let timer = null
let socket = null
let after = 0

function mergeLogs(entries) {
  const merged = new Map(logs.value.map(entry => [entry.sequence, entry]))
  for (const entry of entries) merged.set(entry.sequence, entry)
  logs.value = [...merged.values()].sort((a, b) => a.sequence - b.sequence).slice(-500)
}

function stop() {
  generation += 1
  clearTimeout(timer)
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
  connected.value = false
}

async function poll(id, token) {
  let more = false
  try {
    const [detail, history] = await Promise.all([
      api.get(`/api-testing/test-executions/${id}/`),
      api.get(`/api-testing/test-executions/${id}/logs/`, { params: { after, limit: 200 } })
    ])
    if (token !== generation) return
    execution.value = detail.data
    mergeLogs(history.data.logs)
    after = history.data.next_after
    more = history.data.logs.length === 200
    syncError.value = ''
    emit('updated', detail.data)
  } catch (error) {
    if (token !== generation) return
    syncError.value = error.message
  }
  if (token !== generation) return
  // Polling is retained with WS so reconnects and out-of-order events cannot lose logs.
  const cancellationSettling = execution.value?.status === 'CANCELLED'
    && logs.value.some(entry => entry.event === 'REQUEST_STARTED' || entry.data?.status === 'RUNNING')
    && !logs.value.some(entry => entry.event === 'EXECUTION_CANCELLED' || entry.event === 'TASK_ERROR')
  if (!finished.value || cancellationSettling || more || syncError.value) timer = setTimeout(() => poll(id, token), more ? 100 : 1200)
  else if (socket) socket.close()
}

async function connect(id, token) {
  try {
    const { data } = await api.post(`/api-testing/test-executions/${id}/realtime-ticket/`)
    if (token !== generation || finished.value) return
    const url = new URL(data.websocket_path, window.location.href)
    url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(url.toString())
    socket.onopen = () => { if (token === generation) connected.value = true }
    socket.onclose = () => { if (token === generation) connected.value = false }
    socket.onerror = () => { if (token === generation) connected.value = false }
    socket.onmessage = event => {
      if (token !== generation) return
      try {
        const payload = JSON.parse(event.data)
        if (payload.type === 'execution_snapshot') mergeLogs(payload.logs || [])
        if (payload.type === 'execution_event') mergeLogs([payload])
      } catch { connected.value = false }
    }
  } catch { /* The durable polling channel remains available. */ }
}

async function cancel() {
  const id = props.executionId
  const token = generation
  cancelling.value = true
  try {
    const { data } = await api.post(`/api-testing/test-executions/${id}/cancel/`)
    if (token !== generation) return
    execution.value = data
    emit('updated', data)
    ElMessage.success('已取消执行，当前请求结束后停止后续步骤')
  } catch { ElMessage.error('取消失败，请刷新执行状态') }
  finally { cancelling.value = false }
}

watch(() => props.executionId, id => {
  stop()
  execution.value = null
  logs.value = []
  after = 0
  syncError.value = ''
  const token = generation
  void poll(id, token)
  void connect(id, token)
}, { immediate: true })
onBeforeUnmount(stop)
</script>

<style scoped>
.execution-monitor { margin-bottom: 24px; }
.monitor-heading { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
.execution-error { color: #f56c6c; }
small { color: #909399; }
</style>
