import { useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { User } from '../api/auth'
import type { Order } from '../api/shop'
import { adminApi, type AdminProduct, type ProductFilters, type ProductInput, type OrderStatus } from '../api/admin'
import SupportWorkspace from './SupportWorkspace'
import './admin.css'

type Tab = 'products' | 'orders' | 'support'
type Write = { pending: boolean; run: (task: () => Promise<unknown>, message: string, done?: () => void) => Promise<void> }
const statuses: Array<{ value: OrderStatus | ''; label: string }> = [
  { value: '', label: '全部订单' }, { value: 'pending_payment', label: '待支付' },
  { value: 'pending_shipment', label: '待发货' }, { value: 'pending_receipt', label: '待收货' },
  { value: 'completed', label: '已完成' }, { value: 'closed', label: '已关闭' },
]
const emptyFilters: ProductFilters = { q: '', category: '', is_listed: '' }
const money = (value: string) => `¥${Number(value).toFixed(2)}`
const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const tabFromUrl = (): Tab => {
  const tab = new URLSearchParams(window.location.search).get('tab')
  return tab === 'orders' || tab === 'support' ? tab : 'products'
}
function orderStatus(order: Order) {
  return order.status === 'pending_payment' && Date.parse(order.expires_at) <= Date.now()
    ? '已超时，等待关闭' : statuses.find(item => item.value === order.status)?.label ?? order.status
}
function formValues(event: FormEvent<HTMLFormElement>) {
  event.preventDefault()
  return new FormData(event.currentTarget)
}
const text = (data: FormData, name: string) => String(data.get(name) ?? '').trim()

function State({ loading, error, empty, retry, children }: { loading: boolean; error: Error | null; empty?: boolean; retry: () => unknown; children: ReactNode }) {
  if (loading) return <p className="admin-empty" role="status">正在加载…</p>
  if (error) return <div className="admin-empty admin-error" role="alert"><p>{error.message}</p><button onClick={() => retry()}>重新加载</button></div>
  if (empty) return <p className="admin-empty">暂无符合条件的记录</p>
  return <>{children}</>
}
function Pagination({ page, total, size = 20, busy, onPage }: { page: number; total: number; size?: number; busy: boolean; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return <nav className="admin-pagination" aria-label="分页"><span>共 {total} 条</span><button disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>上一页</button><span aria-live="polite">第 {page} / {pages} 页</span><button disabled={busy || page >= pages} onClick={() => onPage(page + 1)}>下一页</button></nav>
}

export function AdminPage({ currentUser, onLogin }: { currentUser: User | null; onLogin: () => void }) {
  return <main className="admin-page">
    <header className="admin-masthead"><a className="admin-brand" href="/">商城 <span>卖家工作台</span></a><nav aria-label="商城导航"><a href="/">商城首页</a><button onClick={onLogin}>{currentUser ? '切换账号' : '登录'}</button></nav></header>
    <div className="admin-intro"><p>商品有序经营 · 每份订单用心送达</p><h1>商家管理</h1></div>
    {!currentUser ? <section className="admin-card admin-empty"><h2>登录管理员账号</h2><p>登录后维护商品、调整库存和处理发货。</p><button className="admin-primary" onClick={onLogin}>登录后继续</button></section>
      : currentUser.role !== 'admin' ? <section className="admin-card admin-empty"><h2>无权限访问</h2><p>当前为买家账号，请使用管理员账号登录。</p><button className="admin-primary" onClick={onLogin}>切换账号</button></section>
        : <AdminWorkspace key={currentUser.id} userId={currentUser.id} />}
  </main>
}

function AdminWorkspace({ userId }: { userId: string }) {
  const client = useQueryClient()
  const [tab, setTab] = useState<Tab>(tabFromUrl)
  const [pending, setPending] = useState(false)
  const lock = useRef(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const pop = () => setTab(tabFromUrl())
    window.addEventListener('popstate', pop)
    return () => window.removeEventListener('popstate', pop)
  }, [])
  const write: Write = { pending, run: async (task, success, done) => {
    if (lock.current) return
    lock.current = true
    setPending(true); setError(''); setMessage('')
    try {
      await task()
      setMessage(success)
      done?.()
    } catch (err) { setError(err instanceof Error ? err.message : '操作失败，请重试。') }
    finally {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['admin', userId] }),
        client.invalidateQueries({ queryKey: ['products'] }),
        client.invalidateQueries({ queryKey: ['product'] }),
        client.invalidateQueries({ queryKey: ['channel-products'] }),
        client.invalidateQueries({ queryKey: ['curated-products'] }),
        client.invalidateQueries({ queryKey: ['orders'] }),
        client.invalidateQueries({ queryKey: ['order'] }),
        client.invalidateQueries({ queryKey: ['cart'] }),
      ])
      lock.current = false; setPending(false)
    }
  } }
  function changeTab(event: MouseEvent<HTMLAnchorElement>, next: Tab) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    if (pending) return
    window.history.pushState(null, '', `${window.location.pathname}?view=admin&tab=${next}`)
    window.dispatchEvent(new PopStateEvent('popstate'))
    setError(''); setMessage('')
  }
  return <>
    <nav className="admin-tabs" aria-label="管理栏目">{(['products', 'orders', 'support'] as const).map(value => <a key={value} href={`?view=admin&tab=${value}`} aria-current={tab === value ? 'page' : undefined} onClick={event => changeTab(event, value)}>{value === 'products' ? '商品与库存' : value === 'orders' ? '订单与发货' : '客服工作台'}</a>)}</nav>
    {error && <p className="admin-notice admin-error" role="alert">{error}</p>}
    {message && <p className="admin-notice" role="status">{message}</p>}
    {tab === 'products' ? <Products userId={userId} write={write} /> : tab === 'orders' ? <Orders userId={userId} write={write} /> : <SupportWorkspace key={userId} userId={userId} />}
  </>
}

function Products({ userId, write }: { userId: string; write: Write }) {
  const [filters, setFilters] = useState<ProductFilters>(emptyFilters)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const [create, setCreate] = useState(false)
  const list = useQuery({ queryKey: ['admin', userId, 'products', filters, page], queryFn: () => adminApi.products(filters, page) })
  if (create) return <section className="admin-card"><div className="admin-section-heading"><h2>新建商品</h2><button disabled={write.pending} onClick={() => setCreate(false)}>返回列表</button></div><p className="admin-muted">新商品库存为 0，创建后可通过库存调整补货。</p><ProductForm write={write} onSaved={() => { setCreate(false); setPage(1) }} /></section>
  if (selected) return <ProductDetail key={selected} id={selected} userId={userId} write={write} back={() => setSelected(null)} />
  return <section className="admin-card">
    <div className="admin-section-heading"><div><h2>商品管理</h2><p className="admin-muted">维护商品信息、上下架与可售库存</p></div><button className="admin-primary" disabled={write.pending} onClick={() => setCreate(true)}>＋ 新建商品</button></div>
    <form className="admin-filters" onSubmit={event => { const data = formValues(event); setFilters({ q: text(data, 'q'), category: text(data, 'category'), is_listed: text(data, 'is_listed') as ProductFilters['is_listed'] }); setPage(1) }}>
      <label>搜索商品<input name="q" placeholder="输入商品名称" maxLength={120} defaultValue={filters.q} /></label><label>分类<input name="category" placeholder="全部分类" maxLength={80} defaultValue={filters.category} /></label><label>上架状态<select name="is_listed" defaultValue={filters.is_listed}><option value="">全部</option><option value="true">已上架</option><option value="false">已下架</option></select></label><button className="admin-primary" type="submit">搜索</button>
    </form>
    <State loading={list.isPending} error={list.error} empty={list.data?.items.length === 0} retry={list.refetch}>
      <div className="admin-table-wrap"><table><thead><tr><th>商品</th><th>分类</th><th>售价</th><th>可售库存</th><th>状态</th><th>操作</th></tr></thead><tbody>{list.data?.items.map(product => <tr key={product.id}><td><div className="admin-product"><img src={product.image_url} alt="" loading="lazy" /><strong>{product.name}</strong></div></td><td>{product.category}</td><td className="admin-price">{money(product.price)}</td><td>{product.stock}</td><td><span className={`admin-badge ${product.is_listed ? 'is-listed' : ''}`}>{product.is_listed ? '已上架' : '已下架'}</span></td><td><div className="admin-row-actions"><button disabled={write.pending} onClick={() => setSelected(product.id)}>编辑 / 库存</button><button disabled={write.pending} onClick={() => void write.run(() => adminApi.updateProduct(product.id, { is_listed: !product.is_listed }), product.is_listed ? '商品已下架。' : '商品已上架。')}>{product.is_listed ? '下架' : '上架'}</button></div></td></tr>)}</tbody></table></div>
    </State>
    {list.data && <Pagination page={page} total={list.data.total} size={list.data.page_size} busy={list.isFetching || write.pending} onPage={setPage} />}
  </section>
}

function ProductForm({ product, write, onSaved }: { product?: AdminProduct; write: Write; onSaved?: () => void }) {
  const [validation, setValidation] = useState('')
  function submit(event: FormEvent<HTMLFormElement>) {
    const data = formValues(event)
    const price = text(data, 'price')
    if (!/^\d+(\.\d{1,2})?$/.test(price) || Number(price) <= 0) { setValidation('价格必须大于零，最多保留两位小数。'); return }
    const input: ProductInput = { name: text(data, 'name'), category: text(data, 'category'), description: text(data, 'description'), image_url: text(data, 'image_url'), price, is_listed: data.get('is_listed') === 'on' }
    if (!input.name || !input.category || !input.image_url) { setValidation('商品名称、分类和图片地址不能为空。'); return }
    setValidation('')
    void write.run(() => product ? adminApi.updateProduct(product.id, input) : adminApi.createProduct(input), product ? '商品信息已保存。' : '商品已创建，初始库存为 0。', onSaved)
  }
  return <form onSubmit={submit} className="admin-form"><fieldset disabled={write.pending}>
    <div className="admin-form-grid"><label>商品名称<input required name="name" maxLength={160} defaultValue={product?.name} /></label><label>分类<input required name="category" maxLength={80} defaultValue={product?.category} /></label><label>价格（元）<input required name="price" type="number" min="0.01" step="0.01" defaultValue={product?.price} /></label><label>商品图片地址<input required name="image_url" maxLength={500} defaultValue={product?.image_url} placeholder="图片 URL 或站内路径" /></label></div>
    <label>商品描述<textarea name="description" maxLength={10000} rows={4} defaultValue={product?.description} /></label><label className="admin-check"><input type="checkbox" name="is_listed" defaultChecked={product?.is_listed ?? false} />上架销售</label>
    {validation && <p className="admin-error" role="alert">{validation}</p>}<button className="admin-primary" type="submit">{write.pending ? '正在提交…' : product ? '保存商品' : '创建商品（库存 0）'}</button>
  </fieldset></form>
}

function ProductDetail({ id, userId, write, back }: { id: string; userId: string; write: Write; back: () => void }) {
  const [page, setPage] = useState(1)
  const [validation, setValidation] = useState('')
  const product = useQuery({ queryKey: ['admin', userId, 'product', id], queryFn: () => adminApi.product(id) })
  const audit = useQuery({ queryKey: ['admin', userId, 'adjustments', id, page], queryFn: () => adminApi.adjustments(id, page) })
  function adjust(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget
    const data = formValues(event)
    const delta = Number(text(data, 'delta')), reason = text(data, 'reason')
    if (!Number.isInteger(delta) || delta === 0 || Math.abs(delta) > 2147483647 || !reason) { setValidation('请输入非零整数调整量及调整原因。'); return }
    if (product.data && product.data.stock + delta < 0) { setValidation('调整后的库存不能低于零。'); return }
    setValidation('')
    void write.run(() => adminApi.adjustInventory(id, delta, reason), '库存已调整，审计记录已更新。', () => { form.reset(); setPage(1) })
  }
  return <div className="admin-stack"><section className="admin-card"><div className="admin-section-heading"><h2>编辑商品</h2><button disabled={write.pending} onClick={back}>返回列表</button></div><State loading={product.isPending} error={product.error} retry={product.refetch}>{product.data && <><p className="admin-muted">商品编号：{id} · 创建于 {time(product.data.created_at)}</p><ProductForm product={product.data} write={write} /></>}</State></section>
    <section className="admin-card"><h2>库存调整</h2><p className="admin-muted">当前可售库存：<strong>{product.data?.stock ?? '—'}</strong>。正数补货，负数扣减；每次调整均记录原因。</p><form className="admin-filters" onSubmit={adjust}><fieldset className="admin-inline-fields" disabled={write.pending || !product.data}><label>调整数量<input required name="delta" type="number" step="1" min={-2147483647} max={2147483647} placeholder="例如 10 或 -2" /></label><label className="admin-grow">调整原因<input required name="reason" maxLength={500} placeholder="例如：仓库补货" /></label><button className="admin-primary" type="submit">{write.pending ? '正在提交…' : '确认调整'}</button></fieldset></form>{validation && <p className="admin-error" role="alert">{validation}</p>}</section>
    <section className="admin-card"><h2>库存审计记录</h2><State loading={audit.isPending} error={audit.error} empty={audit.data?.items.length === 0} retry={audit.refetch}><div className="admin-table-wrap"><table><thead><tr><th>时间</th><th>调整量</th><th>调整前 → 后</th><th>原因</th><th>操作管理员</th></tr></thead><tbody>{audit.data?.items.map(item => <tr key={item.id}><td>{time(item.created_at)}</td><td>{item.delta > 0 ? '+' : ''}{item.delta}</td><td>{item.before_stock} → {item.after_stock}</td><td>{item.reason}</td><td className="admin-id">{item.admin_id}</td></tr>)}</tbody></table></div></State>{audit.data && <Pagination page={page} total={audit.data.total} size={audit.data.page_size} busy={audit.isFetching || write.pending} onPage={setPage} />}</section>
  </div>
}

function Orders({ userId, write }: { userId: string; write: Write }) {
  const [status, setStatus] = useState<OrderStatus | ''>('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['admin', userId, 'orders', status, page], queryFn: () => adminApi.orders(status, page), enabled: !selected })
  if (selected) return <OrderDetail key={selected} id={selected} userId={userId} write={write} back={() => setSelected(null)} />
  return <section className="admin-card"><h2>订单管理</h2><nav className="admin-status-filters" aria-label="订单状态">{statuses.map(item => <button key={item.value} aria-pressed={status === item.value} onClick={() => { setStatus(item.value); setPage(1) }}>{item.label}</button>)}</nav>
    <State loading={list.isPending} error={list.error} empty={list.data?.items.length === 0} retry={list.refetch}><div className="admin-order-list">{list.data?.items.map(order => <article className="admin-order-card" key={order.id}><div className="admin-section-heading"><span className="admin-id">订单编号：{order.id}</span><span className="admin-badge">{orderStatus(order)}</span></div><p>{order.items.map(item => `${item.name} × ${item.quantity}`).join('；')}</p><div className="admin-section-heading"><div><strong className="admin-price">{money(order.total)}</strong><span className="admin-muted"> · {time(order.created_at)}</span></div><button disabled={write.pending} onClick={() => setSelected(order.id)}>{order.status === 'pending_shipment' ? '查看详情 / 发货' : '查看详情'}</button></div></article>)}</div></State>
    {list.data && <Pagination page={page} total={list.data.total} size={list.data.page_size} busy={list.isFetching || write.pending} onPage={setPage} />}
  </section>
}

function OrderDetail({ id, userId, write, back }: { id: string; userId: string; write: Write; back: () => void }) {
  const detail = useQuery({ queryKey: ['admin', userId, 'order', id], queryFn: () => adminApi.order(id) })
  const [validation, setValidation] = useState('')
  const order = detail.data
  function ship(event: FormEvent<HTMLFormElement>) {
    const data = formValues(event), company = text(data, 'shipping_company'), tracking = text(data, 'tracking_number')
    if (!company || !tracking) { setValidation('请填写物流公司和运单号。'); return }
    if (order?.status !== 'pending_shipment') return
    setValidation('')
    void write.run(() => adminApi.ship(id, company, tracking), '发货成功，订单已进入待收货。')
  }
  const closeReasons: Record<string, string> = { buyer_cancelled: '买家取消订单', payment_timeout: '支付超时' }
  return <section className="admin-card"><div className="admin-section-heading"><h2>订单详情</h2><button disabled={write.pending} onClick={back}>返回列表</button></div><State loading={detail.isPending} error={detail.error} retry={detail.refetch}>{order && <>
    <div className="admin-order-summary"><span className="admin-badge">{orderStatus(order)}</span><p className="admin-id">订单编号：{order.id}</p><strong className="admin-price">订单合计 {money(order.total)}</strong></div>
    <div className="admin-detail-grid"><section><h3>收货信息</h3><p>{order.address.recipient_name} · {order.address.phone}</p><p>{order.address.province}{order.address.city}{order.address.district}{order.address.detail}</p><p className="admin-muted">下单时保存的地址快照</p></section><section><h3>物流信息</h3><p>物流公司：{order.shipping_company || '暂无'}</p><p>运单号码：{order.tracking_number || '暂无'}</p><p>发货时间：{time(order.shipped_at)}</p></section></div>
    <h3>订单商品快照</h3><div className="admin-table-wrap"><table><thead><tr><th>商品</th><th>成交单价</th><th>数量</th><th>小计</th></tr></thead><tbody>{order.items.map((item, index) => <tr key={`${item.product_id}-${index}`}><td><div className="admin-product"><img src={item.image_url} alt="" loading="lazy" /><strong>{item.name}</strong></div></td><td>{money(item.unit_price)}</td><td>{item.quantity}</td><td>{money(item.line_total)}</td></tr>)}</tbody></table></div>
    <dl className="admin-facts">{[['创建时间', order.created_at], ['支付截止', order.expires_at], ['支付时间', order.paid_at], ['完成时间', order.completed_at], ['关闭时间', order.closed_at]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{time(value)}</dd></div>)}{order.close_reason && <div><dt>关闭原因</dt><dd>{closeReasons[order.close_reason] ?? order.close_reason}</dd></div>}</dl>
    {order.status === 'pending_shipment' && <section className="admin-shipment"><h3>填写物流并发货</h3><form onSubmit={ship}><fieldset className="admin-inline-fields" disabled={write.pending}><label>物流公司<input name="shipping_company" required maxLength={100} placeholder="填写物流公司" /></label><label className="admin-grow">运单号码<input name="tracking_number" required maxLength={100} placeholder="填写运单号码" /></label><button className="admin-primary" type="submit">{write.pending ? '正在发货…' : '确认发货'}</button></fieldset></form>{validation && <p className="admin-error" role="alert">{validation}</p>}</section>}
  </>}</State></section>
}
