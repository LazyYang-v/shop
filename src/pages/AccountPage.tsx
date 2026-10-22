import { useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { User } from '../api/auth'
import { shopApi, type Address, type AddressInput } from '../api/shop'
import './account.css'

export type AccountPageProps = {
  currentUser: User | null
  onLogin: () => void
  addressesOnly?: boolean
}

const orderLinks = [
  { status: 'pending_payment', label: '待支付', hint: '查看并完成模拟支付' },
  { status: 'pending_shipment', label: '待发货', hint: '等待商家安排配送' },
  { status: 'pending_receipt', label: '待收货', hint: '查看物流、确认收货' },
  { status: 'completed', label: '已完成', hint: '回顾已完成的订单' },
  { status: 'closed', label: '已关闭', hint: '查看已取消或超时关闭的订单' },
]
const fields = [
  { name: 'recipient_name', label: '收货人', max: 80, autocomplete: 'name', placeholder: '填写收货人姓名' },
  { name: 'phone', label: '联系电话', max: 32, autocomplete: 'tel', placeholder: '手机号码或固定电话' },
  { name: 'province', label: '省份', max: 80, autocomplete: 'address-level1', placeholder: '如：浙江省' },
  { name: 'city', label: '城市', max: 80, autocomplete: 'address-level2', placeholder: '如：杭州市' },
  { name: 'district', label: '区县', max: 80, autocomplete: 'address-level3', placeholder: '如：西湖区' },
  { name: 'detail', label: '详细地址', max: 240, autocomplete: 'street-address', placeholder: '街道、门牌号、楼栋及房间号' },
] as const

type FieldName = typeof fields[number]['name']
const emptyAddress: AddressInput = { recipient_name: '', phone: '', province: '', city: '', district: '', detail: '', is_default: false }

export function AccountPage({ currentUser, onLogin, addressesOnly = false }: AccountPageProps) {
  return <main className="account-page">
    <header className="account-masthead">
      <a className="account-brand" href="/" aria-label="淘宝首页">淘宝 <span>我的淘宝</span></a>
      <nav aria-label="个人中心导航">
        <a href="/">返回首页</a>
        <a href="?view=account" aria-current={!addressesOnly ? 'page' : undefined}>个人中心</a>
        <a href="?view=orders">我的订单</a>
        <a href="?view=cart">购物车</a>
        <a href="?view=addresses" aria-current={addressesOnly ? 'page' : undefined}>地址簿</a>
      </nav>
    </header>
    <div className="account-content">
      <div className="account-page-heading"><div><p className="account-eyebrow">我的淘宝 / {addressesOnly ? '收货地址' : '个人中心'}</p><h1>{addressesOnly ? '地址簿' : '个人中心'}</h1><p>{addressesOnly ? '管理常用收货信息，让每次下单更方便。' : '账号、订单和收货信息，都在这里。'}</p></div></div>
      {!currentUser ? <section className="account-panel account-empty"><h2>登录后，开启你的个人中心</h2><p>使用买家账号查看订单、购物车和收货地址。</p><button className="account-primary" onClick={onLogin}>登录后继续</button></section>
        : currentUser.role !== 'buyer' ? <section className="account-panel account-empty"><h2>这里是买家个人中心</h2><p>当前登录的是管理员账号，请切换买家账号后管理订单和收货地址。</p><button className="account-primary" onClick={onLogin}>切换账号</button><a href="/">返回商城首页</a></section>
          : <BuyerAccount key={currentUser.id} currentUser={currentUser} addressesOnly={addressesOnly} />}
    </div>
    <footer className="account-footer">我的淘宝 · 轻松管理每一笔购物</footer>
  </main>
}

function BuyerAccount({ currentUser, addressesOnly }: { currentUser: User; addressesOnly: boolean }) {
  const queryClient = useQueryClient()
  const queryKey = ['addresses', currentUser.id]
  const addresses = useQuery({ queryKey, queryFn: shopApi.addresses })
  const [editor, setEditor] = useState<{ id?: string; data: AddressInput } | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldName, string>>>({})
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [pending, setPending] = useState('')
  const busy = useRef(false)
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null)
  const defaultAddress = addresses.data?.find(address => address.is_default)

  async function runAction(action: string, request: () => Promise<Address | void>, success: string, deletedId?: string) {
    if (busy.current || currentUser.role !== 'buyer') return
    busy.current = true
    setPending(action)
    setNotice(null)
    try {
      const saved = await request()
      await queryClient.cancelQueries({ queryKey, exact: true })
      queryClient.setQueryData<Address[]>(queryKey, existing => {
        const remaining = (existing ?? []).filter(address => address.id !== (saved?.id ?? deletedId))
        return saved ? [...remaining.map(address => saved.is_default ? { ...address, is_default: false } : address), saved] : remaining
      })
      if (action === 'save') setEditor(null)
      setDeleteId(null)
      setNotice({ error: false, text: success })
      // Mark the shared checkout/address cache stale and fetch the server's current list.
      void queryClient.invalidateQueries({ queryKey, exact: true })
    } catch (error) {
      setNotice({ error: true, text: error instanceof Error ? error.message : '操作失败，请稍后重试。' })
    } finally {
      busy.current = false
      setPending('')
    }
  }

  function openEditor(address?: Address) {
    setEditor({ id: address?.id, data: address ? { recipient_name: address.recipient_name, phone: address.phone, province: address.province, city: address.city, district: address.district, detail: address.detail, is_default: address.is_default } : { ...emptyAddress, is_default: addresses.data?.length === 0 } })
    setFieldErrors({})
    setDeleteId(null)
    setNotice(null)
  }

  function saveAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editor || busy.current) return
    const data = { ...editor.data }
    const errors: Partial<Record<FieldName, string>> = {}
    for (const field of fields) {
      data[field.name] = data[field.name].trim()
      if (!data[field.name]) errors[field.name] = `请填写${field.label}。`
      else if (data[field.name].length > field.max) errors[field.name] = `${field.label}不能超过 ${field.max} 个字符。`
    }
    if (data.phone && (data.phone.length < 6 || !/^[+\d\s()\-]+$/.test(data.phone) || data.phone.replace(/\D/g, '').length < 6)) errors.phone = '请输入有效联系电话，至少包含 6 位数字，可使用 +、空格、括号或短横线。'
    setFieldErrors(errors)
    setEditor({ ...editor, data })
    if (Object.keys(errors).length) {
      const firstInvalid = fields.find(field => errors[field.name])
      if (firstInvalid) event.currentTarget.querySelector<HTMLElement>(`[name="${firstInvalid.name}"]`)?.focus()
      return
    }
    void runAction('save', () => shopApi.saveAddress(data, editor.id), editor.id ? '收货地址已更新。' : '收货地址已添加。')
  }

  return <>
    {!addressesOnly && <>
      <section className="account-panel account-profile" aria-labelledby="account-profile-heading">
        <div className="account-avatar" aria-hidden="true">{currentUser.email.slice(0, 1).toUpperCase()}</div>
        <div><h2 id="account-profile-heading">账号信息</h2><dl><div><dt>登录邮箱</dt><dd>{currentUser.email}</dd></div><div><dt>账号身份</dt><dd>买家</dd></div></dl></div>
        <a className="account-text-link" href="?view=addresses">管理收货地址 →</a>
      </section>
      <section className="account-panel" aria-labelledby="account-orders-heading">
        <div className="account-section-heading"><h2 id="account-orders-heading">我的订单</h2><a href="?view=orders">全部订单 →</a></div>
        <div className="account-order-links">{orderLinks.map((link, index) => <a key={link.status} href={`?view=orders&status=${link.status}`}><span className="account-link-number" aria-hidden="true">0{index + 1}</span><strong>{link.label}</strong><span>{link.hint}</span><span className="account-link-arrow" aria-hidden="true">↗</span></a>)}</div>
      </section>
      <div className="account-shortcuts">
        <section className="account-panel"><p className="account-eyebrow">继续购物</p><h2>我的购物车</h2><p>查看已选商品，调整数量并结算。</p><a className="account-text-link" href="?view=cart">打开购物车 →</a></section>
        <section className="account-panel"><p className="account-eyebrow">配送信息</p><h2>我的地址簿</h2>{defaultAddress ? <p>{defaultAddress.recipient_name} · {defaultAddress.province} {defaultAddress.city} {defaultAddress.district}<br />已设置默认收货地址</p> : <p>{addresses.isPending ? '正在读取收货地址…' : addresses.isError ? '地址暂时无法读取，请进入地址簿重试。' : addresses.data?.length ? '尚未设置默认地址，可在地址簿中选择。' : '添加常用地址，下单时直接选择。'}</p>}<a className="account-text-link" href="?view=addresses">管理地址簿 →</a></section>
      </div>
    </>}
    {addressesOnly && <section className="account-panel" aria-labelledby="account-addresses-heading">
      <div className="account-section-heading"><div><h2 id="account-addresses-heading">收货地址</h2><p>修改或删除地址不会改变历史订单中的地址快照。</p></div><button className="account-primary" disabled={!!pending || !!editor || !addresses.isSuccess || addresses.isFetching} onClick={() => openEditor()}>＋ 新增地址</button></div>
      {notice && <p className={`account-notice${notice.error ? ' account-error' : ''}`} role={notice.error ? 'alert' : 'status'}>{notice.text}</p>}
      {addresses.isPending && <p className="account-empty" role="status">正在加载收货地址…</p>}
      {addresses.isError && <div className="account-notice account-error" role="alert"><p>地址加载失败：{addresses.error.message}</p><button disabled={addresses.isFetching || !!pending} onClick={() => void addresses.refetch()}>{addresses.isFetching ? '正在重试…' : '重试加载'}</button></div>}
      {editor && <form className="account-address-form" onSubmit={saveAddress} noValidate>
        <h3>{editor.id ? '编辑收货地址' : '新增收货地址'}</h3>
        <p>所有文本字段均为必填项。联系电话支持手机和固定电话。</p>
        <fieldset disabled={!!pending}><legend className="account-sr-only">收货信息</legend><div className="account-fields">
          {fields.map(field => <label className={field.name === 'detail' ? 'account-field-wide' : ''} key={field.name} htmlFor={`account-${field.name}`}>{field.label}<span aria-hidden="true"> *</span>
            {field.name === 'detail' ? <textarea id={`account-${field.name}`} name={field.name} required maxLength={field.max} autoComplete={field.autocomplete} placeholder={field.placeholder} rows={3} value={editor.data[field.name]} aria-invalid={!!fieldErrors[field.name]} aria-describedby={fieldErrors[field.name] ? `account-${field.name}-error` : undefined} onChange={event => setEditor({ ...editor, data: { ...editor.data, [field.name]: event.target.value } })} />
              : <input id={`account-${field.name}`} name={field.name} type={field.name === 'phone' ? 'tel' : 'text'} required maxLength={field.max} autoComplete={field.autocomplete} placeholder={field.placeholder} value={editor.data[field.name]} aria-invalid={!!fieldErrors[field.name]} aria-describedby={fieldErrors[field.name] ? `account-${field.name}-error` : undefined} onChange={event => setEditor({ ...editor, data: { ...editor.data, [field.name]: event.target.value } })} />}
            {fieldErrors[field.name] && <small id={`account-${field.name}-error`} className="account-field-error">{fieldErrors[field.name]}</small>}
          </label>)}
        </div><label className="account-checkbox"><input type="checkbox" checked={editor.data.is_default} onChange={event => setEditor({ ...editor, data: { ...editor.data, is_default: event.target.checked } })} />设为默认地址</label>
          <p className="account-help">首个地址会自动设为默认；下单时仍可选择其他地址。</p>
          <div className="account-actions"><button type="submit" className="account-primary">{pending === 'save' ? '正在保存…' : '保存地址'}</button><button type="button" onClick={() => { setEditor(null); setFieldErrors({}) }}>取消编辑</button></div>
        </fieldset>
      </form>}
      {addresses.isSuccess && addresses.data.length === 0 && !editor && <div className="account-empty"><h3>还没有收货地址</h3><p>点击“新增地址”，保存你的第一条收货信息。</p></div>}
      <div className="account-address-list" aria-busy={!!pending || addresses.isFetching}>
        {addresses.data?.map(address => <article key={address.id} className={`account-address${address.is_default ? ' account-address-default' : ''}`}>
          <div className="account-address-heading"><h3>{address.recipient_name}</h3><span>{address.phone}</span>{address.is_default && <span className="account-default-badge">默认地址</span>}</div>
          <p className="account-address-location">{address.province} {address.city} {address.district}<br />{address.detail}</p>
          <div className="account-actions"><button disabled={!!pending || !!editor || addresses.isFetching} onClick={() => openEditor(address)}>编辑</button>{!address.is_default && <button disabled={!!pending || !!editor || addresses.isFetching} onClick={() => { const { id, ...data } = address; void runAction(`default-${id}`, () => shopApi.saveAddress({ ...data, is_default: true }, id), '默认收货地址已更新。') }}>{pending === `default-${address.id}` ? '正在设置…' : '设为默认'}</button>}<button className="account-danger" disabled={!!pending || !!editor || addresses.isFetching} onClick={() => { setDeleteId(address.id); setNotice(null) }}>删除</button></div>
          {deleteId === address.id && <div className="account-delete-confirm" role="group" aria-label={`确认删除${address.recipient_name}的地址`}><p>确定删除这条收货地址？{address.is_default && '删除后请为其他地址重新设置默认。'}此操作无法撤销。</p><div className="account-actions"><button className="account-danger" disabled={!!pending} onClick={() => void runAction(`delete-${address.id}`, () => shopApi.deleteAddress(address.id), '收货地址已删除。', address.id)}>{pending === `delete-${address.id}` ? '正在删除…' : '确认删除'}</button><button disabled={!!pending} onClick={() => setDeleteId(null)}>保留地址</button></div></div>}
        </article>)}
      </div>
    </section>}
  </>
}
