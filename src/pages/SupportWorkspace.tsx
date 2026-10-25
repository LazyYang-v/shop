import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getCsrfToken, notifySessionExpired } from '../api/auth'
import './support.css'

type Section = 'cases' | 'knowledge' | 'channels' | 'metrics'
type CaseStatus = 'open' | 'in_progress' | 'waiting_buyer' | 'resolved' | 'rejected'
type ReviewStatus = Exclude<CaseStatus, 'open'>
type Message = { role: string; text: string; at?: string }
type SupportCase = {
  id: string; kind: string; kind_label: string; status: CaseStatus; priority: string
  order_id: string | null; buyer_id: string; assigned: boolean; assigned_to: string | null
  summary: {
    concern?: string; verified_facts?: Record<string, unknown>[]; executed_actions?: Record<string, unknown>[]
    blocker?: string; escalation_reason?: string; history?: Message[]; history_shared?: boolean
  }
  details: Record<string, unknown>; messages: Message[]
  created_at: string; updated_at: string; expires_at: string
}
type CasePage = { items: SupportCase[]; total: number; page: number }
type KnowledgeKind = 'faq' | 'product' | 'policy' | 'promotion'
type KnowledgeState = 'draft' | 'published' | 'retired'
type KnowledgeInput = {
  kind: KnowledgeKind; topic: string; title: string; body: string; source: string
  keywords: string[]; attributes: Record<string, unknown>; product_id: string | null
  state: KnowledgeState; valid_from: string; valid_until: string | null
}
type Knowledge = KnowledgeInput & { id: string; version: number }
type ChannelSettings = { display_name: string; welcome: string; handoff_threshold: number }
type Channel = { name: string; connected: boolean; adapter: string; settings: ChannelSettings }
type Ratio = { numerator: number; denominator: number; value: number | null }
type MetricKey = 'resolution_rate' | 'handoff_rate' | 'tool_success_rate' | 'retrieval_hit_rate' | 'satisfaction'
type Metrics = Record<MetricKey, Ratio> & {
  days: number; from: string; to: string; turns: number; consultations: number
  routes: Record<string, number>; definitions: Record<MetricKey, string>
}
type Write = {
  pending: boolean
  run: (task: () => Promise<unknown>, success: string, done?: () => void) => Promise<void>
}

const caseStatuses: Array<{ value: CaseStatus; label: string }> = [
  { value: 'open', label: '待接手' }, { value: 'in_progress', label: '处理中' },
  { value: 'waiting_buyer', label: '等待买家' }, { value: 'resolved', label: '已解决' },
  { value: 'rejected', label: '已拒绝' },
]
const knowledgeKinds: Record<KnowledgeKind, string> = { faq: '常见问题', product: '商品知识', policy: '服务政策', promotion: '促销规则' }
const knowledgeStates: Record<KnowledgeState, string> = { draft: '草稿', published: '已发布', retired: '已停用' }
const channelNames: Record<string, string> = { storefront: '商城', taobao: '淘宝', jd: '京东', douyin: '抖音', pinduoduo: '拼多多' }
const metricNames: Record<MetricKey, string> = {
  resolution_rate: '反馈解决率', handoff_rate: '人工升级率', tool_success_rate: '工具成功率',
  retrieval_hit_rate: '知识检索命中率', satisfaction: '满意反馈率',
}
const recordLabels: Record<string, string> = {
  source: '来源', order_id: '订单编号', product_id: '商品编号', status: '状态', total: '订单金额',
  queried_at: '查询时间', at: '时间', action: '动作', address_id: '买家选择的地址编号', invoice_title: '发票抬头',
}
const statusLabel = (value: CaseStatus) => caseStatuses.find(item => item.value === value)?.label ?? value
const time = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const field = (data: FormData, name: string) => String(data.get(name) ?? '').trim()
const localDate = (value?: string | null) => {
  if (value === null) return ''
  const date = value ? new Date(value) : new Date()
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 19)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/admin/customer-service${path}`, { ...init, credentials: 'same-origin', cache: 'no-store' })
  if (response.status === 401) notifySessionExpired()
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item: { loc?: unknown[]; msg?: string }) => `${item.loc?.slice(1).join('.') || '输入'}：${item.msg || '格式不正确'}`).join('；')
      : response.status === 403 ? '无管理员权限，或安全令牌已失效，请重新登录后重试。' : `请求失败 (${response.status})`
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
async function mutate<T>(path: string, method: 'POST' | 'PATCH' | 'PUT', body: unknown = {}): Promise<T> {
  const token = await getCsrfToken()
  return request<T>(path, {
    method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token }, body: JSON.stringify(body),
  })
}

function QueryState({ loading, error, retry, children }: {
  loading: boolean; error: Error | null; retry: () => unknown; children: ReactNode
}) {
  if (loading) return <p className="admin-empty" role="status">正在加载…</p>
  if (error) return <div className="admin-notice admin-error" role="alert"><p>{error.message}</p><button type="button" onClick={() => retry()}>重新加载</button></div>
  return <>{children}</>
}
function Records({ items, empty }: { items?: Record<string, unknown>[]; empty: string }) {
  if (!items?.length) return <p className="admin-muted">{empty}</p>
  return <ul className="support-records">{items.map((item, index) => <li key={index}><dl className="support-facts">{Object.entries(item).map(([key, value]) => <div key={key}>
    <dt>{recordLabels[key] ?? key}</dt><dd>{value === null ? '—' : typeof value === 'object' ? <pre>{JSON.stringify(value, null, 2)}</pre> : String(value)}</dd>
  </div>)}</dl></li>)}</ul>
}
function Conversation({ items, empty }: { items?: Message[]; empty: string }) {
  const roles: Record<string, string> = { user: '买家', buyer: '买家', assistant: '客服助手', staff: '人工客服' }
  if (!items?.length) return <p className="admin-muted">{empty}</p>
  return <ol className="support-messages">{items.map((item, index) => <li key={index}>
    <div className="support-message-heading"><strong>{roles[item.role] ?? item.role}</strong>{item.at && <time dateTime={item.at}>{time(item.at)}</time>}</div>
    <p>{item.text}</p>
  </li>)}</ol>
}

export default function SupportWorkspace({ userId }: { userId: string }) {
  const client = useQueryClient()
  const [section, setSection] = useState<Section>('cases')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const lock = useRef(false)
  const write: Write = { pending, run: async (task, success, done) => {
    if (lock.current) return
    lock.current = true
    setPending(true); setError(''); setMessage('')
    try {
      await task()
      setMessage(success)
      done?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请重试。')
    } finally {
      try {
        await client.invalidateQueries({ queryKey: ['admin', userId, 'support'] })
      } finally {
        lock.current = false; setPending(false)
      }
    }
  } }
  const sections: Array<{ value: Section; label: string }> = [
    { value: 'cases', label: '人工工单' }, { value: 'knowledge', label: '知识库' },
    { value: 'channels', label: '渠道设置' }, { value: 'metrics', label: '服务指标' },
  ]
  return <div className="support-workspace admin-stack">
    <section className="admin-card support-intro"><h2>客服工作台</h2><p className="admin-muted">核对买家诉求、维护知识依据与渠道配置，查看实际服务样本。</p>
      <nav className="support-nav" aria-label="客服管理栏目">{sections.map(item => <button type="button" key={item.value} aria-pressed={section === item.value} disabled={pending} onClick={() => { setSection(item.value); setError(''); setMessage('') }}>{item.label}</button>)}</nav>
    </section>
    {error && <p className="admin-notice admin-error" role="alert">{error}</p>}
    {message && <p className="admin-notice" role="status">{message}</p>}
    {section === 'cases' && <Cases userId={userId} write={write} />}
    {section === 'knowledge' && <KnowledgePanel userId={userId} write={write} />}
    {section === 'channels' && <Channels userId={userId} write={write} />}
    {section === 'metrics' && <ServiceMetrics userId={userId} />}
  </div>
}

function Cases({ userId, write }: { userId: string; write: Write }) {
  const [status, setStatus] = useState<CaseStatus | ''>('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<SupportCase | null>(null)
  const list = useQuery({
    queryKey: ['admin', userId, 'support', 'cases', status, page], retry: false,
    queryFn: ({ signal }) => request<CasePage>(`/cases?${new URLSearchParams({ page: String(page), ...(status ? { status } : {}) })}`, { signal }),
  })
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / 20))
  const latest = list.data?.items.find(item => item.id === selected?.id)
  const stale = Boolean(!write.pending && selected && latest && latest.updated_at !== selected.updated_at)
  return <div className="admin-stack">
    <section className="admin-card">
      <div className="admin-section-heading"><h2>人工工单</h2><button type="button" disabled={list.isFetching || write.pending} onClick={() => void list.refetch()}>刷新列表</button></div>
      <div className="admin-filters"><label>工单状态<select value={status} disabled={write.pending} onChange={event => { setStatus(event.target.value as CaseStatus | ''); setPage(1); setSelected(null) }}><option value="">全部状态</option>{caseStatuses.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><span className="admin-muted">每页 20 条；仅显示保留期内的工单。</span></div>
      <QueryState loading={list.isPending} error={list.error} retry={list.refetch}>
        {list.data?.items.length === 0 ? <p className="admin-empty">暂无符合条件的工单</p> : <div className="admin-table-wrap"><table>
          <caption className="support-sr-only">工单列表，可选择工单查看上下文并审核</caption>
          <thead><tr><th scope="col">工单 / 诉求</th><th scope="col">状态</th><th scope="col">优先级 / 接手人</th><th scope="col">更新时间</th><th scope="col">操作</th></tr></thead>
          <tbody>{list.data?.items.map(item => <tr key={item.id} className={selected?.id === item.id ? 'support-selected' : undefined}>
            <td><strong>{item.kind_label}</strong><p className="support-excerpt">{item.summary.concern || '—'}</p><span className="admin-id">{item.id}</span></td>
            <td><span className="support-status">{statusLabel(item.status)}</span></td><td>{item.priority === 'urgent' ? '紧急' : item.priority === 'normal' ? '普通' : item.priority}<br /><span className="admin-id">{item.assigned_to === userId ? '由你接手' : item.assigned_to ? item.assigned_to : '尚未接手'}</span></td>
            <td>{time(item.updated_at)}</td><td><button type="button" disabled={write.pending} aria-pressed={selected?.id === item.id} aria-label={`查看${item.kind_label}工单 ${item.id}`} onClick={() => setSelected(item)}>查看 / 审核</button></td>
          </tr>)}</tbody>
        </table></div>}
      </QueryState>
      {list.data && <nav className="admin-pagination" aria-label="工单分页"><span>共 {list.data.total} 条</span><button type="button" disabled={list.isFetching || write.pending || page <= 1} onClick={() => { setPage(value => value - 1); setSelected(null) }}>上一页</button><span aria-live="polite">第 {page} / {pages} 页</span><button type="button" disabled={list.isFetching || write.pending || page >= pages} onClick={() => { setPage(value => value + 1); setSelected(null) }}>下一页</button></nav>}
    </section>
    {selected && <section className="admin-card" aria-label="所选工单详情">
      <div className="admin-section-heading"><h2>{selected.kind_label} · {statusLabel(selected.status)}</h2><button type="button" disabled={write.pending} onClick={() => setSelected(null)}>收起详情</button></div>
      {stale && <div className="admin-notice" role="status"><p>工单已有新版本。载入后重新核对，再提交回复；当前草稿将清空。</p><button type="button" disabled={write.pending} onClick={() => latest && setSelected(latest)}>载入新版本</button></div>}
      <CaseDetail key={`${selected.id}:${selected.updated_at}`} item={selected} userId={userId} write={write} stale={stale} onUpdated={setSelected} />
    </section>}
  </div>
}

function CaseDetail({ item, userId, write, stale, onUpdated }: {
  item: SupportCase; userId: string; write: Write; stale: boolean; onUpdated: (item: SupportCase) => void
}) {
  const client = useQueryClient()
  const [nextStatus, setNextStatus] = useState<ReviewStatus>('in_progress')
  const [validation, setValidation] = useState('')
  const ended = item.status === 'resolved' || item.status === 'rejected'
  const otherStaff = Boolean(item.assigned_to && item.assigned_to !== userId)
  const summary = item.summary
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const reply = field(data, 'reply')
    if (!reply) { setValidation('请填写给买家的回复。'); return }
    if (ended || otherStaff || stale) return
    setValidation('')
    const applyAddress = item.kind === 'address_change' && nextStatus === 'resolved' && data.get('apply_address') === 'on'
    void write.run(async () => {
      const result = await mutate<{ case: SupportCase }>(`/cases/${encodeURIComponent(item.id)}`, 'PATCH', {
        status: nextStatus, reply, expected_updated_at: item.updated_at, apply_address: applyAddress,
      })
      onUpdated(result.case)
      if (applyAddress) await Promise.all([
        client.invalidateQueries({ queryKey: ['admin', userId, 'orders'] }),
        client.invalidateQueries({ queryKey: ['admin', userId, 'order', item.order_id] }),
      ])
    }, applyAddress ? '回复与工单状态已保存，已应用买家选择的地址。' : '回复与工单状态已保存。')
  }
  return <>
    <dl className="support-facts support-case-facts">
      <div><dt>工单编号</dt><dd>{item.id}</dd></div><div><dt>买家编号</dt><dd>{item.buyer_id}</dd></div>
      <div><dt>关联订单</dt><dd>{item.order_id ? <a className="support-link" href={`?view=admin&tab=orders`}>{item.order_id}（前往订单管理）</a> : '—'}</dd></div>
      <div><dt>接手管理员</dt><dd>{item.assigned_to === userId ? '你' : item.assigned_to || '尚未接手'}</dd></div>
      <div><dt>创建时间</dt><dd>{time(item.created_at)}</dd></div><div><dt>审核版本时间</dt><dd>{time(item.updated_at)}</dd></div>
      <div><dt>保留至</dt><dd>{time(item.expires_at)}</dd></div><div><dt>升级原因</dt><dd>{summary.escalation_reason || '—'}</dd></div>
    </dl>
    <h3>诉求摘要</h3><p className="support-prose">{summary.concern || '—'}</p>
    <h3>当前阻塞</h3><p className="support-prose support-blocker">{summary.blocker || '未记录'}</p>
    <div className="support-detail-grid"><section><h3>已核实事实</h3><Records items={summary.verified_facts} empty="暂无已核实事实，请先核对相关业务记录。" /></section><section><h3>已执行动作</h3><Records items={summary.executed_actions} empty="尚无执行动作记录。" /><h3>申请明细</h3><Records items={Object.keys(item.details).length ? [item.details] : []} empty="无附加明细。" /></section></div>
    <details className="support-disclosure"><summary>咨询历史 · {summary.history_shared ? '买家已授权共享' : '未共享'}</summary><Conversation items={summary.history} empty={summary.history_shared ? '本次没有可共享的咨询记录。' : '买家未共享咨询历史。'} /></details>
    <h3>工单往来</h3><Conversation items={item.messages} empty="尚无工单回复。" />
    {ended ? <p className="admin-muted">工单已结束；买家补充问题后可重新处理。</p> : otherStaff ? <p className="admin-notice">该工单已由其他管理员接手，请由接手人继续处理。</p> : <form className="admin-form support-review" onSubmit={submit}>
      <h3>审核并回复买家</h3><p className="admin-muted">提交后由你接手。状态记录处理进展；提交不会自动退款、补偿或发货。</p>
      <fieldset disabled={write.pending || stale}>
        <label>处理状态<select name="status" value={nextStatus} onChange={event => setNextStatus(event.target.value as ReviewStatus)}>{caseStatuses.filter(option => option.value !== 'open').map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>给买家的回复<textarea name="reply" required maxLength={1200} rows={4} placeholder="说明核实结果、下一步和仍需补充的信息" /></label>
        {item.kind === 'address_change' && nextStatus === 'resolved' && <label className="admin-check support-address-consent"><input type="checkbox" name="apply_address" />明确应用买家选择的地址簿地址到此订单（仅限待发货订单）</label>}
        {item.kind === 'address_change' && <p className="admin-muted">仅勾选并将工单设为“已解决”时才修改订单地址，提交时会重新核验订单与地址归属。</p>}
        {validation && <p className="admin-error" role="alert">{validation}</p>}
        <button className="admin-primary" type="submit">{write.pending ? '正在提交…' : '提交审核与回复'}</button>
      </fieldset>
    </form>}
  </>
}

function KnowledgePanel({ userId, write }: { userId: string; write: Write }) {
  const [seed, setSeed] = useState<Knowledge | undefined>()
  const [revision, setRevision] = useState(0)
  const editor = useRef<HTMLDivElement>(null)
  const list = useQuery({
    queryKey: ['admin', userId, 'support', 'knowledge'], retry: false,
    queryFn: ({ signal }) => request<{ items: Knowledge[] }>('/knowledge', { signal }),
  })
  function reuse(item?: Knowledge) {
    setSeed(item); setRevision(value => value + 1)
    editor.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    editor.current?.focus({ preventScroll: true })
  }
  return <div className="admin-stack">
    <section className="admin-card" ref={editor} tabIndex={-1}>
      <div className="admin-section-heading"><h2>{seed ? '复用知识创建新版本' : '新增知识'}</h2>{seed && <button type="button" disabled={write.pending} onClick={() => reuse()}>清空，新增知识</button>}</div>
      <p className="admin-muted">版本号由服务器按类型、主题与商品生成。发布区间重叠时需先停用旧版本；复用默认保存为草稿。</p>
      {seed && <p className="admin-muted">复用：{seed.title} · v{seed.version}</p>}
      <KnowledgeForm key={revision} seed={seed} write={write} />
    </section>
    <section className="admin-card"><div className="admin-section-heading"><h2>知识条目</h2><button type="button" disabled={write.pending || list.isFetching} onClick={() => void list.refetch()}>刷新知识</button></div><p className="admin-muted">按更新时间展示最近 200 条；展开条目可检查正文与结构化属性。</p>
      <QueryState loading={list.isPending} error={list.error} retry={list.refetch}>
        {!list.data?.items.length ? <p className="admin-empty">暂无知识条目</p> : <div className="admin-table-wrap"><table>
          <caption className="support-sr-only">知识版本、来源、生效区间与操作</caption>
          <thead><tr><th scope="col">知识 / 内容</th><th scope="col">来源</th><th scope="col">版本 / 状态</th><th scope="col">生效区间</th><th scope="col">操作</th></tr></thead>
          <tbody>{list.data.items.map(item => <tr key={item.id}>
            <td><strong>{item.title}</strong><p className="admin-muted">{knowledgeKinds[item.kind]} · {item.topic}</p>{item.product_id && <p className="admin-id">商品：{item.product_id}</p>}<details className="support-knowledge-content"><summary>查看正文与属性</summary><p className="support-prose">{item.body}</p><p>关键词：{item.keywords.join('、') || '—'}</p><pre>{JSON.stringify(item.attributes, null, 2)}</pre></details></td>
            <td>{item.source}</td><td>v{item.version}<br /><span className="support-status">{knowledgeStates[item.state]}</span></td>
            <td>{time(item.valid_from)}<br />至 {item.valid_until ? time(item.valid_until) : '长期有效'}</td>
            <td><div className="admin-row-actions"><button type="button" disabled={write.pending} onClick={() => reuse(item)} aria-label={`复用知识 ${item.title} v${item.version}`}>复用表单</button><button type="button" disabled={write.pending || item.state === 'retired'} onClick={() => void write.run(() => mutate(`/knowledge/${encodeURIComponent(item.id)}/retire`, 'POST'), `知识“${item.title}” v${item.version} 已停用。`)} aria-label={`停用知识 ${item.title} v${item.version}`}>{item.state === 'retired' ? '已停用' : '停用'}</button></div></td>
          </tr>)}</tbody>
        </table></div>}
      </QueryState>
    </section>
  </div>
}

function KnowledgeForm({ seed, write }: { seed?: Knowledge; write: Write }) {
  const [kind, setKind] = useState<KnowledgeKind>(seed?.kind ?? 'faq')
  const [validation, setValidation] = useState('')
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    try {
      const attributes: unknown = JSON.parse(field(data, 'attributes') || '{}')
      if (!attributes || typeof attributes !== 'object' || Array.isArray(attributes)) throw new Error('结构化属性必须是 JSON 对象，不能是数组或空值。')
      if (JSON.stringify(attributes).length > 12000) throw new Error('结构化属性过长，请精简到 12000 字符以内。')
      if ('size_chart' in attributes) {
        const chart = attributes.size_chart
        const maximums: Record<string, number> = { height_cm: 250, weight_kg: 400, chest_cm: 250, waist_cm: 250 }
        if (!chart || typeof chart !== 'object' || Array.isArray(chart) || !Object.keys(chart).length || Object.keys(chart).length > 30) throw new Error('尺码表须为以尺码名称为键的 JSON 对象，请参考下方示例。')
        for (const [label, dimensions] of Object.entries(chart)) {
          if (!label.trim() || label.length > 40 || !dimensions || typeof dimensions !== 'object' || Array.isArray(dimensions) || !Object.keys(dimensions).length) throw new Error('每个尺码须有名称和测量范围。')
          for (const [key, interval] of Object.entries(dimensions)) {
            if (!Object.hasOwn(maximums, key) || !Array.isArray(interval) || interval.length !== 2 || interval.some(value => typeof value !== 'number' || !Number.isFinite(value) || value <= 0 || value > maximums[key]) || interval[0] > interval[1]) throw new Error('尺码范围使用 height_cm、weight_kg、chest_cm 或 waist_cm，每项填写 [下限,上限]。')
          }
        }
      }
      const keywords = field(data, 'keywords').split(/\r?\n/).map(word => word.trim()).filter(Boolean)
      if (keywords.length > 20 || keywords.some(word => word.length > 80)) throw new Error('关键词最多 20 项，每项最多 80 字符。')
      const productId = field(data, 'product_id')
      if (kind === 'product' && !productId) throw new Error('商品知识必须填写商品编号。')
      if (productId && !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(productId)) throw new Error('商品编号须为有效的 UUID。')
      const from = new Date(field(data, 'valid_from'))
      const untilText = field(data, 'valid_until')
      const until = untilText ? new Date(untilText) : null
      if (!Number.isFinite(from.getTime()) || (until && (!Number.isFinite(until.getTime()) || until <= from))) throw new Error('请填写有效日期，结束时间须晚于开始时间。')
      const input: KnowledgeInput = {
        kind, topic: field(data, 'topic'), title: field(data, 'title'), body: field(data, 'body'), source: field(data, 'source'),
        keywords, attributes: attributes as Record<string, unknown>, product_id: productId || null,
        state: field(data, 'state') as KnowledgeState, valid_from: from.toISOString(), valid_until: until?.toISOString() ?? null,
      }
      if (!input.topic || !input.title || !input.body || !input.source) throw new Error('主题、标题、正文与来源均不能为空。')
      setValidation('')
      void write.run(async () => {
        const result = await mutate<{ id: string; version: number; state: KnowledgeState }>('/knowledge', 'POST', input)
        setValidation(`已创建 v${result.version}（${knowledgeStates[result.state]}）。再次提交将创建另一个版本。`)
      }, '知识版本已创建。')
    } catch (err) {
      setValidation(err instanceof SyntaxError ? '结构化属性 JSON 格式不正确，请检查引号、逗号与括号。' : err instanceof Error ? err.message : '请检查表单内容。')
    }
  }
  return <form className="admin-form" onSubmit={submit}><fieldset disabled={write.pending}>
    <div className="admin-form-grid">
      <label>知识类型<select name="kind" value={kind} onChange={event => setKind(event.target.value as KnowledgeKind)}>{Object.entries(knowledgeKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>主题（用于版本分组）<input name="topic" required maxLength={100} defaultValue={seed?.topic} placeholder="例如 return_policy" /></label>
      <label>标题<input name="title" required maxLength={200} defaultValue={seed?.title} /></label>
      <label>商品编号（UUID，商品知识必填）<input name="product_id" required={kind === 'product'} maxLength={36} defaultValue={seed?.product_id ?? ''} /></label>
      <label>来源<input name="source" required maxLength={500} defaultValue={seed?.source} placeholder="可核验的业务文档、链接或出处" /></label>
      <label>保存状态<select name="state" defaultValue="draft">{Object.entries(knowledgeStates).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>生效开始<input name="valid_from" type="datetime-local" step="1" required defaultValue={localDate(seed?.valid_from)} /></label>
      <label>生效结束（留空为长期）<input name="valid_until" type="datetime-local" step="1" defaultValue={localDate(seed?.valid_until ?? null)} /></label>
    </div>
    <p className="admin-muted">时间按本机时区 {Intl.DateTimeFormat().resolvedOptions().timeZone} 输入，提交时包含时区。</p>
    <label>正文<textarea name="body" required maxLength={8000} rows={5} defaultValue={seed?.body} /></label>
    <label>关键词（每行一项，最多 20 项，每项 80 字符）<textarea name="keywords" rows={3} defaultValue={seed?.keywords.join('\n')} /></label>
    <label>结构化属性（JSON 对象）<textarea className="support-code" name="attributes" rows={7} defaultValue={seed ? JSON.stringify(seed.attributes, null, 2) : '{}'} aria-describedby="support-attributes-help" spellCheck={false} /></label>
    <p className="admin-muted" id="support-attributes-help">按需维护 material（材质）、specs（规格）、size_chart（尺码范围）、skin_types（适用肤质）、skin_tones（适用肤色）、tags（标签）。尺码例：<code>{'{"material":"棉","size_chart":{"M":{"height_cm":[160,170],"weight_kg":[50,60]}}}'}</code>；护肤例：<code>{'{"ingredients":["商家核实的成分"],"skin_types":["干皮"],"skin_tones":["暖黄皮"]}'}</code>。只填写商品已核实的属性，提交上限 12000 字符。</p>
    {validation && <p className={validation.startsWith('已创建') ? 'admin-notice' : 'admin-error'} role={validation.startsWith('已创建') ? 'status' : 'alert'}>{validation}</p>}
    <button type="submit" className="admin-primary">{write.pending ? '正在提交…' : '创建知识版本'}</button>
  </fieldset></form>
}

function Channels({ userId, write }: { userId: string; write: Write }) {
  const list = useQuery({
    queryKey: ['admin', userId, 'support', 'channels'], retry: false,
    queryFn: ({ signal }) => request<{ items: Channel[] }>('/channels', { signal }),
  })
  return <section className="admin-card"><div className="admin-section-heading"><h2>渠道状态与配置</h2><button type="button" disabled={write.pending || list.isFetching} onClick={() => void list.refetch()}>刷新渠道</button></div>
    <p className="admin-muted">商城使用现有登录会话。外部平台显示各自实际接入状态；保存展示名称、欢迎语或阈值仅更新本地配置。</p>
    <QueryState loading={list.isPending} error={list.error} retry={list.refetch}>
      {!list.data?.items.length ? <p className="admin-empty">暂无渠道配置</p> : <div className="support-channels">{list.data.items.map(channel => <ChannelForm key={channel.name} channel={channel} write={write} />)}</div>}
    </QueryState>
  </section>
}
function ChannelForm({ channel, write }: { channel: Channel; write: Write }) {
  const [validation, setValidation] = useState('')
  const [dirty, setDirty] = useState(false)
  const [savedSettings, setSavedSettings] = useState<ChannelSettings | null>(null)
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const input: ChannelSettings = { display_name: field(data, 'display_name'), welcome: field(data, 'welcome'), handoff_threshold: Number(field(data, 'handoff_threshold')) }
    if (!input.display_name || !Number.isFinite(input.handoff_threshold) || input.handoff_threshold < 0.2 || input.handoff_threshold > 0.8) { setValidation('请填写展示名称；人工升级阈值须在 0.2 到 0.8 之间。'); return }
    setValidation('')
    void write.run(async () => {
      await mutate(`/channels/${encodeURIComponent(channel.name)}`, 'PUT', input)
      setSavedSettings(input); setDirty(false)
    }, `${channelNames[channel.name] ?? channel.name}渠道配置已保存。`)
  }
  const settings = savedSettings ?? channel.settings
  return <article className="support-channel">
    <div className="admin-section-heading"><h3>{channelNames[channel.name] ?? channel.name}</h3><span className="support-status">{channel.connected ? '已接入' : '未接入'}</span></div>
    <p className="admin-muted">渠道：{channel.name} · 适配器：{channel.adapter === 'storefront_session' ? '商城登录会话' : channel.adapter === 'not_configured' ? '未配置' : channel.adapter}</p>
    <form className="admin-form" onSubmit={submit} onChange={() => setDirty(true)}><fieldset disabled={write.pending}>
      <label>展示名称<input name="display_name" required maxLength={80} defaultValue={settings.display_name} /></label>
      <label>欢迎语<textarea name="welcome" maxLength={300} rows={2} defaultValue={settings.welcome} /></label>
      <label>人工升级阈值（0.2–0.8）<input name="handoff_threshold" type="number" required min="0.2" max="0.8" step="any" defaultValue={settings.handoff_threshold} /></label>
      {validation && <p className="admin-error" role="alert">{validation}</p>}
      <div className="support-save-row"><button type="submit" disabled={!dirty}>{write.pending ? '正在保存…' : '保存配置'}</button>{dirty && <span className="admin-muted">有未保存修改</span>}</div>
    </fieldset></form>
  </article>
}

function ServiceMetrics({ userId }: { userId: string }) {
  const [days, setDays] = useState(7)
  const metrics = useQuery({
    queryKey: ['admin', userId, 'support', 'metrics', days], retry: false,
    queryFn: ({ signal }) => request<Metrics>(`/metrics?days=${days}`, { signal }),
  })
  const data = metrics.data
  const routes = Object.entries(data?.routes ?? {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  return <section className="admin-card support-metrics">
    <div className="admin-section-heading"><h2>服务指标</h2><button type="button" disabled={metrics.isFetching} onClick={() => void metrics.refetch()}>刷新指标</button></div>
    <form className="admin-filters" onSubmit={event => { event.preventDefault(); const value = Number(field(new FormData(event.currentTarget), 'days')); if (Number.isInteger(value) && value >= 1 && value <= 30) setDays(value) }}>
      <label>统计天数（1–30 天）<input name="days" type="number" min="1" max="30" step="1" required defaultValue={days} /></label><button type="submit" disabled={metrics.isFetching}>应用范围</button>
    </form>
    <QueryState loading={metrics.isPending} error={metrics.error} retry={metrics.refetch}>
      {data && <>
        <p className="admin-muted">实际窗口：{time(data.from)} 至 {time(data.to)}（最近 {data.days} 天）</p>
        <dl className="support-metric-counts"><div><dt>对话轮次</dt><dd>{data.turns.toLocaleString('zh-CN')}</dd></div><div><dt>有对话的咨询数</dt><dd>{data.consultations.toLocaleString('zh-CN')}</dd></div></dl>
        <div className="admin-table-wrap"><table>
          <caption>服务比例及统计口径。比例为百分比；无样本时显示“—”。</caption>
          <thead><tr><th scope="col">指标</th><th scope="col" className="support-number">比例</th><th scope="col" className="support-number">实际分子</th><th scope="col" className="support-number">实际分母</th><th scope="col">定义</th></tr></thead>
          <tbody>{(Object.keys(metricNames) as MetricKey[]).map(key => {
            const ratio = data[key]
            return <tr key={key}><th scope="row">{metricNames[key]}</th><td className="support-number">{ratio.denominator === 0 || ratio.value === null ? '—' : `${(ratio.value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 })}%`}</td><td className="support-number">{ratio.numerator.toLocaleString('zh-CN')}</td><td className="support-number">{ratio.denominator.toLocaleString('zh-CN')}</td><td>{data.definitions[key]}</td></tr>
          })}</tbody>
        </table></div>
        <div className="admin-table-wrap"><table className="support-route-table"><caption>意图分流 · 按对话轮次计数</caption><thead><tr><th scope="col">意图</th><th scope="col" className="support-number">轮次</th></tr></thead><tbody>{routes.length ? routes.map(([intent, count]) => <tr key={intent}><th scope="row">{intent}</th><td className="support-number">{count.toLocaleString('zh-CN')}</td></tr>) : <tr><td colSpan={2}>暂无分流样本 —</td></tr>}</tbody></table></div>
      </>}
    </QueryState>
  </section>
}
