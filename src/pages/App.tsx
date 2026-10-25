import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, getCsrfToken, type User } from '../api/auth'
import { getCategories, getProduct, getProducts, type ProductQuery } from '../api/products'
import { CommercePage } from './CommercePage'
import { OrdersPage } from './OrdersPage'
import { shopApi } from '../api/shop'
import { ChannelPage, channels } from './ChannelPage'
import { AccountPage } from './AccountPage'
import { InfoPage, notices } from './InfoPage'
import { AdminPage } from './AdminPage'
import './navigation.css'

const categoryOrder = [
  '女装', '男装', '手机', '家电', '美妆', '母婴', '食品', '鞋靴',
  '宠物', '汽车', '图书', '医疗健康', '办公', '工业品', '更多分类',
]

const promos = [
  { title: '生活超市', caption: '生活好物 · 一站购齐', color: 'orange', emoji: '🛍️', channel: 'living' },
  { title: '平价好物', caption: '实用之选 · 明白消费', color: 'pink', emoji: '👟', channel: 'value' },
  { title: '穿搭美妆', caption: '日常穿搭 · 发现风格', color: 'rose', emoji: '✨', channel: 'style' },
  { title: '阅读时光', caption: '一本好书 · 一刻闲暇', color: 'blue', emoji: '☕', channel: 'reading' },
  { title: '数码生活', caption: '工作生活 · 实用好物', color: 'purple', emoji: '🎧', channel: 'digital' },
]

export function App() {
  const queryClient = useQueryClient()
  const [authView, setAuthView] = useState<'login' | 'register' | 'admin' | null>(null)
  const [authError, setAuthError] = useState('')
  const [authMessage, setAuthMessage] = useState('')
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [authLoading, setAuthLoading] = useState(false)
  const [authReturnUrl, setAuthReturnUrl] = useState<string | null>(null)
  const returnParams = new URLSearchParams(window.location.search)
  const customerServiceReturn = returnParams.get('customer-service-return') === '1'
  const customerServiceOrder = returnParams.get('customer-service-order') ?? ''
  const customerServiceReturnUrl = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(customerServiceOrder)
    ? `/customer-service.html?order=${encodeURIComponent(customerServiceOrder)}` : '/customer-service.html'
  const [commerce, setCommerce] = useState(() => new URLSearchParams(window.location.search).get('view') === 'cart')
  const [detailId, setDetailId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('product'))
  const [detailMessage, setDetailMessage] = useState('')
  const productDetail = useQuery({ queryKey: ['product', detailId], queryFn: () => getProduct(detailId!), enabled: detailId !== null })
  const [searchParams, setSearchParams] = useState(() => new URLSearchParams(window.location.search))
  const [searchInput, setSearchInput] = useState(() => searchParams.get('q') ?? '')
  useEffect(() => { setSearchInput(searchParams.get('q') ?? '') }, [searchParams])
  const requestedSort = searchParams.get('sort')
  const requestedPage = Number(searchParams.get('page') ?? 1)
  const catalogCategories = useQuery({ queryKey: ['categories'], queryFn: getCategories })
  const categories = [...(catalogCategories.data ?? [])].sort((left, right) => {
    const leftIndex = categoryOrder.indexOf(left)
    const rightIndex = categoryOrder.indexOf(right)
    return (leftIndex === -1 ? categoryOrder.length : leftIndex) - (rightIndex === -1 ? categoryOrder.length : rightIndex) || left.localeCompare(right)
  })
  const requestedCategory = searchParams.get('category') ?? undefined
  const category = catalogCategories.data && requestedCategory && !catalogCategories.data.includes(requestedCategory) ? undefined : requestedCategory
  const productQuery: ProductQuery = { q: searchParams.get('q') ?? '', category, sort: requestedSort === 'price_asc' || requestedSort === 'price_desc' ? requestedSort : 'popular', page: Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1, page_size: 20 }
  const products = useQuery({ queryKey: ['products', productQuery], queryFn: () => getProducts(productQuery) })
  const isFiltered = Boolean(productQuery.q || category)
  const curatedCategory = category ?? (isFiltered ? products.data?.items[0]?.category : undefined)
  const curatedProducts = useQuery({ queryKey: ['curated-products', curatedCategory ?? 'all'], queryFn: () => getProducts({ category: curatedCategory, sort: 'popular', page_size: 4 }) })

  const adminAccess = useQuery({ queryKey: ['admin-access'], queryFn: authApi.adminAccess, enabled: authView === 'admin' && currentUser?.role === 'admin' })

  useEffect(() => {
    const syncQuery = () => {
      const params = new URLSearchParams(window.location.search)
      setSearchParams(params)
      setDetailId(params.get('product'))
      setCommerce(params.get('view') === 'cart')
    }
    window.addEventListener('popstate', syncQuery)
    return () => window.removeEventListener('popstate', syncQuery)
  }, [])

  function updateCatalog(values: Record<string, string>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(values)) value ? next.set(key, value) : next.delete(key)
    if ('q' in values || 'category' in values || 'sort' in values) next.delete('page')
    window.history.pushState(null, '', `${window.location.pathname}${next.size ? `?${next}` : ''}`)
    setSearchParams(next)
  }

  useEffect(() => {
    if (customerServiceReturn) {
      setAuthReturnUrl(customerServiceReturnUrl)
      setAuthView('login')
    }
    void authApi.me().then(user => {
      setCurrentUser(user)
      if (customerServiceReturn) window.location.assign(customerServiceReturnUrl)
    }).catch(() => setCurrentUser(null))
    const expired = () => {
      setCurrentUser(null)
      setAuthMessage('登录状态已失效，请重新登录。')
      setAuthView('login')
      queryClient.clear()
    }
    window.addEventListener('auth:expired', expired)
    return () => window.removeEventListener('auth:expired', expired)
  }, [queryClient, customerServiceReturn, customerServiceReturnUrl])

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAuthError('')
    setAuthMessage('')
    setAuthLoading(true)
    const form = new FormData(event.currentTarget)
    const email = String(form.get('email') ?? '')
    const password = String(form.get('password') ?? '')
    try {
      await getCsrfToken()
      if (authView === 'register') {
        const result = await authApi.register(email, password)
        setAuthMessage(result.message)
        setAuthView('login')
      } else {
        if (currentUser) { await authApi.logout(); queryClient.clear(); setCurrentUser(null) }
        const user = await authApi.login(email, password)
        queryClient.clear()
        setCurrentUser(user)
        setAuthMessage(`欢迎回来，${user.email}`)
        setAuthView(null)
        if (customerServiceReturn) {
          window.location.assign(customerServiceReturnUrl)
          return
        }
        if (authReturnUrl) {
          window.history.pushState(null, '', authReturnUrl)
          window.dispatchEvent(new PopStateEvent('popstate'))
          setAuthReturnUrl(null)
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '操作失败，请重试。'
      if (message.includes('CSRF')) {
        setAuthError('安全令牌已过期，请重新获取后再次提交。表单没有自动重试。')
        try { await getCsrfToken() } catch { /* Keep the original actionable error. */ }
      } else {
        setAuthError(message)
      }
    } finally {
      setAuthLoading(false)
    }
  }

  async function signOut() {
    setAuthError('')
    try {
      await authApi.logout()
      setCurrentUser(null)
      setAuthView(null)
      queryClient.clear()
      setAuthMessage('已安全退出。')
      await getCsrfToken()
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '退出失败，请重试。')
    }
  }

  const view = searchParams.get('view')
  const loginFromPage = () => {
    setAuthReturnUrl(window.location.pathname + window.location.search)
    window.history.pushState(null, '', '/')
    setSearchParams(new URLSearchParams())
    setCommerce(false)
    setDetailId(null)
    setAuthError('')
    setAuthView('login')
  }
  if (view === 'channel') return <ChannelPage />
  if (view === 'account' || view === 'addresses') return <AccountPage currentUser={currentUser} onLogin={loginFromPage} addressesOnly={view === 'addresses'} />
  if (view === 'admin') return <AdminPage currentUser={currentUser} onLogin={loginFromPage} />
  if (view && ['help', 'notices', 'directory', 'mobile'].includes(view)) return <InfoPage view={view} categories={categories} />
  if (searchParams.get('view') === 'orders' || searchParams.has('order')) return <OrdersPage currentUser={currentUser} initialOrderId={searchParams.get('order')} onLogin={() => { window.history.pushState(null, '', '/'); setSearchParams(new URLSearchParams()); setCommerce(false); setAuthView('login') }} />
  if (commerce) return <CommercePage currentUser={currentUser} onLogin={() => { setCommerce(false); setAuthView('login'); setAuthError('登录后即可加入购物车。') }} initialOrderId={new URLSearchParams(window.location.search).get('order')} />
  if (detailId) return <main className="product-detail-shell"><nav className="product-breadcrumb"><a href="/" onClick={event => { event.preventDefault(); setDetailId(null); window.history.pushState(null, '', '/') }}>首页</a><span>/</span><span>{productDetail.data?.category ?? '商品'}</span><span>/</span><span>商品详情</span></nav><section className="product-detail-page">{productDetail.isPending && <p role="status">正在加载商品详情…</p>}{productDetail.isError && <p role="alert">{productDetail.error.message}</p>}{productDetail.data && <><img className="product-detail-image" src={productDetail.data.image_url} alt={productDetail.data.name}/><div className="product-detail-info"><small className="product-detail-category">{productDetail.data.category}</small><h1>{productDetail.data.name}</h1><p className="product-detail-description">{productDetail.data.description}</p><strong className="product-detail-price">¥{productDetail.data.price}</strong><div className="product-detail-option"><b>库存</b><span>可售 {productDetail.data.stock} 件</span></div>{detailMessage && <p role="status" className="product-detail-message">{detailMessage}</p>}<div className="product-detail-actions"><button className="product-add-button" onClick={async () => { if (!currentUser) { setDetailId(null); window.history.pushState(null, '', '/'); setAuthView('login'); setAuthError('登录后即可加入购物车。'); return } if (currentUser.role !== 'buyer') { setDetailMessage('管理员账号不能使用买家购物车，请切换买家账号。'); return } try { await shopApi.add(productDetail.data!.id, 1); setDetailMessage('已加入购物车。') } catch (error) { const message = error instanceof Error ? error.message : '加入购物车失败'; setDetailMessage(message.includes('CSRF') || message.includes('来源校验') ? '安全验证已过期，请再次点击“加入购物车”重试。' : message) } }}>加入购物车</button><button className="product-view-cart-button" onClick={() => { window.history.pushState(null, '', '?view=cart'); window.dispatchEvent(new PopStateEvent('popstate')) }}>查看购物车</button></div></div></>}</section></main>

  return (
    <>
      <div className="topbar">
        <div className="top-inner">
          <div className="top-left"><span>中国大陆⌄</span>{currentUser ? <><span>你好，{currentUser.email}</span><button className="text-button" onClick={() => void signOut()}>退出</button></> : <><button className="text-button highlighted" onClick={() => { setAuthView('login'); setAuthError('') }}>亲，请登录</button><button className="text-button" onClick={() => { setAuthView('register'); setAuthError('') }}>免费注册</button></>}<a href="?view=mobile">手机逛淘宝</a></div>
          <div className="top-right"><a href="?view=account">我的淘宝⌄</a><a href="/customer-service.html">♧ 联系客服</a><a href="?view=addresses">收货地址</a><a href="?view=directory#categories">商品分类⌄</a><button className="text-button" onClick={() => currentUser?.role === 'admin' ? window.location.assign('?view=admin') : setAuthView('admin')}>管理后台</button><a href="?view=help">客服中心⌄</a><a href="?view=directory">☰ 网站导航⌄</a></div>
        </div>
      </div>

      <header className="header">
        <a className="logo" href="/" aria-label="淘宝首页">淘宝<small>Taobao.com</small></a>
        <div className="search-area">
          <form className="search" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); updateCatalog({ q: String(form.get('q') ?? '') }) }}>
            <select aria-label="搜索类别"><option>宝贝</option></select>
            <input name="q" value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="搜索你想要的商品" aria-label="搜索你想要的商品" />
            <button type="submit">搜索</button>
          </form>
          <div className="hotwords">{['手机', '连衣裙', '运动鞋', '笔记本', '零食', '家居', '洗发水', '行李箱', '口红'].map(word => <button key={word} onClick={() => updateCatalog({ q: word, category: '' })}>{word}</button>)}</div>
        </div>
        <a className="cart-button" href="/customer-service.html" style={{ textDecoration: 'none' }}>☏　联系客服 <b>咨询</b></a>
      </header>

      <nav className="main-nav" aria-label="主要导航">{channels.map(channel => <a key={channel.id} href={`?view=channel&channel=${channel.id}`}>{channel.title}</a>)}<a href="?view=notices">商城公告</a><a href="?view=directory">更多⌄</a></nav>
      <nav className="mobile-shortcuts" aria-label="我的商城"><a href="?view=account">我的淘宝</a><a href="?view=orders">我的订单</a><a href="?view=cart">购物车</a><a href="?view=directory">分类导航</a><a href="?view=help">帮助</a></nav>

      <main className={`page-grid${isFiltered ? ' search-results-page' : ''}`}>
        <aside className="category-panel">
          <div className="category-title">☷　全部商品分类</div>
          <button className={`category${!category ? ' selected' : ''}`} aria-pressed={!category} onClick={() => updateCatalog({ category: '' })}><span>全部商品</span><span>›</span></button>
          {categories.map((item) => <button className={`category${category === item ? ' selected' : ''}`} aria-pressed={category === item} key={item} onClick={() => updateCatalog({ category: item })}><span>{item}</span><span>›</span></button>)}
        </aside>

        <section className="main-content">
          {!isFiltered && <><section className="hero">
            <div className="hero-art" aria-hidden="true"><div className="plant plant-one" /><div className="sofa"><span /><span /><span /></div><div className="table"><i /><i /></div><div className="lamp" /></div>
            <div className="hero-copy"><h1>家装焕新季</h1><p>品质家居 · 美好生活</p><a className="hero-cta" href="?view=channel&channel=home">逛逛家居　›</a></div>
            <div className="hero-dots"><i /><i /><i /><i /><i /></div>
          </section>

          <section className="promo-grid" aria-label="活动精选">
            {promos.map((promo) => <a href={`?view=channel&channel=${promo.channel}`} className={`promo-card ${promo.color}`} key={promo.title}><div><h2>{promo.title}</h2><p>{promo.caption}</p></div><span className="promo-emoji" aria-hidden="true">{promo.emoji}</span></a>)}
          </section>

          </>}
          <section className="recommendation" id="products" aria-label="商品目录">
            <div className="catalog-summary"><div><span className="catalog-eyebrow">TAOBAO · 发现好物</span><h2>{isFiltered ? `${productQuery.q ? `“${productQuery.q}” ` : ''}搜索结果` : '为你精选'}{products.data && <span className="result-count">共 {products.data.total} 件商品</span>}</h2><p>{isFiltered ? '根据你的搜索与分类，为你找到这些好物' : '真实商品图片，发现适合日常生活的好物'}</p></div></div>
            {isFiltered && <div className="active-filters" aria-label="当前筛选"><span>当前筛选</span>{productQuery.q && <span className="filter-chip">关键词：{productQuery.q}<button aria-label="移除关键词" onClick={() => updateCatalog({ q: '' })}>×</button></span>}{category && <span className="filter-chip">分类：{category}<button aria-label="移除分类" onClick={() => updateCatalog({ category: '' })}>×</button></span>}</div>}
            <div className="section-heading"><label>分类 <select aria-label="商品分类" value={productQuery.category ?? ''} onChange={event => updateCatalog({ category: event.target.value })}><option value="">全部分类</option>{categories.map(category => <option key={category}>{category}</option>)}</select></label><label>排序 <select aria-label="排序方式" value={productQuery.sort} onChange={event => updateCatalog({ sort: event.target.value })}><option value="popular">综合</option><option value="price_asc">价格升序</option><option value="price_desc">价格降序</option></select></label>{(isFiltered || productQuery.sort !== 'popular') && <button className="clear-filters" onClick={() => { setSearchInput(''); updateCatalog({ category: '', q: '', sort: '' }) }}>清除筛选</button>}</div>
            {products.isPending && <div className="state-card" role="status">正在从商品目录加载精选好物…</div>}
            {products.isError && <div className="state-card error" role="alert">暂时无法加载商品：{products.error.message}</div>}
            {products.data && products.data.items.length === 0 && <div className="state-card">没有找到匹配的商品，试试其他关键词或分类。</div>}
            {products.data && products.data.items.length > 0 && <><div className="product-grid">{products.data.items.map((product) => <article className="product-card" key={product.id}><a className="product-card-link" href={`?product=${product.id}`} onClick={event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); setDetailMessage(''); setDetailId(product.id); window.history.pushState(null, '', `?product=${product.id}`) }}><div className="product-image-wrap"><img className="product-image" src={product.image_url} alt={product.name} /><span className="image-badge">精选</span></div><div className="product-details"><div className="product-category">{product.category}</div><h3>{product.name}</h3><p className="product-description">{product.description}</p><div className="product-meta"><span className="price"><small>¥</small>{product.price}</span><span className="stock">库存 {product.stock}</span></div></div></a></article>)}</div><div className="catalog-pagination"><span>共 {products.data.total} 件商品 · 第 {products.data.page} 页</span><button disabled={products.data.page <= 1} onClick={() => updateCatalog({ page: String(products.data!.page - 1) })}>上一页</button><button disabled={products.data.page * products.data.page_size >= products.data.total} onClick={() => updateCatalog({ page: String(products.data!.page + 1) })}>下一页</button></div></>}
          </section>
        </section>

        <aside className="right-rail">
          <section className="account-card"><div className="greeting"><div className="avatar">🐻</div><div><strong>{currentUser ? `Hi! ${currentUser.email}` : 'Hi! 你好'}</strong><span>{currentUser ? (currentUser.role === 'admin' ? '管理员账号已登录' : '买家账号已登录') : '登录淘宝，享受更多精彩'}</span></div></div>{currentUser ? <div className="account-actions"><button onClick={() => void signOut()}>退出登录</button>{currentUser.role === 'admin' && <button onClick={() => setAuthView('admin')}>管理后台</button>}</div> : <div className="account-actions"><button onClick={() => setAuthView('login')}>登录</button><button onClick={() => setAuthView('register')}>注册</button></div>}<div className="quick-links"><a href="?view=orders"><i>▤</i>我的订单</a><a href="?view=orders&status=pending_payment"><i>♧</i>待付款</a><a href="?view=orders&status=pending_shipment"><i>▣</i>待发货</a><a href="?view=orders&status=pending_receipt"><i>▱</i>待收货</a><a href="?view=help"><i>◯</i>售后服务</a></div></section>
          <section className="notice-card"><div className="notice-heading"><h2>商城公告</h2><a href="?view=notices">更多 ›</a></div>{notices.map(notice => <p key={notice.id}><a href={`?view=notices&notice=${notice.id}`}><b>公告</b> {notice.title}</a></p>)}</section>
          <section className="ranking-card"><div className="curated-heading"><h2>精选推荐</h2><span>发现更多好物</span></div><p className="curated-caption">{category ? `${category}分类 · 在售商品` : '逛逛商品目录里的日常好物'}</p>{curatedProducts.isPending && <p role="status">正在加载推荐…</p>}{curatedProducts.isError && <p role="alert">推荐暂时无法加载</p>}<div className="curated-list">{curatedProducts.data?.items.map(product => <a className="curated-product" key={product.id} href={`?product=${product.id}`} onClick={event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); setDetailMessage(''); setDetailId(product.id); window.history.pushState(null, '', `?product=${product.id}`) }}><img src={product.image_url} alt={product.name} loading="lazy"/><div><small>{product.category}</small><strong>{product.name}</strong><span>¥{product.price}</span></div><span className="curated-arrow" aria-hidden="true">›</span></a>)}</div></section>
        </aside>
      </main>
      {authView && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) { setAuthView(null); setAuthError('') } }}><section className="auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title"><button className="dialog-close" aria-label="关闭" onClick={() => setAuthView(null)}>×</button>{authView === 'admin' ? <><h2 id="auth-title">管理后台访问</h2>{!currentUser && <p role="status">请先登录管理员账号。</p>}{currentUser?.role === 'buyer' && <p className="error-message" role="alert">无权限：当前账号不是管理员。</p>}{currentUser?.role === 'admin' && <>{adminAccess.isPending && <p>正在验证管理员权限…</p>}{adminAccess.isError && <p className="error-message" role="alert">{adminAccess.error.message}</p>}{adminAccess.data && <div className="admin-success"><strong>管理员访问已授权</strong><span>当前账号：{adminAccess.data.email}</span><span>当前角色：管理员</span><a href="?view=admin">进入商品与订单管理</a></div>}</>}</> : <><h2 id="auth-title">{authView === 'login' ? '登录淘宝' : '创建买家账号'}</h2><p className="demo-warning">{authError.includes('登录后即可加入购物车') ? '登录后即可加入购物车。' : '仅用于作品演示，请使用虚构邮箱和演示专用密码，不要使用真实账号的密码。'}</p>{authMessage && <p className="success-message" role="status">{authMessage}</p>}{authError && !authError.includes('登录后即可加入购物车') && <p className="error-message" role="alert">{authError}</p>}<form className="auth-form" onSubmit={(event) => void submitAuth(event)}><label>邮箱<input type="email" name="email" autoComplete="email" required maxLength={320} /></label><label>密码<input type="password" name="password" autoComplete={authView === 'login' ? 'current-password' : 'new-password'} required minLength={12} maxLength={128} /></label><button type="submit" disabled={authLoading}>{authLoading ? '请稍候…' : authView === 'login' ? '登录' : '注册'}</button></form><button className="text-button auth-switch" onClick={() => { setAuthError(''); setAuthMessage(''); setAuthView(authView === 'login' ? 'register' : 'login') }}>{authView === 'login' ? '没有账号？立即注册' : '已有账号？返回登录'}</button></>}</section></div>}
      {authMessage && !authView && <div className="toast" role="status">{authMessage}<button aria-label="关闭提示" onClick={() => setAuthMessage('')}>×</button></div>}
      <footer>精选好物，认真生活 <span>淘宝风格电商作品集 · 单商家商城演示</span></footer>
    </>
  )
}
