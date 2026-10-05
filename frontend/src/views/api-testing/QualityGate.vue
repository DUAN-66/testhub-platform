<template>
  <div class="quality-page">
    <h2>契约回归与质量门禁</h2>
    <p>比较接口契约，保留登录等前置步骤执行受影响套件，再依据本次执行证据决定放行。</p>
    <el-alert title="支持 OpenAPI 3.0；无法证明兼容的语义变化需要人工审查。P95 为本次功能回归样本指标。" type="info" :closable="false" />
    <el-card>
      <el-form label-width="100px" :disabled="busy">
        <el-form-item label="项目">
          <el-select v-model="project" @change="changeProject" placeholder="选择项目">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="导入契约">
          <el-input v-model="name" placeholder="版本名称" class="version-name" />
          <el-input v-model="document" type="textarea" :rows="5" placeholder="粘贴 OpenAPI JSON 或 YAML" />
          <el-button :disabled="!project || !name || !document || busy" @click="importVersion">导入不可变版本</el-button>
        </el-form-item>
        <el-form-item label="版本比较">
          <el-select v-model="baseline" placeholder="基线版本" @change="resetEvidence">
            <el-option v-for="item in versions" :key="item.id" :label="item.name + ' · ' + item.digest.slice(0, 8)" :value="item.id" />
          </el-select>
          <span class="arrow">→</span>
          <el-select v-model="candidate" placeholder="候选版本" @change="resetEvidence">
            <el-option v-for="item in versions" :key="item.id" :label="item.name + ' · ' + item.digest.slice(0, 8)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="通过率下限">
          <el-input-number v-model="minPassRate" :min="0" :max="100" @change="resetEvidence" /> %
        </el-form-item>
        <el-form-item label="P95 上限">
          <el-input-number v-model="maxP95" :min="1" @change="resetEvidence" /> ms
        </el-form-item>
        <el-form-item label="并发性能门禁">
          <el-switch v-model="loadEnabled" @change="resetEvidence" />
          <span class="arrow">启用后必须取得本次并发执行证据，缺失或失败均阻断。</span>
        </el-form-item>
        <template v-if="loadEnabled">
          <el-form-item label="请求 / 环境">
            <el-select v-model="loadRequest" placeholder="受影响套件中的 GET/HEAD 请求" @change="resetEvidence">
              <el-option v-for="item in loadRequests" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
            <el-select v-model="loadEnvironment" placeholder="套件执行环境" clearable @change="resetEvidence">
              <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="负载配置">
            并发 <el-input-number v-model="loadUsers" :min="1" :max="8" @change="resetEvidence" />
            每用户请求 <el-input-number v-model="loadIterations" :min="1" :max="10" @change="resetEvidence" />
          </el-form-item>
          <el-form-item label="性能预算">
            P95(ms) <el-input-number v-model="loadP95" :min="1" @change="resetEvidence" />
            错误率(%) <el-input-number v-model="loadErrors" :min="0" :max="100" @change="resetEvidence" />
            成功RPS <el-input-number v-model="loadRps" :min="0" @change="resetEvidence" />
          </el-form-item>
          <el-form-item label="SQL查询预算">
            <el-switch v-model="sqlEnabled" @change="resetEvidence" />
            <el-input-number v-if="sqlEnabled" v-model="maxQueries" :min="0" @change="resetEvidence" />
            <span class="arrow">要求每个响应携带 X-Query-Count；演示项目预期为 1。</span>
          </el-form-item>
        </template>
      </el-form>
      <el-button :disabled="!baseline || !candidate || busy" @click="preview">分析变更</el-button>
      <el-button type="primary" :disabled="!baseline || !candidate || busy" :loading="busy" @click="execute">执行回归并评估</el-button>
      <el-button v-if="run && !report" :disabled="busy" @click="resume">查询本次结果</el-button>
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="result" />
    </el-card>
    <el-card v-if="plan" class="result">
      <h3>变更与影响范围</h3>
      <p>选择 {{ plan.impact.selected_suites }} / {{ plan.impact.total_suites }} 个套件；破坏性变更 {{ plan.diff.breaking_count }} 项；待审查 {{ plan.diff.review_count }} 项。</p>
      <el-alert v-if="plan.impact.uncovered_operations.length" :title="'缺少覆盖：' + plan.impact.uncovered_operations.join(', ')" type="error" :closable="false" />
      <el-alert v-if="plan.impact.uncertain_suite_ids.length" title="存在未解析的 URL 变量，已保守选取套件并阻断放行。" type="warning" :closable="false" />
      <el-table :data="plan.diff.changes" empty-text="无语义变更">
        <el-table-column prop="operation" label="接口" />
        <el-table-column prop="severity" label="风险" width="130" />
        <el-table-column prop="rule" label="变更规则" />
        <el-table-column prop="location" label="位置" />
      </el-table>
    </el-card>
    <el-card v-if="run" class="result">
      <p>本次运行：{{ run.id }} · {{ run.state }}；执行记录：{{ run.execution_ids.join(', ') || '无' }}</p>
    </el-card>
    <el-card v-if="report" class="result">
      <h3><el-tag :type="report.decision === 'PASS' ? 'success' : 'danger'">{{ report.decision === 'PASS' ? '允许放行' : '阻断放行' }}</el-tag></h3>
      <p>报告 {{ report.id }} · 通过率 {{ report.metrics.pass_rate ?? '无样本' }}% · P95 {{ report.metrics.p95_ms ?? '无样本' }} ms</p>
      <p v-if="report.performance?.summary">并发样本 {{ report.performance.summary.requests }} · P95 {{ report.performance.summary.p95_ms?.toFixed(2) }} ms · 成功RPS {{ report.performance.summary.successful_rps?.toFixed(2) }} · 错误率 {{ report.performance.summary.error_rate }}% · SQL {{ report.performance.summary.max_queries ?? '未提供' }}</p>
      <el-table :data="report.rules">
        <el-table-column prop="name" label="门禁规则" />
        <el-table-column label="结果" width="100"><template #default="scope">{{ scope.row.passed ? '通过' : '阻断' }}</template></el-table-column>
        <el-table-column label="实际值"><template #default="scope">{{ JSON.stringify(scope.row.actual) }}</template></el-table-column>
        <el-table-column label="要求"><template #default="scope">{{ JSON.stringify(scope.row.expected) }}</template></el-table-column>
      </el-table>
      <el-button @click="download">导出证据 JSON</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import api from '@/utils/api'

const projects = ref([]), versions = ref([]), project = ref(null)
const name = ref(''), document = ref(''), baseline = ref(null), candidate = ref(null)
const minPassRate = ref(100), maxP95 = ref(1000)
const loadEnabled = ref(false), loadRequests = ref([]), environments = ref([])
const loadRequest = ref(null), loadEnvironment = ref(null), loadUsers = ref(4), loadIterations = ref(10)
const loadP95 = ref(1000), loadErrors = ref(0), loadRps = ref(1), sqlEnabled = ref(false), maxQueries = ref(1)
let performanceId = null, performanceKey = null
const plan = ref(null), run = ref(null), report = ref(null), error = ref(''), busy = ref(false)
let generation = 0, disposed = false, idempotencyKey = null
const data = () => ({ baseline_id: baseline.value, candidate_id: candidate.value,
  policy: { min_pass_rate: minPassRate.value, max_p95_ms: maxP95.value,
    ...(loadEnabled.value ? { performance: { max_p95_ms: loadP95.value, max_error_rate: loadErrors.value,
      min_rps: loadRps.value, min_requests: loadUsers.value * loadIterations.value,
      ...(sqlEnabled.value ? { max_queries: maxQueries.value } : {}) } } : {}) } })
const unpack = response => response.data
const resetEvidence = () => { generation++; plan.value = null; run.value = null; report.value = null; error.value = ''; idempotencyKey = null; performanceId = null; performanceKey = null }
const loadVersions = async () => { versions.value = unpack(await api.get('/v1/contracts/', { params: { project: project.value } })) }
const changeProject = async () => {
  resetEvidence(); baseline.value = null; candidate.value = null
  loadRequest.value = null; loadEnvironment.value = null
  await guarded(async () => {
    await loadVersions()
    const responses = await Promise.all([
      api.get('/api-testing/requests/', { params: { project: project.value } }),
      api.get('/api-testing/environments/', { params: { project: project.value } })
    ])
    const requests = responses[0].data.results || responses[0].data
    loadRequests.value = requests.filter(item => ['GET', 'HEAD'].includes(item.method))
    environments.value = (responses[1].data.results || responses[1].data).filter(item => item.project === project.value || item.scope === 'GLOBAL')
  })
}
const guarded = async action => {
  busy.value = true; error.value = ''
  try { await action() } catch (exc) { error.value = JSON.stringify(exc.response?.data || '请求失败，请检查连接后重试') }
  finally { if (!disposed) busy.value = false }
}
const importVersion = () => guarded(async () => {
  await api.post('/v1/contracts/', { project: project.value, name: name.value, document: document.value })
  document.value = ''; await loadVersions()
})
const preview = () => guarded(async () => { plan.value = unpack(await api.post('/v1/quality/plan/', data())) })
const awaitEvidence = async token => {
  if (loadEnabled.value && !performanceId) {
    performanceKey ||= crypto.randomUUID()
    const measured = unpack(await api.post('/v1/performance/', { request_id: loadRequest.value,
      environment_id: loadEnvironment.value || null, gate_id: run.value.id,
      workload: { users: loadUsers.value, iterations: loadIterations.value, timeout_seconds: 3 } },
    { headers: { 'Idempotency-Key': performanceKey } }))
    performanceId = measured.id
  }
  const deadline = Date.now() + 90000
  while (!disposed && token === generation && Date.now() < deadline) {
    run.value = unpack(await api.get(`/v1/quality/${run.value.id}/run/`))
    if (run.value.state === 'ERROR') break
    if (run.value.state === 'READY') {
      const results = await Promise.all(run.value.execution_ids.map(id => api.get(`/api-testing/test-executions/${id}/`)))
      const functionalDone = results.every(r => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(r.data.status))
      const loadDone = !performanceId || ['COMPLETED', 'FAILED'].includes((await api.get(`/v1/performance/${performanceId}/`)).data.status)
      if (functionalDone && loadDone) break
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  if (disposed || token !== generation) return
  report.value = unpack(await api.post('/v1/quality/evaluate/', { run_id: run.value.id }))
}
const execute = () => guarded(async () => {
  report.value = null
  idempotencyKey ||= crypto.randomUUID()
  run.value = unpack(await api.post('/v1/quality/execute/', data(), { headers: { 'Idempotency-Key': idempotencyKey } }))
  plan.value = run.value
  await awaitEvidence(generation)
})
const resume = () => guarded(() => awaitEvidence(generation))
const download = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' }))
  const link = window.document.createElement('a'); link.href = url; link.download = `quality-gate-${report.value.id}.json`; link.click()
  URL.revokeObjectURL(url)
}
onMounted(() => guarded(async () => {
  const result = unpack(await api.get('/api-testing/projects/'))
  projects.value = result.results || result
}))
onBeforeUnmount(() => { disposed = true; generation++ })
</script>

<style scoped>
.quality-page { padding: 24px; max-width: 1300px; margin: auto; }
.el-card, .result { margin-top: 20px; }
.version-name { margin-bottom: 10px; }
.arrow { padding: 0 16px; }
</style>
