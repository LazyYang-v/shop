import { useEffect, useState, type ComponentProps, type MouseEvent } from 'react'
import './info.css'

export type InfoPageProps = { view: string; categories: string[] }

export const notices: { id: string; title: string; summary: string; body: string[]; date: string }[] = [
  {
    id: 'shopping-guide', title: '购物流程说明：从挑选到下单',
    summary: '挑选商品、勾选购物车并选择收货地址，开启一次完整的购物演示。', date: '2026-10-22',
    body: [
      '访客可以浏览已上架商品，使用关键词搜索、分类筛选以及综合或价格排序。商品为单规格商品，请在购买前查看可售库存。',
      '登录买家账号后，将商品加入购物车，调整数量并勾选需要结算的条目。选择已保存的收货地址后提交订单，实际金额和库存以服务端校验结果为准。',
      '创建订单成功后会扣减可售库存，并从购物车移除本次结算的条目。订单保存下单时的商品、价格和地址快照，后续商品或地址修改不会改变历史订单。',
      '请在订单显示的支付截止时间前完成模拟支付。待支付订单可以主动取消；取消或超时关闭后恢复订单占用库存，但不会恢复购物车条目。',
    ],
  },
  {
    id: 'simulated-payment', title: '模拟支付说明：不涉及真实资金',
    summary: '本商城仅提供模拟支付，不收集支付凭证，也不提供真实退款。', date: '2026-10-22',
    body: [
      '本项目为单商家商城作品演示，不接入真实资金渠道。模拟支付不产生真实扣款，不需要银行卡、支付密码或支付凭证。',
      '买家只能对属于自己的、尚未过期的待支付订单进行模拟支付。成功后订单进入待发货，支付结果以服务端返回状态为准。',
      '支付截止时间到达后不能继续支付。后台扫描关闭前，订单可能显示“已超时，等待关闭”；扫描完成后才进入已关闭状态并恢复库存。',
      '本演示不提供真实退款、退款售后或在线客服。查看订单状态、取消未支付订单等可用操作，请前往“我的订单”。',
    ],
  },
  {
    id: 'shipping-and-receipt', title: '发货与收货说明：查看订单进度',
    summary: '管理员填写物流信息后发货，买家可查看保存的信息并确认收货。', date: '2026-10-22',
    body: [
      '模拟支付成功后，订单进入待发货。管理员填写物流公司与运单号并提交发货后，订单进入待收货。',
      '买家可以在自己的订单详情中查看已保存的物流公司、运单号和发货时间。本项目没有接入物流查询接口，不提供实时运输轨迹或送达时间承诺。',
      '待收货订单可以由所属买家确认收货，确认后进入已完成状态。本项目不提供自动确认收货、拆分发货或退款售后功能。',
      '尚未发货时没有运单信息属于正常情况，请以订单详情中的状态为准。',
    ],
  },
  {
    id: 'address-and-privacy', title: '地址与隐私说明：请使用演示信息',
    summary: '买家管理自己的地址；下单后保存地址快照，请勿填写真实敏感信息。', date: '2026-10-22',
    body: [
      '买家可以管理属于自己的收货地址、购物车和订单。请使用虚构邮箱、演示专用密码和虚构收货信息，不要在作品演示中提交真实敏感信息。',
      '创建订单时会保存收件人、联系电话和详细地址的快照。修改或删除地址簿中的地址，不会修改已经创建的订单。',
      '首版不支持修改已创建订单的收货地址。若待支付订单地址有误，可先取消订单，再将商品重新加入购物车，选择正确地址后重新下单。',
      '订单详情包含收货信息，请避免向他人分享含有个人信息的截图；在公共设备使用后，请前往账户页面退出登录。',
    ],
  },
]

const views = [
  { id: 'help', title: '帮助中心', description: '购物中的小疑问，在这里找到答案。', mark: '?' },
  { id: 'notices', title: '商城公告', description: '了解本商城的购物流程与演示边界。', mark: 'i' },
  { id: 'directory', title: '全部分类与网站导航', description: '从喜欢的分类出发，找到日常好物。', mark: '+' },
  { id: 'mobile', title: '手机使用说明', description: '打开手机浏览器，随时接着逛。', mark: 'M' },
]
const channels = [
  { id: 'living', title: '品质生活', description: '发现日常好物' },
  { id: 'value', title: '超值精选', description: '按需挑选，理性购物' },
  { id: 'home', title: '居家焕新', description: '为家添一点心意' },
  { id: 'digital', title: '数码好物', description: '探索数码与科技' },
  { id: 'style', title: '穿搭灵感', description: '找到自己的风格' },
  { id: 'reading', title: '阅读时光', description: '留一点时间给阅读' },
]
const serviceLinks = [
  { href: '?view=account', title: '我的账户', description: '登录与账户信息' },
  { href: '?view=addresses', title: '收货地址', description: '管理自己的地址簿' },
  { href: '?view=cart', title: '购物车', description: '勾选商品，准备结算' },
  { href: '?view=orders', title: '我的订单', description: '支付、进度与确认收货' },
  { href: '?view=help', title: '帮助中心', description: '查看常见问题' },
  { href: '?view=notices', title: '商城公告', description: '阅读商城使用说明' },
]
const faqs = [
  { question: '第一次购物，应该怎么下单？', answer: '先浏览或搜索商品，登录买家账号后加入购物车。勾选要结算的商品，选择收货地址并提交订单，再到我的订单完成模拟支付。', href: '?view=cart', label: '前往购物车' },
  { question: '模拟支付会真的扣钱吗？可以退款吗？', answer: '不会。模拟支付不接入真实资金渠道，也不收集支付凭证，仅将有效的待支付订单推进到待发货。本项目不提供真实退款或退款售后，请勿提交支付密码等敏感信息。', href: '?view=orders', label: '查看我的订单' },
  { question: '订单超时了，为什么还显示待支付？', answer: '到达支付截止时间后已不能支付。后台扫描关闭前会显示“已超时，等待关闭”；扫描完成后才变为已关闭并恢复占用库存。可以稍后刷新订单查看状态。', href: '?view=orders', label: '查看订单状态' },
  { question: '如何取消订单？商品会回到购物车吗？', answer: '可以在我的订单中取消属于自己的待支付订单。关闭后会恢复其占用的可售库存，但不会恢复购物车条目；需要重新购买时，请重新加入购物车。已支付订单不支持取消或退款。', href: '?view=orders', label: '前往我的订单' },
  { question: '在哪里查看物流，如何确认收货？', answer: '发货后可在订单详情查看管理员填写的物流公司和运单号。本项目没有实时物流查询，也没有送达时间承诺。待收货订单由买家确认收货后进入已完成。', href: '?view=orders', label: '查看订单与物流' },
  { question: '修改地址后，已下单的地址会改变吗？', answer: '不会。订单保存下单时的地址快照。待支付订单若地址有误，可取消后重新下单；已创建订单不能直接修改收货地址。演示时请使用虚构收货信息。', href: '?view=addresses', label: '管理收货地址' },
  { question: '有在线客服、优惠券或平台活动吗？', answer: '本项目是单商家商城演示，没有在线客服、优惠券、积分或多商家平台规则。遇到购物疑问可阅读本帮助页和商城公告；订单相关的可用操作请到我的订单查看。', href: '?view=orders', label: '查看可用订单操作' },
]

function navigate(event: MouseEvent<HTMLAnchorElement>) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  window.history.pushState(null, '', event.currentTarget.href)
  window.dispatchEvent(new PopStateEvent('popstate'))
  window.scrollTo({ top: 0, behavior: 'auto' })
}
function InfoLink(props: ComponentProps<'a'>) {
  return <a {...props} onClick={navigate} />
}
function readNotice() {
  return new URLSearchParams(window.location.search).get('notice') ?? ''
}

export function InfoPage({ view, categories }: InfoPageProps) {
  const active = views.find(item => item.id === view) ?? views[0]
  const [noticeId, setNoticeId] = useState(readNotice)
  const [query, setQuery] = useState('')
  useEffect(() => {
    const sync = () => setNoticeId(readNotice())
    sync()
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [view])
  const notice = notices.find(item => item.id === noticeId)
  const filteredFaqs = faqs.filter(item => `${item.question}${item.answer}`.includes(query.trim()))
  const uniqueCategories = [...new Set(categories.filter(item => item.trim()))]

  return <main className="info-page">
    <div className="info-topbar"><span>单商家商城 · 作品演示</span><InfoLink href="?view=orders">我的订单</InfoLink><InfoLink href="?view=cart">购物车</InfoLink></div>
    <header className="info-header"><InfoLink className="info-brand" href="?">淘宝<span>认真生活，好好逛</span></InfoLink><div className="info-header-label">购物指南</div><InfoLink className="info-home" href="?">返回商城首页 →</InfoLink></header>
    <nav className="info-tabs" aria-label="购物指南导航">{views.map(item => <InfoLink key={item.id} href={`?view=${item.id}`} aria-current={active.id === item.id ? 'page' : undefined}>{item.title}</InfoLink>)}</nav>
    <div className="info-content">
      <nav className="info-breadcrumb" aria-label="面包屑"><InfoLink href="?">首页</InfoLink><span aria-hidden="true">/</span>{noticeId && active.id === 'notices' ? <><InfoLink href="?view=notices">商城公告</InfoLink><span aria-hidden="true">/</span><span>公告详情</span></> : <span>{active.title}</span>}</nav>
      <section className="info-hero"><div><p className="info-eyebrow">TAOBAO · 购物指南</p><h1>{active.title}</h1><p>{active.description}</p></div><span className="info-hero-mark" aria-hidden="true">{active.mark}</span></section>
      {active.id === 'help' && <div className="info-help-layout"><section className="info-card info-faq"><div className="info-section-heading"><h2>常见问题</h2><span>从下单到收货</span></div><label className="info-search">搜索帮助<input type="search" placeholder="试试“支付”“地址”“物流”" value={query} onChange={event => setQuery(event.target.value)} /></label><p className="info-result-count" role="status">{query.trim() ? `找到 ${filteredFaqs.length} 个相关问题` : '点击问题展开答案'}</p>{filteredFaqs.map(item => <details key={item.question}><summary>{item.question}</summary><div className="info-faq-answer"><p>{item.answer}</p><InfoLink href={item.href}>{item.label} →</InfoLink></div></details>)}{!filteredFaqs.length && <div className="info-empty"><p>没有找到相关问题，试试更短的关键词。</p><button type="button" onClick={() => setQuery('')}>查看全部问题</button></div>}</section><aside className="info-help-aside"><section className="info-card"><h2>常用入口</h2><div className="info-shortcuts">{serviceLinks.slice(0, 4).map(item => <InfoLink key={item.href} href={item.href}>{item.title}<span aria-hidden="true">→</span></InfoLink>)}</div></section><section className="info-boundary"><p className="info-eyebrow">关于本演示</p><h2>放心体验，理性使用</h2><p>模拟支付不涉及真实资金。本项目没有真实退款或在线客服，请在订单页查看可用操作。</p><InfoLink href="?view=orders">前往我的订单 →</InfoLink></section></aside></div>}
      {active.id === 'notices' && <section className="info-card">{noticeId ? notice ? <article className="info-article"><InfoLink className="info-back" href="?view=notices">← 返回公告列表</InfoLink><p className="info-eyebrow">商城使用说明</p><h2>{notice.title}</h2><time dateTime={notice.date}>发布于 {notice.date}</time><p className="info-article-summary">{notice.summary}</p>{notice.body.map(paragraph => <p key={paragraph}>{paragraph}</p>)}<div className="info-article-actions"><InfoLink href="?view=orders">查看我的订单 →</InfoLink><InfoLink href="?view=help">帮助中心</InfoLink></div><nav className="info-related" aria-label="其他公告"><h3>继续了解</h3>{notices.filter(item => item.id !== notice.id).map(item => <InfoLink href={`?view=notices&notice=${item.id}`} key={item.id}>{item.title} →</InfoLink>)}</nav></article> : <div className="info-empty"><h2>这条公告不存在</h2><p>链接可能有误，请返回公告列表查看使用说明。</p><InfoLink href="?view=notices">查看全部公告 →</InfoLink></div> : <><div className="info-section-heading"><h2>全部公告</h2><span>共 {notices.length} 条使用说明</span></div><div className="info-notice-list">{notices.map(item => <article key={item.id}><div><span className="info-tag">使用说明</span><time dateTime={item.date}>{item.date}</time></div><h3><InfoLink href={`?view=notices&notice=${item.id}`}>{item.title}</InfoLink></h3><p>{item.summary}</p><InfoLink className="info-read-more" href={`?view=notices&notice=${item.id}`}>阅读全文 <span aria-hidden="true">→</span></InfoLink></article>)}</div></>}</section>}
      {active.id === 'directory' && <div className="info-directory"><section className="info-card"><div className="info-section-heading"><h2>全部商品分类</h2><InfoLink href="?">浏览全部商品 →</InfoLink></div><p className="info-muted">按分类浏览在售商品，找到你需要的那一件。</p>{uniqueCategories.length ? <div className="info-category-grid">{uniqueCategories.map(category => <InfoLink key={category} href={`?category=${encodeURIComponent(category)}`}>{category}<span aria-hidden="true">›</span></InfoLink>)}</div> : <p className="info-empty">暂无可用分类，可以先前往首页浏览全部商品。</p>}</section><section className="info-card"><div className="info-section-heading"><h2>主题频道</h2><span>换个角度发现好物</span></div><div className="info-channel-grid">{channels.map(item => <InfoLink key={item.id} href={`?view=channel&channel=${item.id}`}><strong>{item.title}</strong><span>{item.description}</span><b aria-hidden="true">→</b></InfoLink>)}</div></section><section className="info-card"><h2>网站导航</h2><div className="info-service-grid">{serviceLinks.map(item => <InfoLink href={item.href} key={item.href}><strong>{item.title} <span aria-hidden="true">↗</span></strong><span>{item.description}</span></InfoLink>)}</div></section></div>}
      {active.id === 'mobile' && <div className="info-mobile-layout"><section className="info-card"><h2>手机浏览器，也能轻松逛</h2><p className="info-muted">使用当前商城网页，无需下载应用。</p><ol className="info-mobile-steps"><li><h3>打开商城网址</h3><p>在手机浏览器中输入当前商城可访问的网址。若使用本机开发地址，需要先由运行项目的人提供手机可访问的地址；手机的 localhost 指向手机本身。</p><InfoLink href="?">打开商城首页 →</InfoLink></li><li><h3>挑选商品，加入购物车</h3><p>使用首页搜索或分类入口挑选商品。登录买家账号后加入购物车，调整数量并勾选本次要购买的商品。</p><InfoLink href="?view=directory">浏览全部分类 →</InfoLink></li><li><h3>选好地址，完成演示下单</h3><p>请使用虚构的收货信息。提交订单后，在我的订单中于截止时间前完成模拟支付，再查看后续订单进度。</p><InfoLink href="?view=orders">前往我的订单 →</InfoLink></li></ol></section><aside><section className="info-boundary"><p className="info-eyebrow">使用小提示</p><h2>继续逛，也记得保护隐私</h2><p>可使用浏览器的“添加书签”功能保存商城网址。在公共设备上使用后，请前往账户页面退出登录。</p><p>手机与电脑分别使用各自的登录会话；登录同一买家账号后，可查看该账号保存的购物车、地址和订单。</p><InfoLink href="?view=account">前往我的账户 →</InfoLink></section><section className="info-card info-mobile-note"><h2>支付前先了解</h2><p>这里只提供模拟支付，没有真实扣款、真实退款或在线客服。</p><InfoLink href="?view=notices&notice=simulated-payment">阅读模拟支付说明 →</InfoLink></section></aside></div>}
      <div className="info-footer"><span>精选好物，认真生活</span><p>淘宝风格电商作品集 · 单商家商城演示</p><InfoLink href="?view=help">帮助中心</InfoLink><InfoLink href="?view=orders">我的订单</InfoLink></div>
    </div>
  </main>
}
