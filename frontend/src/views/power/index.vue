<template>
  <section class="page" data-module="power">
    <header class="page-head">
      <div>
        <h2>动力配套管理</h2>
        <p class="page-desc">围绕电源设备做登记、筛选、状态流转与检修安排；状态只能顺次推进，报废设备须补完检修流程后复用。</p>
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

    <form class="filter-bar" @submit.prevent="onSearch">
      <label class="filter-item">
        <span>设备编号</span>
        <input v-model="keyword" placeholder="按设备编号检索" />
      </label>
      <label class="filter-item">
        <span>设备状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
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
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">检修安排</button>
            <button
              v-if="nextAction(row)"
              class="link"
              type="button"
              @click="runStatusAction(nextAction(row) as string, row)"
            >
              {{ nextAction(row) }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无动力配套数据，可先登记电源设备</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
        <span>共 {{ total }} 条动力配套记录</span>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>设备详情 · {{ detail?.['设备编号'] }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>

        <div v-if="detailLoading" class="modal-body">
          <p class="hint-text">检修计划读取失败，正在自动再取一次……</p>
        </div>
        <div v-else-if="detail" class="modal-body">
          <dl class="detail-grid">
            <template v-for="column in columns" :key="column">
              <dt>{{ column }}</dt>
              <dd>{{ displayCell(detail, column) }}</dd>
            </template>
          </dl>

          <div class="maint-edit">
            <label class="filter-item">
              <span>下次检修日（必填，保存后立即生效）</span>
              <input v-model="maintDate" type="date" />
            </label>
            <div class="maint-buttons">
              <button
                v-if="detail['检修状态'] === '待检修'"
                class="btn"
                type="button"
                :disabled="maintBusy"
                @click="saveMaintDate"
              >
                保存下次检修日
              </button>
              <button
                v-else-if="detail.status !== '已报废'"
                class="btn primary"
                type="button"
                :disabled="maintBusy"
                @click="scheduleMaintenance"
              >
                排检修
              </button>
              <button
                v-if="detail['检修状态'] === '待检修'"
                class="btn primary"
                type="button"
                :disabled="maintBusy"
                @click="completeMaintenance"
              >
                完成检修（补完流程后复用）
              </button>
            </div>
            <p v-if="detail.status === '已报废' && detail['检修状态'] !== '待检修'" class="hint-text">
              设备已报废，不能再排检修；如需复用，请先补完既有检修流程。
            </p>
          </div>
        </div>
        <div v-else class="modal-body">
          <p class="error-text">{{ detailError || '检修计划未拉到，稍后可重新打开' }}</p>
          <button class="btn" type="button" @click="reopenDetail()">重新拉取</button>
        </div>

        <p v-if="detailMessage" class="modal-message">{{ detailMessage }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/power'
const PAGE_SIZE = 10
const columns = [
  '设备编号', '设备类型', '额定功率', '所属站点', '投用日期',
  '上次检修', '下次检修日', '检修状态', '设备状态',
]
const statuses = ['正常运行', '降额运行', '故障停机', '已报废']
// 每个状态在次序上唯一允许顺次推进的下一步动作
const NEXT_ACTIONS: Record<string, string> = {
  正常运行: '降额运行',
  降额运行: '故障停机',
  故障停机: '申请报废',
}
const STORAGE_KEY = 'power-list-state'

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const statusFilter = ref('')
const errorMessage = ref('')
const stats = ref([
  { label: '正常设备', value: 0 },
  { label: '降额设备', value: 0 },
  { label: '故障设备', value: 0 },
])

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Row | null>(null)
const detailId = ref<number | null>(null)
const detailError = ref('')
const detailMessage = ref('')
const maintDate = ref('')
const maintBusy = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function displayCell(row: Row, column: string): string | number {
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function nextAction(row: Row): string | undefined {
  return NEXT_ACTIONS[String(row.status)]
}

function persistState() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    page: page.value,
    keyword: keyword.value,
    status: statusFilter.value,
  }))
}

function restoreState() {
  const raw = sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw) as { page?: number; keyword?: string; status?: string }
    page.value = Number(saved.page) > 0 ? Number(saved.page) : 1
    keyword.value = saved.keyword ?? ''
    statusFilter.value = saved.status ?? ''
  } catch {
    // 记忆内容损坏时按首屏处理，不影响列表加载
  }
}

function buildQuery(targetPage: number): string {
  const params = new URLSearchParams({
    page: String(targetPage),
    size: String(PAGE_SIZE),
  })
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  return params.toString()
}

async function fetchJsonWithRetry(path: string): Promise<Response> {
  // 检修计划/列表拉不到时先自动再取一次，避免页面停在半截
  try {
    const response = await request(path)
    if (response.ok) return response
    // 4xx（如 404）重试无意义，只对服务端错误再取一次
    if (response.status >= 500) return request(path)
    return response
  } catch {
    return request(path)
  }
}

async function reload() {
  errorMessage.value = ''
  persistState()
  try {
    const response = await fetchJsonWithRetry(`${ENDPOINT}?${buildQuery(page.value)}`)
    if (!response.ok) {
      throw new Error('电源设备列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (page.value > totalPages.value) {
      page.value = totalPages.value
      await reload()
      return
    }
    await loadStats()
    syncOpenDetail()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '动力配套列表读取失败'
  }
}

async function loadStats() {
  try {
    const [normal, derated, faulty] = await Promise.all(
      statuses.slice(0, 3).map(async (status) => {
        const params = new URLSearchParams({ status, page: '1', size: '1' })
        const response = await fetchJsonWithRetry(`${ENDPOINT}?${params.toString()}`)
        if (!response.ok) return 0
        const payload = await response.json()
        return Number(payload.total) || 0
      }),
    )
    stats.value = [
      { label: '正常设备', value: normal },
      { label: '降额设备', value: derated },
      { label: '故障设备', value: faulty },
    ]
  } catch {
    // 统计卡片不阻塞主链路，保持上一次数值即可
  }
}

function onSearch() {
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
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '电源设备登记入口尚未接入审批流'
}

async function runStatusAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '动力配套动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '动力配套操作失败'
  }
}

async function openDetail(row: Row) {
  detailVisible.value = true
  detailId.value = Number(row.id)
  detail.value = row // 先用列表行兜底展示，再拉详情覆盖，保证两处口径统一以详情为准
  detailError.value = ''
  detailMessage.value = ''
  maintDate.value = String(row['下次检修日'] ?? '')
  await loadDetail()
}

function reopenDetail() {
  if (detailId.value !== null) void loadDetail()
}

async function loadDetail() {
  if (detailId.value === null) return
  detailLoading.value = true
  detailError.value = ''
  try {
    const response = await fetchJsonWithRetry(`${ENDPOINT}/${detailId.value}`)
    if (!response.ok) {
      throw new Error('检修计划拉取失败，请稍后重试')
    }
    const payload = await response.json() as Row
    detail.value = payload
    maintDate.value = String(payload['下次检修日'] ?? '')
  } catch (error) {
    detail.value = null
    detailError.value = error instanceof Error ? error.message : '检修计划拉取失败'
  } finally {
    detailLoading.value = false
  }
}

function syncOpenDetail() {
  // 列表刷新后（如翻页/操作后）同步弹窗里的同一条记录，保证列表详情不打架
  if (!detailVisible.value || detailId.value === null) return
  const latest = rows.value.find((item) => Number(item.id) === detailId.value)
  if (latest) {
    detail.value = latest
    if (!maintDate.value) maintDate.value = String(latest['下次检修日'] ?? '')
  }
}

function closeDetail() {
  detailVisible.value = false
  detail.value = null
  detailId.value = null
  detailError.value = ''
  detailMessage.value = ''
}

async function saveMaintDate() {
  detailMessage.value = ''
  if (!maintDate.value) {
    detailMessage.value = '下次检修日不能为空，请先选择检修日期'
    return
  }
  maintBusy.value = true
  try {
    const response = await request(`${ENDPOINT}/${detailId.value}`, {
      method: 'PATCH',
      body: JSON.stringify({ values: { 下次检修日: maintDate.value } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '下次检修日保存失败')
    }
    detail.value = payload.entry
    detailMessage.value = payload.message || '检修安排已保存'
    await reload()
  } catch (error) {
    detailMessage.value = error instanceof Error ? error.message : '下次检修日保存失败'
  } finally {
    maintBusy.value = false
  }
}

async function scheduleMaintenance() {
  detailMessage.value = ''
  if (!maintDate.value) {
    detailMessage.value = '下次检修日不能为空，请先选择检修日期'
    return
  }
  maintBusy.value = true
  try {
    const response = await request(`${ENDPOINT}/${detailId.value}/maintenance`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '安排检修', 下次检修日: maintDate.value } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '检修安排失败')
    }
    detail.value = payload.entry
    detailMessage.value = payload.message
    await reload()
  } catch (error) {
    detailMessage.value = error instanceof Error ? error.message : '检修安排失败'
  } finally {
    maintBusy.value = false
  }
}

async function completeMaintenance() {
  detailMessage.value = ''
  maintBusy.value = true
  try {
    const response = await request(`${ENDPOINT}/${detailId.value}/maintenance`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '完成检修' } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '检修完成操作失败')
    }
    detail.value = payload.entry
    maintDate.value = ''
    detailMessage.value = payload.message
    await reload()
  } catch (error) {
    detailMessage.value = error instanceof Error ? error.message : '检修完成操作失败'
  } finally {
    maintBusy.value = false
  }
}

onMounted(() => {
  restoreState()
  void reload()
})
</script>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pager .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 640px;
  max-height: 82vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.modal-head h3 {
  margin: 0;
  font-size: 16px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr 110px 1fr;
  gap: 6px 10px;
  margin: 0 0 14px;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
.maint-edit {
  border-top: 1px solid var(--border);
  padding-top: 12px;
}
.maint-buttons {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.hint-text {
  color: var(--muted);
  font-size: 12px;
  margin: 8px 0 0;
}
.modal-message {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--brand);
}
.filter-item select {
  padding: 4px 8px;
}
</style>
