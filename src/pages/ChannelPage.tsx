import { useQuery } from '@tanstack/react-query'
import { getCategories, getProducts, type ProductQuery } from '../api/products'
import './channels.css'

export const channels = [
  { id: 'living', title: '生活超市', subtitle: '把日常过成喜欢的样子', description: '从一餐一饭到日常照护，发现生活中的实用好物。', categories: ['食品', '母婴', '宠物', '医疗健康'], emoji: '🛍️', tone: 'peach' },
  { id: 'value', title: '平价好物', subtitle: '好生活，也有好价格', description: '按价格升序挑选商品，让每一份预算都花得明白。', categories: [], emoji: '🏷️', tone: 'pink' },
  { id: 'home', title: '家居焕新', subtitle: '给家一点新鲜感', description: '实用家电、办公用品与日常工具，为熟悉的空间添一份舒适。', categories: ['家电', '办公', '工业品'], emoji: '🛋️', tone: 'peach' },
  { id: 'digital', title: '数码生活', subtitle: '让生活多一点灵感', description: '手机、家电与办公好物，陪伴工作和生活的每一刻。', categories: ['手机', '家电', '办公'], emoji: '🎧', tone: 'blue' },
  { id: 'style', title: '穿搭美妆', subtitle: '今天也要好好打扮', description: '从日常穿搭到随身好物，找到自己的生活风格。', categories: ['女装', '男装', '鞋靴', '美妆'], emoji: '👜', tone: 'pink' },
  { id: 'reading', title: '阅读时光', subtitle: '留一点时间给自己', description: '翻开一本书，写下一个想法，让忙碌的日子慢下来。', categories: ['图书', '办公'], emoji: '📖', tone: 'blue' },
]

export function ChannelPage() {
  const params = new URLSearchParams(window.location.search)
  const channel = channels.find(item => item.id === params.get('channel'))
  const available = useQuery({ queryKey: ['categories'], queryFn: getCategories })
  const categoryList = channel?.categories.length ? channel.categories.filter(item => available.data?.includes(item)) : available.data ?? []
  const requestedCategory = params.get('category') ?? ''
  const category = categoryList.includes(requestedCategory) ? requestedCategory : channel?.categories.length ? categoryList[0] : undefined
  const requestedPage = Number(params.get('page') ?? 1)
  const requestedSort = params.get('sort')
  const sort: ProductQuery['sort'] = requestedSort === 'price_asc' || requestedSort === 'price_desc' ? requestedSort : channel?.id === 'value' ? 'price_asc' : 'popular'
  const page = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  const query = useQuery({ queryKey: ['channel-products', channel?.id, category, sort, page], queryFn: () => getProducts({ category, sort, page, page_size: 20 }), enabled: !!channel && available.isSuccess })
  function url(values: Record<string, string>) {
    const next = new URLSearchParams(params)
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    if ('category' in values || 'sort' in values) next.delete('page')
    return `?${next}`
  }
  return <main className="channel-page">
    <header className="channel-masthead"><a className="channel-brand" href="/">商城<span>发现好物</span></a><nav aria-label="频道导航"><a href="?view=directory">全部分类</a><a href="?view=account">我的商城</a><a href="?view=cart">购物车</a></nav></header>
    <nav className="channel-tabs" aria-label="好物频道">{channels.map(item => <a key={item.id} href={`?view=channel&channel=${item.id}`} aria-current={channel?.id === item.id ? 'page' : undefined}>{item.title}</a>)}</nav>
    {!channel ? <section className="channel-empty"><h1>这个频道暂未开放</h1><p>去其他频道逛逛，发现更多生活好物。</p><a href="?view=directory">查看全部频道</a></section> : <>
      <section className={`channel-hero ${channel.tone}`}><div><small>SHANGCHENG · {channel.title}</small><h1>{channel.subtitle}</h1><p>{channel.description}</p><a href="#channel-products">开始逛逛　↓</a></div><span aria-hidden="true">{channel.emoji}</span></section>
      <section className="channel-catalog" id="channel-products">
        <div className="channel-heading"><div><h2>{channel.title}精选</h2><p>在售商品 · 商品价格与库存以当前详情为准</p></div><label>排序 <select aria-label="频道排序" value={sort} onChange={event => { window.location.href = url({ sort: event.target.value }) }}><option value="popular">综合</option><option value="price_asc">价格升序</option><option value="price_desc">价格降序</option></select></label></div>
        <nav className="channel-categories" aria-label="频道商品分类">{!channel.categories.length && <a href={url({ category: '' })} aria-current={!category ? 'page' : undefined}>全部商品</a>}{categoryList.map(item => <a key={item} href={url({ category: item })} aria-current={category === item ? 'page' : undefined}>{item}</a>)}</nav>
        {(available.isPending || query.isLoading) && <p role="status" className="channel-empty">正在寻找频道好物…</p>}
        {(available.isError || query.isError) && <div role="alert" className="channel-empty"><p>{available.error?.message ?? query.error?.message}</p><button onClick={() => void (available.isError ? available.refetch() : query.refetch())}>重新加载</button></div>}
        {query.data?.items.length === 0 && <div className="channel-empty"><p>这个分类暂时没有在售商品，试试其他分类吧。</p><a href="/">浏览全部商品</a></div>}
        <div className="channel-products">{query.data?.items.map(product => <article key={product.id}><a href={`?product=${product.id}`}><img src={product.image_url} alt={product.name} loading="lazy"/><div><small>{product.category}</small><h3>{product.name}</h3><p>{product.description}</p><div className="channel-product-meta"><strong>¥{product.price}</strong><span>库存 {product.stock}</span></div></div></a></article>)}</div>
        {query.data && query.data.total > 0 && <div className="channel-pagination"><span>共 {query.data.total} 件商品 · 第 {query.data.page} 页</span>{page > 1 && <a href={url({ page: String(page - 1) })}>上一页</a>}{page * query.data.page_size < query.data.total && <a href={url({ page: String(page + 1) })}>下一页</a>}</div>}
      </section>
    </>}
    <footer className="channel-footer">精选好物，认真生活<a href="?view=help">购物帮助 →</a></footer>
  </main>
}
