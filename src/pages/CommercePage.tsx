import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getProducts } from '../api/products'
import { shopApi, type Address, type Cart } from '../api/shop'

type Buyer = { id: string; role: string } | null

export function CommercePage({ initialOrderId, currentUser, onLogin }: { initialOrderId?: string | null; currentUser: Buyer; onLogin: () => void }) {
  const queryClient = useQueryClient()
  const [view, setView] = useState<'cart' | 'payment'>(initialOrderId ? 'payment' : 'cart')
  const [message, setMessage] = useState('')
  const [messageError, setMessageError] = useState(false)
  const [cartAddError, setCartAddError] = useState('')
  const [activeOrderId] = useState<string | null>(initialOrderId ?? null)
  const [selection, setSelection] = useState<Record<string, boolean>>({})
  const [selectedAddressId, setSelectedAddressId] = useState<string | null>(null)
  const [showAddressForm, setShowAddressForm] = useState(false)
  const [savingAddress, setSavingAddress] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const checkoutKey = useRef<{ addressId: string; key: string } | null>(null)
  const checkoutBusy = useRef(false)
  const products = useQuery({ queryKey: ['products'], queryFn: () => getProducts() })
  const cart = useQuery({ queryKey: ['cart', currentUser?.id], queryFn: shopApi.cart, enabled: currentUser?.role === 'buyer' })
  useEffect(() => { if (cart.data) setSelection(Object.fromEntries(cart.data.items.map(item => [item.product_id, item.selected]))) }, [cart.data])
  const addresses = useQuery({ queryKey: ['addresses', currentUser?.id], queryFn: shopApi.addresses, enabled: currentUser?.role === 'buyer' })
  const defaultAddress = selectedAddressId ? addresses.data?.find(address => address.id === selectedAddressId) : addresses.data?.find(address => address.is_default) ?? addresses.data?.[0]
  const activeOrder = useQuery({ queryKey: ['order', activeOrderId], queryFn: () => shopApi.order(activeOrderId!), enabled: view === 'payment' && activeOrderId !== null })
  const selectedItems = cart.data?.items.filter(item => selection[item.product_id] ?? item.selected) ?? []
  const selectedTotal = selectedItems.reduce((sum, item) => sum + Number(item.unit_price) * item.quantity, 0)
  const invalidate = async () => queryClient.invalidateQueries({ queryKey: ['cart', currentUser?.id] })

  async function openCheckout() {
    setMessageError(false)
    setMessage('')
    try {
      const result = await addresses.refetch({ throwOnError: true })
      setShowAddressForm(!result.data?.length)
      setView('payment')
    } catch (error) {
      setMessageError(true)
      setMessage(error instanceof Error ? error.message : '读取默认收货地址失败。')
    }
  }

  async function checkout() {
    if (!defaultAddress || checkoutBusy.current) return
    checkoutBusy.current = true
    setSubmitting(true)
    if (checkoutKey.current?.addressId !== defaultAddress.id) checkoutKey.current = { addressId: defaultAddress.id, key: crypto.randomUUID() }
    try {
      const order = await shopApi.checkout(defaultAddress.id, checkoutKey.current.key)
      queryClient.setQueryData(['order', currentUser?.id, order.id], order)
      await Promise.all([invalidate(), queryClient.invalidateQueries({ queryKey: ['orders'] })])
      window.history.pushState(null, '', `?view=orders&order=${encodeURIComponent(order.id)}`)
      window.dispatchEvent(new PopStateEvent('popstate'))
    } catch (error) { setMessageError(true); setMessage(error instanceof Error ? error.message : '下单失败') }
    finally { checkoutBusy.current = false; setSubmitting(false) }
  }

  async function saveAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSavingAddress(true)
    try {
      const address = await shopApi.saveAddress({ recipient_name: String(form.get('recipient_name')).trim(), phone: String(form.get('phone')).trim(), province: String(form.get('province')).trim(), city: String(form.get('city')).trim(), district: String(form.get('district')).trim(), detail: String(form.get('detail')).trim(), is_default: form.has('is_default') })
      queryClient.setQueryData<Address[]>(['addresses', currentUser?.id], existing => [...(existing ?? []).filter(item => item.id !== address.id).map(item => address.is_default ? { ...item, is_default: false } : item), address])
      setSelectedAddressId(address.id)
      setShowAddressForm(false)
      setMessageError(false)
      setMessage('收货地址已保存并选中。')
    } catch (error) { setMessageError(true); setMessage(error instanceof Error ? error.message : '保存地址失败') }
    finally { setSavingAddress(false) }
  }

  async function runCartAction(action: () => Promise<Cart | void>) {
    try {
      const updated = await action()
      if (updated) queryClient.setQueryData(['cart', currentUser?.id], updated)
      else await queryClient.invalidateQueries({ queryKey: ['cart', currentUser?.id] })
      setMessageError(false)
      setMessage('购物车已更新。')
    } catch (error) { setMessageError(true); setMessage(error instanceof Error ? error.message : '购物车更新失败') }
  }

  async function payOrder() {
    if (!activeOrderId) return
    try { await shopApi.pay(activeOrderId); await queryClient.invalidateQueries({ queryKey: ['order', activeOrderId] }); setMessageError(false); setMessage('模拟支付成功，订单已进入待发货。') }
    catch (error) { setMessageError(true); setMessage(error instanceof Error ? error.message : '支付未完成') }
  }

  function toggleItem(productId: string, selected: boolean) {
    setSelection(current => ({ ...current, [productId]: selected }))
    void runCartAction(() => shopApi.update(productId, { selected }))
  }

  function removeItem(productId: string) {
    void runCartAction(async () => {
      await shopApi.remove(productId)
      return shopApi.cart()
    })
  }

  return <main className="commerce-page">
    <header className="commerce-masthead"><a href="/" className="commerce-brand">淘宝 <span>{view === 'payment' ? '确认订单' : '购物车'}</span></a><div className="commerce-mast-actions"><a href="?view=orders">我的订单</a><button onClick={() => setView('cart')}>购物车</button><button onClick={onLogin}>{currentUser ? '账号' : '登录'}</button></div></header>
    {message && <p className={`commerce-message ${messageError ? 'error' : ''}`} role={messageError ? 'alert' : 'status'}>{message}</p>}
    {view === 'payment' ? <>
      <div className="commerce-tabs"><button onClick={() => { setView('cart'); setMessage('') }}>← 返回购物车</button><strong>确认订单</strong><span>订单信息</span><span>模拟支付</span></div>
      <div className="commerce-layout checkout-layout-commerce"><section className="commerce-card"><h1>确认订单</h1><h2>选择收货地址</h2>
        {addresses.isFetching && <p role="status">正在加载收货地址…</p>}
        {addresses.data?.map(address => <label className={`address-choice ${defaultAddress?.id === address.id ? 'selected' : ''}`} key={address.id}><input type="radio" name="shipping-address" checked={defaultAddress?.id === address.id} onChange={() => setSelectedAddressId(address.id)}/>{address.recipient_name} · {address.phone} · {address.province}{address.city}{address.district}{address.detail} {address.is_default && <small>默认地址</small>}</label>)}
        {!addresses.isFetching && !addresses.data?.length && <p>还没有收货地址，请填写下方信息。</p>}
        <button onClick={() => setShowAddressForm(true)}>新增收货地址</button>
        {showAddressForm && <form className="address-form" onSubmit={event => void saveAddress(event)}><h3>新增收货地址</h3>{([{ name: 'recipient_name', label: '收货人', max: 80 }, { name: 'phone', label: '手机号码', max: 32 }, { name: 'province', label: '省份', max: 80 }, { name: 'city', label: '城市', max: 80 }, { name: 'district', label: '区县', max: 80 }, { name: 'detail', label: '详细地址', max: 240 }]).map(field => <label key={field.name}>{field.label}<input name={field.name} required maxLength={field.max} minLength={field.name === 'phone' ? 6 : 1} type={field.name === 'phone' ? 'tel' : 'text'}/></label>)}<label><input name="is_default" type="checkbox"/>设为默认地址</label><div><button type="submit" className="primary-action" disabled={savingAddress}>{savingAddress ? '正在保存…' : '保存地址'}</button> <button type="button" disabled={savingAddress} onClick={() => setShowAddressForm(false)}>取消</button></div></form>}
        <h2 className="commerce-section-heading">确认订单信息</h2>{activeOrder.data?.items.map((item, index) => <article className="cart-row checkout-item" key={`${item.name}-${index}`}><div className="cart-info"><b>{item.name}</b><span>¥{item.unit_price} × {item.quantity}</span></div><strong>¥{item.line_total}</strong></article>)}{!activeOrderId && selectedItems.map(item => <article className="cart-row checkout-item" key={item.product_id}><img src={item.image_url} alt=""/><div className="cart-info"><b>{item.name}</b><span>¥{item.unit_price} × {item.quantity}</span></div><strong>¥{(Number(item.unit_price) * item.quantity).toFixed(2)}</strong></article>)}
        {activeOrderId && activeOrder.isPending && <p role="status">正在读取订单…</p>}{activeOrder.isError && <p className="commerce-message error" role="alert">{activeOrder.error.message}</p>}
      {!activeOrder.data && addresses.isError && <p className="commerce-message error" role="alert">{addresses.error.message}</p>}</section><aside className="commerce-summary"><h2>付款详情</h2>{activeOrder.data && <><p>订单编号：<strong>{activeOrder.data.id}</strong></p><p>订单状态：<strong>{activeOrder.data.status === 'pending_payment' ? (Date.parse(activeOrder.data.expires_at) <= Date.now() ? '已超时，等待关闭' : '待支付') : activeOrder.data.status === 'pending_shipment' ? '待发货' : activeOrder.data.status}</strong></p></>}<div className="summary-total"><span>合计</span><strong>¥{activeOrder.data?.total ?? selectedTotal.toFixed(2)}</strong></div>{activeOrder.data?.status === 'pending_payment' && Date.parse(activeOrder.data.expires_at) > Date.now() && <button className="primary-action" onClick={() => void payOrder()}>模拟支付 ¥{activeOrder.data.total}</button>}{!activeOrderId && <button className="primary-action" disabled={submitting || savingAddress || !selectedItems.length || addresses.isFetching || !defaultAddress} onClick={() => void checkout()}>{submitting ? '正在提交…' : '提交订单并扣减库存'}</button>}</aside></div>
    </> : view === 'cart' ? <>
      <div className="commerce-tabs"><strong>全部商品 ({cart.data?.items.length ?? 0})</strong><span>已选 {selectedItems.reduce((sum, item) => sum + item.quantity, 0)} 件</span></div>
      <div className="commerce-layout"><section className="commerce-card cart-list"><div className="cart-toolbar"><label><input type="checkbox" aria-label="全选商品" checked={selectedItems.length > 0 && selectedItems.length === (cart.data?.items.length ?? 0)} onChange={event => cart.data?.items.forEach(item => toggleItem(item.product_id, event.currentTarget.checked))}/> 全选</label><span>商品信息</span><span>单价</span><span>数量</span><span>操作</span></div>
        {cart.isPending && currentUser?.role === 'buyer' && <p role="status">正在加载购物车…</p>}{cart.isError && <p role="alert">{cart.error.message}</p>}
        {!currentUser && <div className="empty-cart"><p>登录后可查看并管理你的购物车。</p><button className="primary-action" onClick={onLogin}>登录后继续</button></div>}
        {currentUser?.role === 'buyer' && cart.data?.items.map(item => <article className="cart-row" key={item.product_id}><input type="checkbox" checked={selection[item.product_id] ?? item.selected} aria-label={`勾选${item.name}`} onChange={event => toggleItem(item.product_id, event.currentTarget.checked)}/><img src={item.image_url} alt=""/><div className="cart-info"><b>{item.name}</b><span>库存 {item.stock}</span></div><strong className="cart-price">¥{item.unit_price}</strong><input type="number" min="1" max={item.stock} value={item.quantity} aria-label={`${item.name}数量`} onChange={async event => { const quantity = Number(event.target.value); if (quantity > 0 && quantity <= item.stock) await runCartAction(() => shopApi.update(item.product_id, { quantity })) }}/><button onClick={() => removeItem(item.product_id)}>删除</button></article>)}
        {currentUser?.role === 'buyer' && !cart.data?.items.length && <p className="empty-cart">购物车还是空的，去挑选喜欢的商品吧。</p>}
      </section><aside className="commerce-summary"><h2>结算明细</h2><p>已选商品 <strong>{selectedItems.reduce((sum, item) => sum + item.quantity, 0)} 件</strong></p><div className="summary-total"><span>合计</span><strong>¥{(cart.data?.items.reduce((sum, item) => sum + (selection[item.product_id] ?? item.selected ? Number(item.unit_price) * item.quantity : 0), 0) ?? 0).toFixed(2)}</strong></div><button className="primary-action" disabled={!selectedItems.length || currentUser?.role !== 'buyer'} onClick={() => void openCheckout()}>结算 ({selectedItems.reduce((sum, item) => sum + item.quantity, 0)})</button></aside></div>
      <footer className="commerce-footerbar"><label><input type="checkbox" aria-label="底部全选商品" checked={selectedItems.length > 0 && selectedItems.length === (cart.data?.items.length ?? 0)} onChange={event => cart.data?.items.forEach(item => toggleItem(item.product_id, event.currentTarget.checked))}/> 全选</label><span>已选 {selectedItems.reduce((sum, item) => sum + item.quantity, 0)} 件</span><strong>合计 ¥{(cart.data?.items.reduce((sum, item) => sum + (selection[item.product_id] ?? item.selected ? Number(item.unit_price) * item.quantity : 0), 0) ?? 0).toFixed(2)}</strong><button disabled={!selectedItems.length || currentUser?.role !== 'buyer'} onClick={() => void openCheckout()}>结算</button></footer>
      <section className="commerce-products"><h2>继续挑选商品</h2>{cartAddError && <p className="commerce-message error" role="alert">{cartAddError}</p>}{products.data?.items.map(product => <article key={product.id}><img src={product.image_url} alt=""/><div><b>{product.name}</b><span>¥{product.price} · 库存 {product.stock}</span></div><button onClick={async () => { if (!currentUser) { onLogin(); return } if (currentUser.role !== 'buyer') { setCartAddError('管理员账号不能使用买家购物车，请切换买家账号。'); return } try { await shopApi.add(product.id, 1); await invalidate(); setMessageError(false); setMessage('已加入购物车。'); setCartAddError('') } catch (error) { setCartAddError(error instanceof Error && (error.message.includes('CSRF') || error.message.includes('来源校验')) ? '安全验证已过期，请再次点击“加入购物车”重试。' : error instanceof Error ? error.message : '加入购物车失败') } }}>加入购物车</button></article>)}</section>
    </> : null}
  </main>
}
