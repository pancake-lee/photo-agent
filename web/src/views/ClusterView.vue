<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import { formatDate } from '../utils/format'
import {
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NButton,
  NIcon,
  NTag,
  NEmpty,
  NSpin,
  NSpace,
  NDataTable,
  NPopconfirm,
  NModal,
  NInputNumber,
  NForm,
  NFormItem,
  NSelect,
  useMessage,
} from 'naive-ui'
import {
  TrashOutline,
  EyeOutline,
  GitNetworkOutline,
  PlayOutline,
  AppsOutline,
  CheckmarkCircleOutline,
} from '@vicons/ionicons5'
import { AGENT_BASE } from '../config'
import PhotoThumbList from '../components/PhotoThumbList.vue'
import PhotoPreviewModal from '../components/PhotoPreviewModal.vue'

// ── 类型定义 ──

interface ClusterPhoto {
  photo_id: string
  filename: string
  distance_to_centroid: number
}

interface ClusterItem {
  cluster_id: number
  label: string
  theme_description: string
  size: number
  coherence_score: number
  photos: ClusterPhoto[]
}

interface ClusterStats {
  total_photos: number
  clustered_photos: number
  noise_photos: number
  num_clusters: number
  duration_seconds: number
}

interface ClusterResultSummary {
  id: string
  created_at: string
  params: Record<string, any>
  stats: ClusterStats
  cluster_labels: { cluster_id: number; label: string; size: number }[]
}

interface ClusterResultDetail {
  id: string
  created_at: string
  params: Record<string, any>
  stats: ClusterStats
  clusters: ClusterItem[]
}

interface EvalRuleResult {
  rule_id: string
  severity: string
  passed: boolean
  value: string
  expected: string
  message: string
  cluster_id: number | null
}

interface EvalHeuristicSummary {
  total_checks: number
  passed: number
  failed: number
  failures: EvalRuleResult[]
}

interface EvalReport {
  report_id: string
  created_at: string
  result_id: string
  total_clusters: number
  heuristic: EvalHeuristicSummary
}

// ── 状态 ──

const message = useMessage()
const results = ref<ClusterResultSummary[]>([])
const loading = ref(false)
const running = ref(false)

// 参数面板
const showParamModal = ref(false)
const paramForm = ref({
  min_cluster_size: 5,
  min_samples: 3,
  umap_n_neighbors: 15,
  umap_min_dist: 0.1,
  umap_n_components: 5,
  umap_metric: 'cosine',
})

const umapMetricOptions = [
  { label: 'cosine', value: 'cosine' },
  { label: 'euclidean', value: 'euclidean' },
  { label: 'manhattan', value: 'manhattan' },
]

// 详情弹窗
const detailVisible = ref(false)
const detailItem = ref<ClusterResultDetail | null>(null)
const detailLoading = ref(false)

// 主题生成状态（track 正在生成的 cluster_id）
const generatingThemeId = ref<number | null>(null)

// 全部展开的簇 ID 集合
const expandedClusters = ref<Set<number>>(new Set())

// 评估状态
const evalRunning = ref(false)
const evalReport = ref<EvalReport | null>(null)
const showEvalResult = ref(false)

// 图片预览
const previewShow = ref(false)
const previewImg = ref('')

function openPreview(uuid: string) {
  previewImg.value = `/api/v1/photos/${uuid}/image`
  previewShow.value = true
}

// ── 数据加载 ──

async function fetchResults() {
  loading.value = true
  try {
    const resp = await fetch(`${AGENT_BASE}/cluster/results`)
    if (resp.ok) {
      results.value = await resp.json()
    }
  } catch (e) {
    console.warn('加载聚类结果失败', e)
    message.error('加载聚类结果失败')
  } finally {
    loading.value = false
  }
}

// ── 运行聚类 ──

async function handleRunCluster() {
  running.value = true
  showParamModal.value = false
  try {
    const resp = await fetch(`${AGENT_BASE}/cluster/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(paramForm.value),
    })
    if (resp.ok) {
      const result = await resp.json()
      message.success(
        `聚类完成：${result.stats.num_clusters} 个簇，${result.stats.clustered_photos} 张照片已聚类，耗时 ${result.stats.duration_seconds}s`
      )
      await fetchResults()
    } else {
      const err = await resp.json()
      message.error(err.detail || '聚类失败')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '聚类请求失败')
  } finally {
    running.value = false
  }
}

// ── 删除 ──

async function handleDelete(id: string) {
  try {
    const resp = await fetch(`${AGENT_BASE}/cluster/results/${id}`, {
      method: 'DELETE',
    })
    if (resp.ok) {
      results.value = results.value.filter((r) => r.id !== id)
      message.success('已删除')
    } else {
      const err = await resp.json()
      message.error(err.detail || '删除失败')
    }
  } catch (e) {
    console.warn('删除聚类结果失败', e)
    message.error('删除失败')
  }
}

// ── 生成主题（单簇） ──

async function handleGenerateTheme(resultId: string, clusterId: number) {
  generatingThemeId.value = clusterId
  try {
    const resp = await fetch(
      `${AGENT_BASE}/cluster/results/${resultId}/clusters/${clusterId}/generate-theme`,
      { method: 'POST' },
    )
    if (resp.ok) {
      const updated = await resp.json()
      // 更新详情弹窗
      detailItem.value = updated
      // 更新列表中的 cluster_labels
      const idx = results.value.findIndex((r) => r.id === resultId)
      if (idx >= 0 && updated.clusters) {
        results.value[idx].cluster_labels = updated.clusters.map((c: ClusterItem) => ({
          cluster_id: c.cluster_id,
          label: c.label,
          size: c.size,
        }))
      }
      const cluster = updated.clusters?.find((c: ClusterItem) => c.cluster_id === clusterId)
      message.success(`主题生成: ${cluster?.label || '完成'}`)
    } else {
      const err = await resp.json()
      message.error(err.detail || '主题生成失败')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '主题生成请求失败')
  } finally {
    generatingThemeId.value = null
  }
}

// ── 评估标题 ──

async function handleEvaluateThemes(resultId: string) {
  evalRunning.value = true
  evalReport.value = null
  try {
    const resp = await fetch(`${AGENT_BASE}/cluster/results/${resultId}/evaluate-themes`, {
      method: 'POST',
    })
    if (resp.ok) {
      evalReport.value = await resp.json()
      showEvalResult.value = true
    } else {
      const err = await resp.json()
      message.error(err.detail || '评估失败')
    }
  } catch (e) {
    message.error(e instanceof Error ? e.message : '评估请求失败')
  } finally {
    evalRunning.value = false
  }
}

// ── 详情 ──

async function showDetail(row: ClusterResultSummary) {
  detailVisible.value = true
  detailLoading.value = true
  detailItem.value = null
  expandedClusters.value = new Set()
  try {
    const resp = await fetch(`${AGENT_BASE}/cluster/results/${row.id}`)
    if (resp.ok) {
      detailItem.value = await resp.json()
    } else {
      message.error('加载详情失败')
      detailVisible.value = false
    }
  } catch (e) {
    console.warn('加载聚类详情失败', e)
    message.error('加载详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

// ── 全部展开切换 ──

function toggleExpandAll(clusterId: number) {
  const next = new Set(expandedClusters.value)
  if (next.has(clusterId)) {
    next.delete(clusterId)
  } else {
    next.add(clusterId)
  }
  expandedClusters.value = next
}

// ── 初始化 ──

onMounted(() => fetchResults())

// ── 表格列定义 ──

const columns = [
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
    render(row: ClusterResultSummary) {
      if (!row.created_at) return '—'
      return formatDate(row.created_at)
    },
  },
  {
    title: '簇数',
    key: 'num_clusters',
    width: 70,
    align: 'center' as const,
    render(row: ClusterResultSummary) {
      return h('strong', null, String(row.stats.num_clusters))
    },
  },
  {
    title: '已聚类 / 噪声 / 总计',
    key: 'photos',
    width: 150,
    align: 'center' as const,
    render(row: ClusterResultSummary) {
      const s = row.stats
      return h('span', null, `${s.clustered_photos} / ${s.noise_photos} / ${s.total_photos}`)
    },
  },
  {
    title: '耗时',
    key: 'duration',
    width: 70,
    align: 'center' as const,
    render(row: ClusterResultSummary) {
      return `${row.stats.duration_seconds}s`
    },
  },
  {
    title: '聚类率',
    key: 'ratio',
    width: 70,
    align: 'center' as const,
    render(row: ClusterResultSummary) {
      const s = row.stats
      if (s.total_photos === 0) return '—'
      return (s.clustered_photos / s.total_photos * 100).toFixed(0) + '%'
    },
  },
  {
    title: '参数',
    key: 'params',
    width: 160,
    ellipsis: { tooltip: true },
    render(row: ClusterResultSummary) {
      const p = row.params
      if (!p) return '—'
      return `min_cs=${p.min_cluster_size} n_neighbors=${p.umap_n_neighbors} metric=${p.umap_metric}`
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    render(row: ClusterResultSummary) {
      return h(NSpace, null, {
        default: () => [
          h(
            NButton,
            { size: 'tiny', onClick: () => showDetail(row) },
            { icon: () => h(NIcon, null, { default: () => h(EyeOutline) }) },
          ),
          h(
            NPopconfirm,
            { onPositiveClick: () => handleDelete(row.id) },
            {
              trigger: () =>
                h(
                  NButton,
                  { size: 'tiny', type: 'error' },
                  { icon: () => h(NIcon, null, { default: () => h(TrashOutline) }) },
                ),
              default: () => '确认删除该聚类结果？',
            },
          ),
        ],
      })
    },
  },
]
</script>

<template>
  <NLayout>
    <NLayoutHeader bordered>
      <div class="page-header">
        <div class="page-header-left">
          <NIcon size="20"><GitNetworkOutline /></NIcon>
          <h3 class="page-title">组图发现</h3>
          <NTag :bordered="false" size="small">
            {{ results.length }} 次结果
          </NTag>
        </div>
        <NSpace>
          <NButton
            size="small"
            type="primary"
            :loading="running"
            @click="showParamModal = true"
          >
            <template #icon>
              <NIcon><PlayOutline /></NIcon>
            </template>
            运行聚类
          </NButton>
        </NSpace>
      </div>
    </NLayoutHeader>

    <NLayoutContent>
      <div class="page-content">
        <!-- 加载状态 -->
        <NSpin :show="loading || running">
          <div v-if="running" class="running-state">
            <NSpin size="large" />
            <p>聚类计算中，请稍候...</p>
            <span class="running-hint">根据照片数量，可能需要几秒到几十秒</span>
          </div>

          <!-- 空状态 -->
          <div v-else-if="!loading && results.length === 0" class="empty-state">
            <NEmpty description="暂无聚类结果">
              <template #extra>
                <div class="empty-actions">
                  <span class="empty-hint">点击「运行聚类」开始分析照片库中的视觉相似分组</span>
                  <NButton size="small" type="primary" @click="showParamModal = true">
                    运行聚类
                  </NButton>
                </div>
              </template>
            </NEmpty>
          </div>

          <!-- 结果列表 -->
          <NDataTable
            v-else
            :columns="columns"
            :data="results"
            :row-key="(row: ClusterResultSummary) => row.id"
            :single-line="false"
            size="small"
            flex-height
            :row-props="(row: ClusterResultSummary) => ({ style: 'cursor: pointer;', onClick: () => showDetail(row) })"
            style="height: calc(100vh - 120px)"
          />
        </NSpin>
      </div>
    </NLayoutContent>

    <!-- 参数配置弹窗 -->
    <NModal
      v-model:show="showParamModal"
      preset="card"
      title="聚类参数配置"
      style="width: 520px; max-width: 90vw;"
    >
      <NForm
        :model="paramForm"
        label-placement="left"
        label-width="160"
        size="small"
      >
        <NFormItem label="最小簇大小 (min_cluster_size)">
          <NInputNumber
            v-model:value="paramForm.min_cluster_size"
            :min="2"
            :max="500"
            placeholder="5"
          />
          <span class="param-hint">一个簇至少包含的照片数，越小簇越多</span>
        </NFormItem>
        <NFormItem label="核心样本数 (min_samples)">
          <NInputNumber
            v-model:value="paramForm.min_samples"
            :min="1"
            :max="500"
            placeholder="3"
          />
          <span class="param-hint">核心点邻域最小样本数，越大越保守</span>
        </NFormItem>
        <NFormItem label="UMAP 邻域数 (n_neighbors)">
          <NInputNumber
            v-model:value="paramForm.umap_n_neighbors"
            :min="2"
            :max="200"
            placeholder="15"
          />
          <span class="param-hint">局部邻域大小，越大越关注全局结构</span>
        </NFormItem>
        <NFormItem label="UMAP 最小距离 (min_dist)">
          <NInputNumber
            v-model:value="paramForm.umap_min_dist"
            :min="0"
            :max="1"
            :step="0.05"
            placeholder="0.1"
          />
          <span class="param-hint">低维空间中点的最小距离</span>
        </NFormItem>
        <NFormItem label="UMAP 目标维度 (n_components)">
          <NInputNumber
            v-model:value="paramForm.umap_n_components"
            :min="2"
            :max="50"
            placeholder="5"
          />
          <span class="param-hint">降维后的维度数</span>
        </NFormItem>
        <NFormItem label="距离度量 (metric)">
          <NSelect
            v-model:value="paramForm.umap_metric"
            :options="umapMetricOptions"
            style="width: 160px"
          />
          <span class="param-hint">向量相似度度量方式</span>
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="showParamModal = false">取消</NButton>
          <NButton type="primary" :loading="false" @click="handleRunCluster">
            开始聚类
          </NButton>
        </NSpace>
      </template>
    </NModal>

    <!-- 详情弹窗 -->
    <NModal
      v-model:show="detailVisible"
      preset="card"
      title="聚类结果详情"
      style="width: 800px; max-width: 95vw;"
    >
      <template #header-extra>
        <NButton
          size="small"
          type="warning"
          :loading="evalRunning"
          @click="handleEvaluateThemes(detailItem!.id)"
        >
          <template #icon>
            <NIcon><CheckmarkCircleOutline /></NIcon>
          </template>
          评估标题
        </NButton>
      </template>
      <NSpin :show="detailLoading">
        <div v-if="detailItem" class="detail-body">
          <!-- 统计摘要 -->
          <div class="detail-summary">
            <div class="detail-metric">
              <span class="detail-metric-value">{{ detailItem.stats.num_clusters }}</span>
              <span class="detail-metric-label">聚类簇数</span>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-value">{{ detailItem.stats.clustered_photos }}</span>
              <span class="detail-metric-label">已聚类</span>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-value">{{ detailItem.stats.noise_photos }}</span>
              <span class="detail-metric-label">噪声</span>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-value">{{ detailItem.stats.total_photos }}</span>
              <span class="detail-metric-label">总计</span>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-value">{{ detailItem.stats.duration_seconds }}s</span>
              <span class="detail-metric-label">耗时</span>
            </div>
            <div class="detail-metric">
              <span class="detail-metric-value">
                {{ detailItem.stats.total_photos > 0 ? (detailItem.stats.clustered_photos / detailItem.stats.total_photos * 100).toFixed(0) : 0 }}%
              </span>
              <span class="detail-metric-label">聚类率</span>
            </div>
          </div>

          <!-- 参数摘要 -->
          <div class="detail-params">
            <span class="detail-label">参数：</span>
            <NTag
              v-for="(v, k) in detailItem.params"
              :key="k"
              size="tiny"
              :bordered="false"
            >
              {{ k }}={{ v }}
            </NTag>
          </div>

          <!-- 簇列表 -->
          <div class="cluster-list">
            <div
              v-for="c in detailItem.clusters"
              :key="c.cluster_id"
              class="cluster-card"
            >
              <div class="cluster-card-header">
                <div class="cluster-title-area">
                  <span class="cluster-label">{{ c.label || `聚类 ${c.cluster_id}` }}</span>
                  <span v-if="c.theme_description" class="cluster-theme-desc">{{ c.theme_description }}</span>
                </div>
                <NSpace size="small">
                  <NTag size="tiny" :bordered="false" type="info">{{ c.size }} 张</NTag>
                  <NTag size="tiny" :bordered="false">凝聚度 {{ (c.coherence_score * 100).toFixed(0) }}%</NTag>
                  <NButton
                    v-if="c.size > 3"
                    size="tiny"
                    :type="expandedClusters.has(c.cluster_id) ? 'warning' : 'default'"
                    @click.stop="toggleExpandAll(c.cluster_id)"
                  >
                    <template #icon>
                      <NIcon><AppsOutline /></NIcon>
                    </template>
                    {{ expandedClusters.has(c.cluster_id) ? '收起' : '展开全部' }}
                  </NButton>
                  <NButton
                    size="tiny"
                    :type="c.theme_description ? 'default' : 'primary'"
                    :loading="generatingThemeId === c.cluster_id"
                    @click.stop="handleGenerateTheme(detailItem!.id, c.cluster_id)"
                  >
                    {{ c.theme_description ? '重新生成' : '生成主题' }}
                  </NButton>
                </NSpace>
              </div>
              <PhotoThumbList
                :photos="c.photos"
                :max-preview="expandedClusters.has(c.cluster_id) ? 0 : 3"
                @preview="openPreview"
              />
            </div>
          </div>

          <!-- 评估结果区域 -->
          <div v-if="evalReport" class="eval-result-section">
            <div class="eval-result-header">
              <span class="eval-result-title">标题评估结果</span>
              <NTag :bordered="false" size="small" :type="evalReport.heuristic.failed === 0 ? 'success' : 'warning'">
                {{ evalReport.heuristic.passed }}/{{ evalReport.heuristic.total_checks }} 通过
              </NTag>
            </div>
            <div v-if="evalReport.heuristic.failed > 0" class="eval-failures">
              <div
                v-for="f in evalReport.heuristic.failures"
                :key="`${f.rule_id}-${f.cluster_id}`"
                class="eval-failure-item"
              >
                <NTag :bordered="false" size="tiny" :type="f.severity === 'error' ? 'error' : 'warning'">
                  {{ f.severity === 'error' ? '错误' : '警告' }}
                </NTag>
                <span v-if="f.cluster_id !== null && f.cluster_id !== undefined" class="eval-failure-cluster">
                  簇 {{ f.cluster_id }}
                </span>
                <span class="eval-failure-msg">{{ f.message }}</span>
              </div>
            </div>
            <div v-else class="eval-all-passed">
              <NIcon color="var(--n-color-success)"><CheckmarkCircleOutline /></NIcon>
              <span>全部检查通过</span>
            </div>
          </div>
        </div>
      </NSpin>
    </NModal>

    <!-- 图片预览弹窗 -->
    <PhotoPreviewModal v-model:show="previewShow" :image-url="previewImg" />
  </NLayout>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
}
.page-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.page-title {
  margin: 0;
  font-size: 16px;
}
.page-content {
  padding: 16px 24px;
}
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}
.empty-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.empty-hint {
  font-size: 13px;
  color: var(--n-text-color-3);
}
.running-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 400px;
  color: var(--n-text-color-2);
}
.running-hint {
  font-size: 12px;
  color: var(--n-text-color-3);
}

/* 参数面板 */
.param-hint {
  display: block;
  font-size: 11px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}

/* 详情 */
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.detail-summary {
  display: flex;
  gap: 20px;
  padding: 12px 0;
  border-bottom: 1px solid var(--n-border-color);
}
.detail-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.detail-metric-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--n-color-primary);
}
.detail-metric-label {
  font-size: 11px;
  color: var(--n-text-color-3);
}
.detail-params {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.detail-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-3);
}
.cluster-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 500px;
  overflow-y: auto;
}
.cluster-card {
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  padding: 12px;
}
.cluster-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.cluster-title-area {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cluster-label {
  font-size: 14px;
  font-weight: 600;
}
.cluster-theme-desc {
  font-size: 12px;
  color: var(--n-text-color-3);
  line-height: 1.4;
}

/* 评估结果 */
.eval-result-section {
  margin-top: 8px;
  padding: 12px;
  background: var(--n-color-embedded);
  border-radius: 8px;
  border: 1px solid var(--n-border-color);
}
.eval-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.eval-result-title {
  font-size: 14px;
  font-weight: 600;
}
.eval-failures {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.eval-failure-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 4px 8px;
  background: var(--n-color-action);
  border-radius: 4px;
}
.eval-failure-cluster {
  font-weight: 600;
  color: var(--n-color-text-2);
  white-space: nowrap;
}
.eval-failure-msg {
  color: var(--n-color-text-3);
  flex: 1;
}
.eval-all-passed {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--n-color-success);
}
</style>
