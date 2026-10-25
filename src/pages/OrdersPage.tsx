import { useEffect, useState, type MouseEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { shopApi, type Order } from '../api/shop'
import './orders.css'

type OrdersPageProps = {
  currentUser: { id: string; role: string } | null
  onLogin: () => void
  initialOrderId?: string | null
}

type OrderAction = 'pay' | 'cancel' | 'confirmReceipt'
type ActionRequest = { action: OrderAction; orderId: string; userId: string }

const statuses = [
  { value: '', label: '全部订单' },
  { value: 'pending_payment', label: '待支付' },
  { value: 'pending_shipment', label: '待发货' },
  { value: 'pending_receipt', label: '待收货' },
  { value: 'completed', label: '已完成' },
  { value: 'closed', label: '已关闭' },
]
const successMessages: Record<OrderAction, string> = {
  pay: '模拟支付成功，订单已进入待发货。',
  cancel: '订单已取消。',
  confirmReceipt: '确认收货成功，订单已完成。',
}
const closeReasons: Record<string, string> = {
  buyer_cancelled: '买家取消订单',
  payment_timeout: '超时未支付，订单自动关闭',
}

function formatTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function money(value: string) {
  return `¥${Number(value).toFixed(2)}`
}

function statusLabel(order: Order) {
  if (order.status === 'pending_payment' && Date.parse(order.expires_at) <= Date.now()) return '已超时，等待关闭'
  return statuses.find(status => status.value === order.status)?.label ?? order.status
}

function readOrderFilters() {
  const params = new URLSearchParams(window.location.search)
  const requestedStatus = params.get('status') ?? ''
  const requestedPage = Number(params.get('page') ?? 1)
  return {
    status: statuses.some(item => item.value === requestedStatus) ? requestedStatus : '',
    page: Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
  }
}

function orderUrl(id?: string | null, logistics = false) {
  return `?view=orders${id ? `&order=${encodeURIComponent(id)}` : ''}${logistics ? '&logistics=1' : ''}`
}

function maskedPhone(phone: string) {
  return phone.length >= 7 ? `${phone.slice(0, 3)}****${phone.slice(-4)}` : '****'
}

function navigate(event: MouseEvent<HTMLAnchorElement>, search: string) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  window.history.pushState(null, '', `${window.location.pathname}${search}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function OrderItems({ order, compact = false }: { order: Order; compact?: boolean }) {
  const items = compact ? order.items.slice(0, 2) : order.items
  return <div className="orders-items">
    {items.map((item, index) => <div className="orders-item" key={`${item.product_id}-${index}`}>
      {item.image_url ? <img src={item.image_url} alt="" loading="lazy" /> : <div className="orders-image-placeholder" aria-hidden="true">商品</div>}
      <div className="orders-item-info"><strong>{item.name}</strong><span>{money(item.unit_price)} × {item.quantity}</span></div>
      <strong className="orders-line-total">{money(item.line_total)}</strong>
    </div>)}
    {compact && order.items.length > 2 && <p className="orders-more">另有 {order.items.length - 2} 种商品，查看详情了解全部商品</p>}
  </div>
}

export function OrdersPage({ currentUser, onLogin, initialOrderId }: OrdersPageProps) {
  const queryClient = useQueryClient()
  const [activeOrderId, setActiveOrderId] = useState<string | null>(initialOrderId ?? null)
  const [showLogistics, setShowLogistics] = useState(() => new URLSearchParams(window.location.search).get('logistics') === '1')
  const [copyMessage, setCopyMessage] = useState('')
  const [status, setStatus] = useState(() => readOrderFilters().status)
  const [page, setPage] = useState(() => readOrderFilters().page)
  const userId = currentUser?.id
  const isBuyer = currentUser?.role === 'buyer'

  useEffect(() => {
    setActiveOrderId(initialOrderId ?? null)
    setShowLogistics(new URLSearchParams(window.location.search).get('logistics') === '1')
  }, [initialOrderId])
  useEffect(() => { setCopyMessage('') }, [activeOrderId, showLogistics, userId])
  useEffect(() => {
    function onPopState() {
      const params = new URLSearchParams(window.location.search)
      if (params.get('view') === 'orders' || params.has('order')) {
        setActiveOrderId(params.get('order') || null)
        setShowLogistics(params.get('logistics') === '1')
        const filters = readOrderFilters()
        setStatus(filters.status)
        setPage(filters.page)
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  useEffect(() => { const filters = readOrderFilters(); setStatus(filters.status); setPage(filters.page) }, [userId])

  function updateFilters(nextStatus: string, nextPage = 1) {
    const params = new URLSearchParams({ view: 'orders' })
    if (nextStatus) params.set('status', nextStatus)
    if (nextPage > 1) params.set('page', String(nextPage))
    window.history.pushState(null, '', `?${params}`)
    setStatus(nextStatus)
    setPage(nextPage)
    resetAction()
  }

  const orders = useQuery({
    queryKey: ['orders', userId, status, page],
    queryFn: () => shopApi.orders(status || undefined, page),
    enabled: isBuyer && !activeOrderId,
    refetchInterval: query => query.state.data?.items.some(order => order.status === 'pending_payment') ? 30_000 : false,
  })
  const detail = useQuery({
    queryKey: ['order', userId, activeOrderId],
    queryFn: () => shopApi.order(activeOrderId!),
    enabled: isBuyer && !!activeOrderId,
    refetchInterval: query => query.state.data?.status === 'pending_payment' ? 30_000 : false,
  })

  const action = useMutation({
    mutationFn: ({ action: name, orderId }: ActionRequest) => shopApi[name](orderId),
    onSuccess: async (order, request) => {
      queryClient.setQueryData(['order', request.userId, request.orderId], order)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['orders', request.userId] }),
        queryClient.invalidateQueries({ queryKey: ['order', request.userId] }),
        queryClient.invalidateQueries({ queryKey: ['products'] }),
        queryClient.invalidateQueries({ queryKey: ['cart'] }),
      ])
    },
    onError: async (_error, request) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['orders', request.userId] }),
        queryClient.invalidateQueries({ queryKey: ['order', request.userId] }),
      ])
    },
  })
  const { reset: resetAction } = action
  useEffect(() => { resetAction() }, [activeOrderId, userId, resetAction])

  function runAction(name: OrderAction, order: Order) {
    if (!isBuyer || !userId || action.isPending) return
    action.mutate({ action: name, orderId: order.id, userId })
  }

  function actionsFor(order: Order) {
    const pendingHere = action.isPending && action.variables?.orderId === order.id
    const expired = Date.parse(order.expires_at) <= Date.now()
    return <div className="orders-actions">
      {order.status === 'pending_payment' && <>
        <button disabled={action.isPending} onClick={() => runAction('cancel', order)}>{pendingHere && action.variables?.action === 'cancel' ? '正在取消…' : '取消订单'}</button>
        <button className="primary-action" disabled={action.isPending || expired} onClick={() => runAction('pay', order)}>{pendingHere && action.variables?.action === 'pay' ? '正在支付…' : expired ? '支付已超时' : '模拟支付'}</button>
      </>}
      {order.status === 'pending_receipt' && <button className="primary-action" disabled={action.isPending} onClick={() => runAction('confirmReceipt', order)}>{pendingHere ? '正在确认…' : '确认收货'}</button>}
      <a className="orders-detail-link" href={orderUrl(order.id, true)} onClick={event => navigate(event, orderUrl(order.id, true))}>查看物流</a>
      <a className="orders-detail-link" href={`/customer-service.html?order=${encodeURIComponent(order.id)}`}>联系客服</a>
      {!activeOrderId && <a className="orders-detail-link" href={orderUrl(order.id)} onClick={event => navigate(event, orderUrl(order.id))}>查看详情</a>}
    </div>
  }

  const visibleAction = !!action.variables && action.variables.userId === userId && (!activeOrderId || action.variables.orderId === activeOrderId)
  const totalPages = Math.max(1, Math.ceil((orders.data?.total ?? 0) / 20))
  const order = detail.data

  return <main className={`commerce-page orders-page ${showLogistics ? 'orders-logistics-page' : ''}`}>
    <header className="commerce-masthead">
      <a className="commerce-brand" href="/" onClick={event => navigate(event, '')}>商城 <span>{activeOrderId && showLogistics ? '物流详情' : '我的订单'}</span></a>
      <nav className="commerce-mast-actions orders-navigation" aria-label="商城导航">
        <a href="/" onClick={event => navigate(event, '')}>首页</a>
        <a href="?view=cart" onClick={event => navigate(event, '?view=cart')}>购物车</a>
        <button onClick={onLogin}>{currentUser ? '切换账号' : '登录'}</button>
      </nav>
    </header>
    <div className="orders-heading"><div><p className="orders-eyebrow">每一份期待，都有迹可循</p><h1>{activeOrderId && showLogistics ? '物流详情' : '我的订单'}</h1>{activeOrderId && !showLogistics && <h2 className="orders-detail-title">订单详情</h2>}</div>{activeOrderId && <div className="orders-return-links">{showLogistics && <a className="orders-back" href={orderUrl(activeOrderId)} onClick={event => navigate(event, orderUrl(activeOrderId))}>← 返回订单详情</a>}<a className="orders-back" href={orderUrl()} onClick={event => navigate(event, orderUrl())}>{showLogistics ? '我的订单' : '返回订单列表'}</a></div>}</div>

    {!currentUser ? <section className="commerce-card orders-empty"><h2>登录后查看我的订单</h2><p>查看订单进度、完成支付，或确认商品已送达。</p><button className="primary-action" onClick={onLogin}>登录后继续</button></section>
      : !isBuyer ? <section className="commerce-card orders-empty"><h2>请使用买家账号</h2><p>管理员账号无法查看买家订单，请切换买家账号后继续。</p><button className="primary-action" onClick={onLogin}>切换买家账号</button></section>
        : <>
          {visibleAction && action.isError && <p className="commerce-message error" role="alert">{action.error.message}</p>}
          {visibleAction && action.isSuccess && <p className="commerce-message" role="status">{successMessages[action.variables.action]}</p>}
          {activeOrderId ? <>
            {detail.isPending && <p className="commerce-card orders-empty" role="status">正在加载订单详情…</p>}
            {detail.isError && <div className="commerce-card orders-empty" role="alert"><p>{detail.error.message}</p><button onClick={() => void detail.refetch()}>重新加载</button></div>}
            {order && showLogistics ? <div className="orders-logistics">
              <section className="orders-logistics-summary"><div className="orders-logistics-summary-heading"><h2>{order.completed_at ? '已签收' : order.shipped_at ? '商家已发货' : order.status === 'closed' ? '订单已关闭' : '待发货'}</h2><span>订单编号：{order.id}</span></div><OrderItems order={order} compact /><a href={orderUrl(order.id)} onClick={event => navigate(event, orderUrl(order.id))}>查看已买商品与订单详情 →</a></section>
              <section className="commerce-card orders-logistics-tracking"><h2>物流信息</h2><div className="orders-waybill"><strong>{order.shipping_company || '暂无快递公司'}</strong><span>运单号：{order.tracking_number || '暂无运单'}</span>{order.tracking_number && <button onClick={async () => {
                try { await navigator.clipboard.writeText(order.tracking_number!); setCopyMessage('运单号已复制。') }
                catch { setCopyMessage('复制失败，请手动选择并复制运单号。') }
              }}>复制运单号</button>}</div>{copyMessage && <p role="status" className="orders-muted">{copyMessage}</p>}
                {order.shipped_at || order.completed_at ? <ol className="orders-timeline">{order.completed_at && <li><div className="orders-timeline-dot" /><div><strong>已确认收货</strong><p>买家已确认收货，订单完成。</p><time dateTime={order.completed_at}>{formatTime(order.completed_at)}</time></div></li>}{order.shipped_at && <li><div className="orders-timeline-dot" /><div><strong>商家已发货</strong><p>{order.shipping_company ? `商品已通过${order.shipping_company}发出。` : '商家已提交发货信息。'}</p><time dateTime={order.shipped_at}>{formatTime(order.shipped_at)}</time></div></li>}</ol> : <p className="orders-logistics-empty">{order.status === 'closed' ? '订单已关闭，暂无物流记录。' : '商品尚未发货，暂无运单及物流记录。'}</p>}
              </section>
              <section className="commerce-card"><h2>收货信息</h2><p className="orders-recipient">{order.address.recipient_name} · {maskedPhone(order.address.phone)}</p><p className="orders-muted">{order.address.province}{order.address.city}{order.address.district}{order.address.detail}</p></section>
            </div> : order && <>
              <section className="commerce-card orders-status-panel"><div><span className={`orders-status orders-status-${order.status}`}>{statusLabel(order)}</span><p>订单编号：<span className="orders-id">{order.id}</span></p>{order.status === 'pending_payment' && <p>请于 {formatTime(order.expires_at)} 前完成支付。</p>}{order.close_reason && <p>关闭原因：{closeReasons[order.close_reason] ?? order.close_reason}</p>}</div>{actionsFor(order)}</section>
              <div className="orders-detail-grid">
                <section className="commerce-card"><h2>收货信息</h2><p className="orders-recipient">{order.address.recipient_name} · {order.address.phone}</p><p className="orders-muted">{order.address.province}{order.address.city}{order.address.district}{order.address.detail}</p><p className="orders-snapshot-note">收货信息为下单时保存的快照。</p></section>
                <section className="commerce-card"><h2>物流信息</h2>{order.shipping_company || order.tracking_number ? <dl className="orders-facts"><div><dt>物流公司</dt><dd>{order.shipping_company || '—'}</dd></div><div><dt>运单号码</dt><dd>{order.tracking_number || '—'}</dd></div><div><dt>发货时间</dt><dd>{formatTime(order.shipped_at)}</dd></div></dl> : <p className="orders-muted">{order.status === 'closed' ? '订单已关闭，暂无物流信息。' : order.status === 'pending_payment' ? '支付后等待商家发货。' : '暂无物流信息，请耐心等待商家发货。'}</p>}</section>
              </div>
              <section className="commerce-card"><h2>商品信息</h2><p className="orders-snapshot-note">以下商品名称、价格及图片为下单时的快照。</p><OrderItems order={order} /><div className="orders-total"><span>共 {order.items.reduce((sum, item) => sum + item.quantity, 0)} 件商品，订单合计</span><strong>{money(order.total)}</strong></div></section>
              <section className="commerce-card"><h2>订单信息</h2><dl className="orders-facts orders-times"><div><dt>创建时间</dt><dd>{formatTime(order.created_at)}</dd></div><div><dt>支付截止</dt><dd>{formatTime(order.expires_at)}</dd></div>{order.paid_at && <div><dt>支付时间</dt><dd>{formatTime(order.paid_at)}</dd></div>}{order.shipped_at && <div><dt>发货时间</dt><dd>{formatTime(order.shipped_at)}</dd></div>}{order.completed_at && <div><dt>完成时间</dt><dd>{formatTime(order.completed_at)}</dd></div>}{order.closed_at && <div><dt>关闭时间</dt><dd>{formatTime(order.closed_at)}</dd></div>}{order.close_reason && <div><dt>关闭原因</dt><dd>{closeReasons[order.close_reason] ?? order.close_reason}</dd></div>}</dl></section>
            </>}
          </> : <>
            <nav className="orders-filters" aria-label="筛选订单状态">{statuses.map(item => <button key={item.value} aria-pressed={status === item.value} className={status === item.value ? 'is-active' : ''} onClick={() => updateFilters(item.value)}>{item.label}</button>)}</nav>
            {orders.isPending && <p className="commerce-card orders-empty" role="status">正在加载订单…</p>}
            {orders.isError && <div className="commerce-card orders-empty" role="alert"><p>{orders.error.message}</p><button onClick={() => void orders.refetch()}>重新加载</button></div>}
            {orders.data && <>
              <p className="orders-count">共 {orders.data.total} 笔订单 · 每页 20 条</p>
              {!orders.data.items.length && <section className="commerce-card orders-empty"><h2>{status ? '暂无该状态的订单' : '还没有订单'}</h2><p>去挑选喜欢的商品，开启新的期待。</p><a href="/" onClick={event => navigate(event, '')}>去首页逛逛 →</a></section>}
              <div className="orders-list">{orders.data.items.map(item => <article className="commerce-card orders-order-card" key={item.id}>
                <header className="orders-card-header"><div><time dateTime={item.created_at}>{formatTime(item.created_at)}</time><span className="orders-id">订单编号：{item.id}</span></div><span className={`orders-status orders-status-${item.status}`}>{statusLabel(item)}</span></header>
                <OrderItems order={item} compact />
                <footer className="orders-card-footer"><div className="orders-card-amount"><span>共 {item.items.reduce((sum, product) => sum + product.quantity, 0)} 件商品</span><strong>合计 {money(item.total)}</strong></div>{actionsFor(item)}</footer>
              </article>)}</div>
              <nav className="orders-pagination" aria-label="订单分页"><button disabled={page <= 1 || orders.isFetching} onClick={() => updateFilters(status, page - 1)}>上一页</button><span aria-live="polite">第 {page} / {totalPages} 页</span><button disabled={page >= totalPages || orders.isFetching} onClick={() => updateFilters(status, page + 1)}>下一页</button></nav>
            </>}
          </>}
        </>}
  </main>
}
