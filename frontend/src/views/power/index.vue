<template>
  <section class="page" data-module="power">
    <header class="page-head">
      <div>
        <h2>动力配套管理</h2>
        <p class="page-desc">状态按「正常运行 → 降额运行 → 故障停机 → 已报废」单向流转；报废设备不能再排检修，补完检修流程后才能复用。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电源设备</button>
        <button class="btn" type="button" @click="exportRows">导出动力配套清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>设备编号</span>
        <input v-model="keyword" placeholder="按设备编号检索" />
      </label>
      <label class="filter-item">
        <span>设备状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-if="String(row.status) !== '已报废'"
              class="link"
              type="button"
              @click="openPlan(row)"
            >
              排检修
            </button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="action === '完成检修' ? openComplete(row) : runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无动力配套数据，可先登记电源设备</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条动力配套记录</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button class="btn" type="button" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</button>
        <select v-model.number="size" @change="goPage(1)">
          <option :value="10">10 条/页</option>
          <option :value="20">20 条/页</option>
          <option :value="50">50 条/页</option>
        </select>
      </div>
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="editing" class="dialog-mask" @click.self="editing = null">
      <div class="dialog">
        <h3>
          {{ editMode === 'complete' ? '完成检修（补完检修流程）' : '排检修' }} — {{ editing['设备编号'] }}
        </h3>
        <p v-if="editMode === 'complete'" class="dialog-tip">
          报废设备补完检修流程后恢复正常运行；检修日期不能为空，缺哪项会拦下提示。
        </p>
        <label v-for="field in maintenanceFields" :key="field" class="dialog-field">
          <span>{{ field }}</span>
          <input v-model="editForm[field]" type="date" />
        </label>
        <p v-if="errorMessage" class="error-text dialog-error">{{ errorMessage }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="button" @click="saveMaintenance">保存</button>
          <button class="btn ghost" type="button" @click="editing = null">取消</button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="dialog-mask" @click.self="detail = null">
      <div class="dialog">
        <h3>电源设备详情 — {{ detail['设备编号'] }}</h3>
        <dl class="detail-list">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </template>
        </dl>
        <div class="dialog-actions">
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/power'
const columns = ["设备编号", "设备类型", "额定功率", "所属站点", "投用日期", "上次检修", "下次检修日", "设备状态"]
const statuses = ["正常运行", "降额运行", "故障停机", "已报废"]
const maintenanceFields = ["上次检修", "下次检修日"]
const NEXT_ACTIONS: Record<string, string[]> = {
  正常运行: ["降额运行", "故障停机", "申请报废"],
  降额运行: ["故障停机", "申请报废"],
  故障停机: ["申请报废"],
  已报废: ["完成检修"],
}
const STORAGE_KEY = 'power-view-state'
const stats = [{"label": "正常设备", "value": 0}, {"label": "降额设备", "value": 0}, {"label": "故障设备", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const keyword = ref('')
const statusFilter = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')

const editing = ref<Row | null>(null)
const editMode = ref<'plan' | 'complete'>('plan')
const editForm = ref<Record<string, string>>({ 上次检修: '', 下次检修日: '' })
const detail = ref<Row | null>(null)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function availableActions(row: Row): string[] {
  return NEXT_ACTIONS[String(row.status ?? '')] ?? []
}

function saveState() {
  const state = { page: page.value, size: size.value, keyword: keyword.value, status: statusFilter.value }
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

function restoreState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const state = JSON.parse(raw) as Partial<{ page: number; size: number; keyword: string; status: string }>
    page.value = Math.max(1, Number(state.page) || 1)
    size.value = [10, 20, 50].includes(Number(state.size)) ? Number(state.size) : 20
    keyword.value = String(state.keyword ?? '')
    statusFilter.value = statuses.includes(String(state.status)) ? String(state.status) : ''
  } catch {
    // 状态损坏时按默认首页加载
  }
}

watch([page, size, keyword, statusFilter], saveState)

async function fetchList(): Promise<{ items: Row[]; total: number }> {
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  query.set('page', String(page.value))
  query.set('size', String(size.value))
  let lastError: unknown = null
  // 拉不到时再取一次，别停在半截
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await request(`${ENDPOINT}?${query.toString()}`)
      if (!response.ok) {
        throw new Error(`接口返回 ${response.status}`)
      }
      return (await response.json()) as { items: Row[]; total: number }
    } catch (error) {
      lastError = error
      if (attempt === 0) {
        await new Promise((resolve) => setTimeout(resolve, 400))
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error('检修计划读取失败')
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchList()
    rows.value = payload.items ?? []
    total.value = Number(payload.total ?? rows.value.length)
  } catch (error) {
    // 失败时保留当前列表，不清空已展示的检修计划
    errorMessage.value = error instanceof Error ? error.message : '检修计划读取失败'
  }
}

function applyFilters() {
  page.value = 1
  void reload()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  page.value = 1
  void reload()
}

function goPage(target: number) {
  page.value = Math.min(Math.max(1, target), pageCount.value)
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '电源设备登记入口尚未接入审批流'
}

async function parseResult(response: Response): Promise<{ ok: boolean; message: string }> {
  const payload = (await response.json()) as { ok?: boolean; message?: string; detail?: string }
  return {
    ok: response.ok && payload.ok !== false,
    message: payload.message ?? payload.detail ?? '',
  }
}

async function runAction(action: string, row: Row, values?: Record<string, string>) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...(values ?? {}) } }),
    })
    const result = await parseResult(response)
    if (!result.ok) {
      throw new Error(result.message || '动力配套动作未生效')
    }
    noticeMessage.value = result.message || '操作成功'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '动力配套操作失败'
  }
}

function openPlan(row: Row) {
  editMode.value = 'plan'
  editing.value = row
  editForm.value = {
    上次检修: String(row['上次检修'] ?? ''),
    下次检修日: String(row['下次检修日'] ?? ''),
  }
}

function openComplete(row: Row) {
  editMode.value = 'complete'
  editing.value = row
  editForm.value = { 上次检修: '', 下次检修日: '' }
}

async function saveMaintenance() {
  const row = editing.value
  if (!row) return
  const missing = maintenanceFields.filter((field) => !editForm.value[field]?.trim())
  if (missing.length) {
    errorMessage.value = `检修日期未填全，缺少：${missing.join('、')}`
    return
  }
  errorMessage.value = ''
  noticeMessage.value = ''
  if (editMode.value === 'complete') {
    await runAction('完成检修', row, { ...editForm.value })
    if (!errorMessage.value) editing.value = null
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: { ...editForm.value } }),
    })
    const result = await parseResult(response)
    if (!result.ok) {
      throw new Error(result.message || '检修日期保存失败')
    }
    noticeMessage.value = result.message || '检修日期已保存'
    editing.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修日期保存失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      const payload = (await response.json()) as { detail?: string }
      throw new Error(payload.detail ?? '设备详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '设备详情读取失败'
  }
}

onMounted(() => {
  restoreState()
  void reload()
})
</script>
