<template>
  <section class="page" data-module="dedup">
    <header class="page-head">
      <div>
        <h2>重复去重管理</h2>
        <p class="page-desc">配置采集数据的去重算法、对比窗口和保留策略；阈值调整后可按新口径重算历史记录。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记去重策略</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出重复去重清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" :data-testid="`recompute-${row.id}`" @click="openRecompute(row)">
              阈值重算
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无重复去重数据，可先登记去重策略</td>
        </tr>
      </tbody>
    </table>

    <!-- 阈值重算工作区：调整阈值并按范围重新判定，生成去重策略数据报告 -->
    <section v-if="recomputeVisible" class="recompute-panel" data-testid="recompute-panel">
      <header class="panel-head">
        <h3>阈值重算 · {{ recomputeForm.策略编号 }}</h3>
        <button class="btn ghost" type="button" data-testid="close-recompute" @click="recomputeVisible = false">关闭</button>
      </header>
      <form class="analysis-form" @submit.prevent="submitRecompute">
        <label>旧阈值<input v-model.number="recomputeForm.旧阈值" data-testid="recompute-old" type="number" step="0.01" readonly /></label>
        <label>新阈值<input v-model.number="recomputeForm.新阈值" data-testid="recompute-new" type="number" step="0.01" min="0.5" max="1" required /></label>
        <label>阈值下界<input v-model.number="recomputeForm.阈值下界" data-testid="recompute-lower" type="number" step="0.01" /></label>
        <label>阈值上界<input v-model.number="recomputeForm.阈值上界" data-testid="recompute-upper" type="number" step="0.01" /></label>
        <label>重新判定范围
          <select v-model="recomputeForm.范围模式" data-testid="recompute-scope-mode">
            <option value="all">全量历史批次</option>
            <option value="partial">指定采集批次</option>
          </select>
        </label>
        <label v-if="recomputeForm.范围模式 === 'partial'">范围批次（逗号分隔）
          <input v-model="recomputeForm.范围批次文本" data-testid="recompute-batches" placeholder="BATCH-A,BATCH-B" />
        </label>
        <button class="btn primary" type="submit" data-testid="submit-recompute" :disabled="recomputing">
          {{ recomputing ? '重算中…' : '按新阈值重新判定' }}
        </button>
      </form>
      <p class="panel-hint">规则 = 判定口径（{{ recomputeForm.去重算法 }}/{{ recomputeForm.业务键列 }}）+ 阈值上限；已归档批次只读，重算只生成新去重版本。</p>
    </section>

    <!-- 去重策略数据报告：对照阈值调整前后的保留记录与重复证据 -->
    <section v-if="activeReport" class="report-panel" data-testid="report-panel">
      <header class="panel-head">
        <h3>去重策略数据报告 {{ activeReport.报告编号 }} · 版本 {{ activeReport.策略版本 }}</h3>
        <div class="page-actions">
          <button class="btn" type="button" data-testid="confirm-report" :disabled="activeReport.报告状态 === '已确认'" @click="confirmReport">
            确认报告版本
          </button>
          <button class="btn" type="button" data-testid="write-landing" @click="writeLanding">生成去重落地清单</button>
        </div>
      </header>
      <p v-if="landingMessage" class="panel-hint" data-testid="landing-message" style="color:#047857">{{ landingMessage }}</p>

      <div class="analysis-summary">
        <article class="analysis-card"><span class="stat-label">旧阈值 → 新阈值</span><strong>{{ activeReport.旧阈值 }} → {{ activeReport.新阈值 }}</strong></article>
        <article class="analysis-card"><span class="stat-label">重新判定范围</span><strong>{{ activeReport.重新判定范围 }}</strong></article>
        <article class="analysis-card"><span class="stat-label">覆盖 / 范围外</span><strong>{{ activeReport.覆盖记录数 }} / {{ activeReport.范围外记录数 }}</strong></article>
        <article class="analysis-card"><span class="stat-label">保留 / 重复</span><strong>{{ activeReport.保留记录数 }} / {{ activeReport.重复记录数 }}</strong></article>
        <article class="analysis-card"><span class="stat-label">口径冲突</span><strong :class="{ 'trend-down': activeReport.口径冲突数 > 0 }">{{ activeReport.口径冲突数 }}</strong></article>
        <article class="analysis-card"><span class="stat-label">报告状态</span><strong>{{ activeReport.报告状态 }}</strong></article>
      </div>

      <h4>阈值调整前后保留记录对照</h4>
      <table class="data-table" data-testid="keeper-compare">
        <thead><tr><th>口径</th><th>阈值</th><th>保留记录</th><th>重复记录数</th></tr></thead>
        <tbody>
          <tr data-testid="old-caliber-row">
            <td>旧口径</td><td>{{ activeReport.旧口径结果.阈值 }}</td>
            <td>{{ activeReport.旧口径结果.保留记录.join('、') }}</td>
            <td>{{ activeReport.旧口径结果.重复证据.length }}</td>
          </tr>
          <tr data-testid="new-caliber-row">
            <td>新口径</td><td>{{ activeReport.新口径结果.阈值 }}</td>
            <td>{{ activeReport.新口径结果.保留记录.join('、') }}</td>
            <td>{{ activeReport.新口径结果.重复证据.length }}</td>
          </tr>
        </tbody>
      </table>

      <h4>重复证据（新口径）</h4>
      <table class="data-table" data-testid="evidence-table">
        <thead><tr><th>记录编号</th><th>业务键</th><th>重复对象</th><th>相似度</th><th>命中阈值</th><th>阈值区间</th><th>判定口径</th></tr></thead>
        <tbody>
          <tr v-for="evidence in activeReport.新口径结果.重复证据" :key="evidence.记录编号" :data-testid="`evidence-${evidence.记录编号}`">
            <td>{{ evidence.记录编号 }}</td>
            <td>{{ evidence.业务键 }}</td>
            <td>{{ evidence.重复对象 }}</td>
            <td>{{ evidence.相似度 }}</td>
            <td>{{ evidence.命中阈值 }}</td>
            <td>{{ evidence.阈值区间.join(' ~ ') }}</td>
            <td>{{ evidence.判定口径 }}</td>
          </tr>
        </tbody>
      </table>

      <h4 v-if="activeReport.口径冲突明细.length">口径冲突明细（下游只认当前版本）</h4>
      <table v-if="activeReport.口径冲突明细.length" class="data-table" data-testid="conflict-table">
        <thead><tr><th>业务键</th><th>旧阈值保留记录</th><th>新阈值保留记录</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="conflict in activeReport.口径冲突明细" :key="conflict.业务键">
            <td>{{ conflict.业务键 }}</td>
            <td>{{ conflict.旧阈值保留记录.join('、') }}</td>
            <td>{{ conflict.新阈值保留记录.join('、') }}</td>
            <td>{{ conflict.冲突说明 }}</td>
          </tr>
        </tbody>
      </table>

      <h4 v-if="activeReport.范围外记录.length">重算覆盖范围外记录（不标记新口径）</h4>
      <table v-if="activeReport.范围外记录.length" class="data-table" data-testid="out-of-scope-table">
        <thead><tr><th>记录编号</th><th>业务键</th><th>采集批次</th></tr></thead>
        <tbody>
          <tr v-for="item in activeReport.范围外记录" :key="item.记录编号">
            <td>{{ item.记录编号 }}</td><td>{{ item.业务键 }}</td><td>{{ item.采集批次 }}</td>
          </tr>
        </tbody>
      </table>

      <h4>数据来源调用链</h4>
      <ol class="trace-chain" data-testid="trace-chain">
        <li v-for="node in traceChain" :key="node.层级">
          <strong>{{ node.层级 }}</strong>：{{ node.对象 }} — {{ node.说明 }}
        </li>
      </ol>
    </section>

    <!-- 去重版本：冻结版/最新版取舍，查看重算覆盖范围与当前版本 -->
    <section v-if="versions.length" class="version-panel" data-testid="version-panel">
      <header class="panel-head"><h3>去重版本（同一策略仅一个当前版本）</h3></header>
      <table class="data-table">
        <thead><tr><th>策略版本</th><th>版本类型</th><th>相似阈值</th><th>重新判定范围</th><th>口径冲突</th><th>当前版本</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="version in versions" :key="version.策略版本" :data-testid="`version-${version.策略版本}`" :data-current="version.是否当前 ? 'true' : 'false'">
            <td>{{ version.策略版本 }}</td>
            <td>{{ version.版本类型 }}</td>
            <td>{{ version.相似阈值 }}</td>
            <td>{{ version.重新判定范围 }}<template v-if="version.范围批次.length">（{{ version.范围批次.join('、') }}）</template></td>
            <td>{{ version.口径冲突数 }}</td>
            <td>{{ version.是否当前 ? '当前' : '—' }}</td>
            <td>
              <button class="link" type="button" :disabled="version.是否当前" data-testid="set-current" @click="setCurrent(version.策略版本)">
                设为当前
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记去重策略</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条重复去重记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Evidence = {
  记录编号: string
  业务键: string
  重复对象: string
  相似度: number
  命中阈值: number
  阈值区间: number[]
  判定口径: string
}
type Report = {
  报告编号: string
  策略编号: string
  策略版本: string
  去重算法: string
  业务键列: string
  旧阈值: number
  新阈值: number
  阈值下界: number
  阈值上界: number
  重新判定范围: string
  覆盖记录数: number
  范围外记录数: number
  保留记录数: number
  重复记录数: number
  口径冲突数: number
  报告状态: string
  旧口径结果: { 阈值: number; 保留记录: string[]; 重复证据: Evidence[] }
  新口径结果: { 阈值: number; 保留记录: string[]; 重复证据: Evidence[] }
  口径冲突明细: { 业务键: string; 旧阈值保留记录: string[]; 新阈值保留记录: string[]; 冲突说明: string }[]
  范围外记录: { 记录编号: string; 业务键: string; 采集批次: string }[]
}
type Version = {
  策略版本: string
  版本类型: string
  相似阈值: number
  重新判定范围: string
  范围批次: string[]
  口径冲突数: number
  是否当前: boolean
}

const ENDPOINT = '/api/dedup'
const columns = ["策略编号", "业务键列", "去重算法", "对比窗口", "相似阈值", "保留顺序", "增量模式", "生效批次"]
const actions = ["提交校验", "启用配置", "停用配置"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const metricNames = ["去重策略总数", "待校验去重策略", "已启用去重策略"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const recomputeVisible = ref(false)
const recomputing = ref(false)
const recomputeForm = ref({
  策略编号: '',
  去重算法: '文本相似度',
  业务键列: '业务键',
  旧阈值: 0.8,
  新阈值: 0.7,
  阈值下界: 0.5,
  阈值上界: 1,
  范围模式: 'all',
  范围批次文本: 'BATCH-A,BATCH-B',
})
const activeReport = ref<Report | null>(null)
const versions = ref<Version[]>([])
const traceChain = ref<{ 层级: string; 对象: string; 说明: string }[]>([])
const landingMessage = ref('')

const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'dedup.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('重复去重动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重复去重操作失败'
  }
}

function openRecompute(row: Row) {
  errorMessage.value = ''
  recomputeForm.value = {
    策略编号: String(row['策略编号']),
    去重算法: String(row['去重算法'] ?? '文本相似度'),
    业务键列: String(row['业务键列'] ?? '业务键'),
    旧阈值: Number(row['相似阈值']) || 0.8,
    新阈值: Number(row['相似阈值']) || 0.7,
    阈值下界: 0.5,
    阈值上界: 1,
    范围模式: 'all',
    范围批次文本: 'BATCH-A,BATCH-B',
  }
  activeReport.value = null
  landingMessage.value = ''
  recomputeVisible.value = true
  void loadVersions(String(row['策略编号']))
}

async function submitRecompute() {
  recomputing.value = true
  errorMessage.value = ''
  const form = recomputeForm.value
  const payload: Record<string, unknown> = {
    新阈值: form.新阈值,
    旧阈值: form.旧阈值,
    阈值下界: form.阈值下界,
    阈值上界: form.阈值上界,
    幂等键: `UI-${form.策略编号}-${form.新阈值}-${Date.now()}`,
  }
  if (form.范围模式 === 'partial') {
    payload.重新判定范围 = '指定采集批次'
    payload.范围批次 = form.范围批次文本.split(',').map((item) => item.trim()).filter(Boolean)
  }
  try {
    const response = await request(`${ENDPOINT}/recompute?strategy_code=${encodeURIComponent(form.策略编号)}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.detail || data.message || '重算失败')
    landingMessage.value = ''
    activeReport.value = data.entry as Report
    await loadVersions(form.策略编号)
    await loadTrace(form.策略编号, (activeReport.value as Report).报告编号)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阈值重算失败'
  } finally {
    recomputing.value = false
  }
}

async function confirmReport() {
  if (!activeReport.value) return
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/reports/${activeReport.value.报告编号}/confirm`, { method: 'POST' })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '报告确认失败')
    activeReport.value = data.entry as Report
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告确认失败'
  }
}

async function writeLanding() {
  if (!activeReport.value) return
  errorMessage.value = ''
  const report = activeReport.value
  try {
    const response = await request(`${ENDPOINT}/landing`, {
      method: 'POST',
      body: JSON.stringify({
        报告编号: report.报告编号,
        存储配置编号: 'STOR-0003',
        策略版本: report.策略版本,
      }),
    })
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.detail || data.message || '落地失败')
    landingMessage.value = data.message
  } catch (error) {
    landingMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '去重落地失败'
  }
}

async function loadVersions(strategyCode: string) {
  try {
    const response = await request(`${ENDPOINT}/versions?strategy_code=${encodeURIComponent(strategyCode)}`)
    if (!response.ok) return
    const data = await response.json()
    versions.value = (data.items ?? []) as Version[]
  } catch {
    versions.value = []
  }
}

async function setCurrent(versionCode: string) {
  if (!recomputeForm.value.策略编号) return
  errorMessage.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/versions/current?strategy_code=${encodeURIComponent(recomputeForm.value.策略编号)}`,
      { method: 'POST', body: JSON.stringify({ 策略版本: versionCode }) },
    )
    const data = await response.json()
    if (!response.ok || !data.ok) throw new Error(data.message || '版本切换失败')
    await loadVersions(recomputeForm.value.策略编号)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本切换失败'
  }
}

async function loadTrace(strategyCode: string, reportCode: string) {
  try {
    const response = await request(
      `${ENDPOINT}/trace-source?strategy_code=${encodeURIComponent(strategyCode)}&report_code=${encodeURIComponent(reportCode)}`,
    )
    if (!response.ok) return
    const data = await response.json()
    traceChain.value = data.链路明细 ?? []
  } catch {
    traceChain.value = []
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('去重策略列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重复去重列表读取失败'
  }
}

onMounted(reload)
</script>
