/* Buyer workspace presentation; business requests stay in the existing chat flow. */
(() => {
  const byId = id => document.getElementById(id);
  const recentKey = 'shop.customer-service.recent';
  const returnKey = 'shop.customer-service.storefront-return';
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const statusLabels = { pending_payment: '待付款', pending_shipment: '待发货', pending_receipt: '待收货', completed: '已完成', closed: '已关闭' };
  let host;
  let owner = 'guest';
  let entries = [];
  let currentId = null;
  let historyVersion = 0;
  let orders = new Map();
  let selectedOrder = null;
  let accountVersion = 0;
  const productCards = new Map();
  let operationState = 'AI_ACTIVE';
  let querying = false;

  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const use = document.createElementNS(svg.namespaceURI, 'use');
    use.setAttribute('href', `#${name}`);
    svg.setAttribute('aria-hidden', 'true');
    svg.append(use);
    return svg;
  }
  function action(text, callback, secondary = false) {
    const button = node('button', text, secondary ? 'card-secondary' : 'card-primary');
    button.type = 'button';
    button.dataset.consultationAction = 'true';
    button.addEventListener('click', () => { showCurrent(); closePanels(); callback(); });
    return button;
  }
  function localLink(label, href) {
    const link = node('a', label, 'card-secondary');
    link.href = href;
    return link;
  }
  function timestamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '时间暂不可用' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function thumbnail(src, label, className = 'product-thumbnail') {
    const box = node('div', undefined, className);
    box.append(icon('bag-icon'));
    // Only storefront images are loaded; arbitrary image URLs from text are ignored.
    if (typeof src === 'string' && /^\/images\/[a-z0-9/_%.\-]+(?:\?[a-z0-9=&%_.\-]*)?$/i.test(src)) {
      const image = node('img'); image.alt = label || ''; image.loading = 'lazy';
      image.addEventListener('load', () => { box.querySelector('svg')?.remove(); });
      image.addEventListener('error', () => { image.remove(); });
      image.src = src;
      box.append(image);
    }
    return box;
  }
  function facts(section, rows) {
    const list = node('dl', undefined, 'card-facts');
    for (const [label, value] of rows) {
      const row = node('div'); row.append(node('dt', `${label}：`), node('dd', value)); list.append(row);
    }
    section.append(list);
  }
  function card(kind, label, status) {
    const section = node('section', undefined, `business-card ${kind}`);
    section.setAttribute('aria-label', label);
    const heading = node('div', undefined, 'card-heading');
    heading.append(node('span', label));
    if (status) {
      const badge = node('span', statusLabels[status] || status, 'status-badge');
      badge.dataset.status = status; heading.append(badge);
    }
    section.append(heading);
    return section;
  }
  function productLine(section, title, description, image, price) {
    const line = node('div', undefined, 'card-product');
    const information = node('div', undefined, 'card-product-info');
    information.append(node('strong', title, 'card-title'));
    if (description) information.append(node('p', description, 'card-description'));
    if (price) information.append(node('strong', `¥${price}`, 'card-price'));
    line.append(thumbnail(image, title), information); section.append(line);
  }
  function append(section) {
    host.activate();
    host.messages.append(section);
    host.messages.scrollTop = host.messages.scrollHeight;
    return section;
  }
  function orderContext(order, detail) {
    selectedOrder = order.order_number;
    const section = node('section', undefined, 'context-order');
    section.append(node('span', '正在咨询的订单', 'muted'), node('span', statusLabels[order.status], 'status-badge'));
    section.append(node('strong', order.product_summary, 'context-title'), node('p', `${statusLabels[order.status]} · ¥${order.total} · 尾号 ${order.order_number.slice(-4)}`));
    byId('order-picker').open = false;
    byId('context-topic').textContent = '订单与服务跟进';
    const actions = node('div', undefined, 'card-actions');
    actions.append(localLink('订单详情', `/?view=orders&order=${encodeURIComponent(order.order_number)}`));
    if (detail) actions.append(action('查询服务进度', () => host.sendOrder(order.order_number, '查询售后进度'), true));
    section.append(actions);
    byId('current-context').replaceChildren(section);
    byId('sidebar-orders').querySelectorAll('[data-order-id]').forEach(item => {
      item.classList.toggle('is-selected', item.dataset.orderId === selectedOrder);
    });
  }
  function renderOrder(order, detail = false) {
    const section = card('order-card', detail ? '订单详情' : '订单信息', order.status);
    section.dataset.orderId = order.order_number;
    const known = orders.get(order.order_number);
    productLine(section, order.product_summary, `订单尾号 ${order.order_number.slice(-4)}`, known?.items?.[0]?.image_url, order.total);
    const actions = node('div', undefined, 'card-actions');
    if (!detail) {
      actions.append(action('咨询此订单', () => host.selectOrder(order.order_number)));
      const extra = node('details', undefined, 'fact-details');
      extra.append(node('summary', '订单详情'));
      facts(extra, [['订单号', order.order_number], ['创建时间', timestamp(order.created_at)]]);
      section.append(extra);
    } else {
      if (order.status === 'pending_payment') {
        host.messages.querySelectorAll('[data-cancel-request-order]').forEach(button => button.remove());
        const cancel = action('申请取消订单', () => host.requestCancel(order.order_number));
        cancel.dataset.cancelRequestOrder = order.order_number;
        actions.append(cancel);
      }
      if (order.status === 'pending_shipment') actions.append(action('催促发货', () => host.sendOrder(order.order_number, '催发货')));
      actions.append(localLink('查看物流', `/?view=orders&order=${encodeURIComponent(order.order_number)}&logistics=1`));
      actions.append(action('退换货咨询', () => host.sendOrder(order.order_number, '我想退换货'), true));
      if (order.shipping_company || order.tracking_number || order.shipped_at) {
        const logistics = node('div', undefined, 'logistics-block');
        logistics.append(node('h3', '物流信息'));
        facts(logistics, [['物流公司', order.shipping_company || '未保存'], ['运单号', order.tracking_number || '未保存']]);
        const timeline = node('ol', undefined, 'logistics-timeline');
        if (order.status === 'completed') timeline.append(node('li', '买家已确认收货 · 订单已完成'));
        if (order.shipped_at) timeline.append(node('li', `商家已发货 · ${timestamp(order.shipped_at)}`));
        logistics.append(timeline, node('p', '以上仅为商城已保存的物流信息，不包含实时轨迹或预计送达时间。', 'muted'));
        section.append(logistics);
      } else section.append(node('p', '暂无已保存物流信息。', 'muted'));
      const extra = node('details', undefined, 'fact-details'); extra.append(node('summary', '完整订单信息'));
      facts(extra, [['订单号', order.order_number], ['支付截止', timestamp(order.expires_at)], ['关闭原因', order.close_reason === 'buyer_cancelled' ? '买家取消' : order.close_reason === 'payment_timeout' ? '支付超时' : '无']]);
      section.append(extra);
      orderContext(order, true);
    }
    section.append(actions);
    return append(section);
  }
  function renderProduct(product, label, callback) {
    const previous = productCards.get(product.id);
    if (previous?.isConnected) {
      const archived = node('details', undefined, 'previous-result');
      archived.append(node('summary', `${product.name} · 此前查询结果`));
      previous.replaceWith(archived);
      previous.querySelectorAll('button').forEach(button => { button.disabled = true; });
      archived.append(previous);
    }
    const section = card('product-card', '商城商品');
    section.dataset.productId = product.id;
    productCards.set(product.id, section);
    productLine(section, product.name, `${product.category} · 单规格 · ${product.is_listed ? '正常销售' : '暂停售卖'}`, undefined, product.price);
    section.append(node('p', product.stock > 0 ? `现货 ${product.stock} 件` : '暂时缺货', 'stock-label'));
    const actions = node('div', undefined, 'card-actions');
    actions.append(localLink('商品详情', `/?product=${encodeURIComponent(product.id)}`));
    if (callback) actions.append(action('价格与库存', callback, true));
    if (host.integrated()) actions.append(action('找相似款', () => host.send(`推荐${product.category}商品`), true));
    section.append(actions);
    const context = node('section', undefined, 'context-product');
    context.append(node('span', '当前商品', 'muted'), node('strong', product.name, 'context-title'), node('p', `${product.category} · ¥${product.price}`));
    context.append(localLink('查看商品详情 →', `/?product=${encodeURIComponent(product.id)}`));
    byId('context-topic').textContent = '商品选购与推荐';
    byId('current-context').replaceChildren(context);
    if (host.integrated()) {
      const version = accountVersion;
      fetch(`/api/products/${encodeURIComponent(product.id)}`, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(5000) })
        .then(response => response.ok ? response.json() : null).then(data => {
          if (!data || data.id !== product.id || version !== accountVersion || !section.isConnected) return;
          section.querySelector('.product-thumbnail')?.replaceWith(thumbnail(data.image_url, product.name));
        }).catch(() => {});
    }
    return append(section);
  }
  function renderProducts(items) {
    const unique = [...new Map(items.map(item => [item.product.id, item])).values()];
    if (unique.length < 2) return unique.map(item => renderProduct(item.product, item.label, item.callback));
    const group = node('section', undefined, 'product-results');
    group.setAttribute('aria-label', '商品查询结果');
    group.append(node('h2', `共找到 ${unique.length} 件商品`));
    const track = node('div', undefined, 'product-track');
    track.tabIndex = 0; track.setAttribute('aria-label', '左右滚动查看商品');
    group.append(track); append(group);
    for (const item of unique) track.append(renderProduct(item.product, item.label, item.callback));
    // A result list is context, not a choice of its last item.
    byId('current-context').replaceChildren(node('p', `${unique.length} 件候选商品，可在聊天中查看详情。`, 'context-placeholder'));
    return group;
  }
  function openPanel(title) {
    closePanels();
    byId('utility-title').textContent = title;
    const content = byId('utility-content'); content.replaceChildren();
    if (!byId('utility-panel').open) byId('utility-panel').showModal();
    return content;
  }
  function closeUtility() { byId('utility-panel').close(); }
  function serviceState(value) {
    const { state = 'AI_ACTIVE', title = '智能服务中', copy = '', canSend = true, pending = false } = value;
    document.querySelector('.heading-title p').textContent = ['WAITING_HUMAN', 'HUMAN_ACTIVE', 'CLOSED'].includes(state) ? '人工客服 · 工单留言' : '商品、订单、售后，随时帮你解答';
    operationState = state;
    byId('service-state').dataset.state = state;
    byId('service-state').hidden = state === 'AI_ACTIVE' && !copy;
    byId('service-state-title').textContent = title;
    byId('service-state-copy').textContent = copy;
    byId('assistant-status-label').textContent = title;
    byId('message-input').disabled = !canSend || pending;
    byId('message-input').maxLength = ['WAITING_HUMAN', 'HUMAN_ACTIVE'].includes(state) ? 1200 : 2000;
    byId('input-count').textContent = `${byId('message-input').value.length} / ${byId('message-input').maxLength}`;
    byId('message-input').placeholder = ['WAITING_HUMAN', 'HUMAN_ACTIVE'].includes(state) ? '补充问题，将留言发送给跟进此事的人工客服…' : state === 'CLOSED' ? '处理已结束，可返回智能客服或在工单中继续补充。' : '描述你的问题，或选择一笔订单开始咨询…';
    byId('resume-ai').hidden = !['WAITING_HUMAN', 'HUMAN_ACTIVE', 'CLOSED'].includes(state);
    byId('resume-ai').disabled = pending;
    byId('refresh-handoff').hidden = !value.caseId;
    byId('refresh-handoff').disabled = pending;
    byId('support-human').disabled = pending || state === 'HANDOFF_REQUESTED';
    byId('send-button').disabled = querying || pending || !canSend || !byId('message-input').value.trim();
  }
  function evidence(result, parts = [], labels = {}, statuses = {}) {
    const details = node('details', undefined, 'reply-evidence');
    details.append(node('summary', '答复依据'));
    const content = node('div', undefined, 'reply-meta');
    if (result.queried_at) content.append(node('p', `查询时间：${result.queried_at}`));
    if (result.request_id) content.append(node('p', `请求标识：${result.request_id}`));
    for (const part of parts) {
      if (!Object.hasOwn(labels, part.source)) continue;
      content.append(node('p', `${labels[part.source]}：${statuses[part.status] || '暂不可用'}`));
      if (part.queried_at) content.append(node('p', `查询时间：${part.queried_at}`));
    }
    details.append(content); host.messages.append(details);
  }
  function renderOrders(items, total) {
    orders = new Map();
    const list = byId('sidebar-orders'); list.replaceChildren();
    for (const item of items) {
      if (uuid.test(item?.id || '') && Object.hasOwn(statusLabels, item.status)) orders.set(item.id, item);
    }
    byId('order-count').textContent = `${Number.isInteger(total) ? total : orders.size} 笔订单`;
    if (!orders.size) {
      list.append(node('div', '还没有订单，先去商城逛逛吧。', 'empty-state'));
      return;
    }
    for (const order of [...orders.values()].slice(0, 5)) {
      const section = node('section', undefined, 'sidebar-order'); section.dataset.orderId = order.id;
      section.classList.toggle('is-selected', order.id === selectedOrder);
      const heading = node('div', undefined, 'sidebar-order-top');
      heading.append(node('span', `尾号 ${order.id.slice(-8)}`), node('span', statusLabels[order.status], 'status-badge'));
      const first = order.items?.[0];
      productLine(section, first?.name || '商城订单', Array.isArray(order.items) ? `共 ${order.items.reduce((sum, item) => sum + (Number.isInteger(item.quantity) ? item.quantity : 0), 0)} 件商品` : '查看订单详情', first?.image_url, order.total);
      section.prepend(heading);
      const bottom = node('div', undefined, 'sidebar-order-bottom');
      bottom.append(action('发送给智能客服', () => host.selectOrder(order.id)), localLink('查看订单', `/?view=orders&order=${encodeURIComponent(order.id)}`));
      section.append(bottom); list.append(section);
    }
  }
  function ordersError(message) {
    byId('sidebar-orders').replaceChildren(node('p', message || '订单暂时加载失败，请点击刷新重试。', 'empty-state'));
    byId('order-count').textContent = '暂未加载';
  }
  function loadEntries() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(recentKey) || '[]');
      entries = Array.isArray(saved) ? saved.filter(item => item.owner === owner && uuid.test(item.id) && Number.isFinite(item.at) && Date.now() - item.at < 86400000).slice(0, 10) : [];
    } catch { entries = []; }
    renderHistoryList();
  }
  function saveEntries() {
    try { sessionStorage.setItem(recentKey, JSON.stringify(entries)); } catch { /* The server remains the history authority. */ }
    renderHistoryList();
  }
  function renderHistoryList() {
    const list = byId('conversation-list'); list.replaceChildren();
    if (!entries.length) { list.append(node('p', '暂无可查看的近期咨询。', 'sidebar-empty')); return; }
    for (const item of entries) {
      const button = node('button', undefined, 'history-entry'); button.type = 'button';
      button.dataset.consultationId = item.id;
      button.append(icon('chat-icon'), node('span', item.title), node('time', timestamp(item.at)));
      button.setAttribute('aria-label', `查看${item.title} ${timestamp(item.at)}`);
      button.addEventListener('click', () => openHistory(item));
      list.append(button);
    }
  }
  function remember(context, text = '') {
    if (!uuid.test(context?.consultation_id || '')) return;
    currentId = context.consultation_id;
    const prior = entries.find(item => item.id === currentId);
    const title = prior?.title || (/退款|售后|退货|退换|发票/.test(text) ? '售后服务咨询' : /订单|物流|发货/.test(text) ? '订单与物流咨询' : '购物咨询');
    entries = [{ id: currentId, owner, title, at: Date.now() }, ...entries.filter(item => item.id !== currentId)].slice(0, 10);
    saveEntries();
  }
  function showCurrent() {
    historyVersion += 1;
    byId('history-view').hidden = true;
    host.messages.hidden = false;
    byId('composer').hidden = false;
    byId('current-conversation').setAttribute('aria-current', 'page');
    byId('current-conversation').classList.add('is-active');
    byId('conversation-list').querySelectorAll('button').forEach(button => button.classList.remove('is-selected'));
  }
  async function openHistory(item) {
    if (host.busy()) return;
    const version = ++historyVersion;
    closePanels();
    host.messages.hidden = true;
    byId('composer').hidden = true;
    byId('history-view').hidden = false;
    byId('history-title').textContent = item.title;
    byId('history-retention').textContent = '仅查看服务端仍保留的对话，不重复执行历史操作。';
    byId('current-conversation').removeAttribute('aria-current');
    byId('current-conversation').classList.remove('is-active');
    byId('conversation-list').querySelectorAll('button').forEach(button => button.classList.toggle('is-selected', button.dataset.consultationId === item.id));
    byId('history-transcript').replaceChildren(node('p', '正在加载咨询记录…', 'history-empty'));
    try {
      const result = await host.lane(async () => {
        const response = await fetch(`/api/customer-service/history?consultation_id=${encodeURIComponent(item.id)}`, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(10000) });
        if (!response.ok) {
          if ([401, 403, 410].includes(response.status)) { entries = entries.filter(entry => entry.id !== item.id); saveEntries(); }
          throw new Error('这次咨询已过期，或当前登录账号无法查看。');
        }
        return response.json();
      });
      if (version !== historyVersion) return;
      byId('history-retention').textContent = result.retention || '仅展示服务端当前仍保留的记录。';
      const transcript = byId('history-transcript'); transcript.replaceChildren();
      for (const line of Array.isArray(result.items) ? result.items : []) {
        if (!['user', 'assistant'].includes(line.role) || typeof line.text !== 'string') continue;
        const row = node('div', undefined, line.role === 'user' ? 'message user history-message' : 'message history-message');
        row.append(node('div', line.text, 'bubble')); transcript.append(row);
      }
      if (!transcript.children.length) transcript.append(node('p', '这次咨询暂没有保留的对话。', 'history-empty'));
    } catch (error) {
      if (version === historyVersion) byId('history-transcript').replaceChildren(node('p', error.message, 'history-empty'));
    }
  }
  function closePanels() {
    document.body.classList.remove('navigation-open', 'context-open');
    byId('navigation-toggle').setAttribute('aria-expanded', 'false');
    byId('context-toggle').setAttribute('aria-expanded', 'false');
    byId('panel-scrim').hidden = true;
  }
  function togglePanel(name) {
    const opening = !document.body.classList.contains(`${name}-open`);
    closePanels();
    if (opening) {
      document.body.classList.add(`${name}-open`);
      byId(name === 'navigation' ? 'navigation-toggle' : 'context-toggle').setAttribute('aria-expanded', 'true');
      byId('panel-scrim').hidden = false;
    }
  }
  function init(options) {
    host = options;
    document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
      showCurrent(); closePanels(); host.send(button.dataset.prompt);
    }));
    document.querySelectorAll('[data-product-consultation]').forEach(button => button.addEventListener('click', () => byId('start-consultation').click()));
    byId('utility-close').addEventListener('click', closeUtility);
    byId('utility-panel').addEventListener('click', event => { if (event.target === byId('utility-panel') && event.clientX > 0) { const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeUtility(); } });
    byId('resume-ai').addEventListener('click', () => window.ShopSupport.resumeAI());
    byId('refresh-handoff').addEventListener('click', () => window.ShopSupport.refresh());
    byId('new-conversation').addEventListener('click', () => {
      if (host.busy()) return;
      showCurrent(); closePanels(); host.restart();
      currentId = null; selectedOrder = null;
      byId('current-context').replaceChildren(node('p', '选择商品或订单，开启新的咨询。', 'context-placeholder'));
      byId('sidebar-orders').querySelectorAll('.is-selected').forEach(item => item.classList.remove('is-selected'));
    });
    byId('current-conversation').addEventListener('click', () => { showCurrent(); closePanels(); window.ShopSupport.resumeAI(); });
    byId('history-return').addEventListener('click', showCurrent);
    byId('refresh-orders').addEventListener('click', async event => {
      const control = event.currentTarget;
      if (control.disabled) return;
      control.disabled = true; control.setAttribute('aria-busy', 'true');
      try { await host.refreshOrders(); }
      finally { control.disabled = false; control.removeAttribute('aria-busy'); }
    });
    byId('navigation-toggle').addEventListener('click', () => togglePanel('navigation'));
    byId('context-toggle').addEventListener('click', () => togglePanel('context'));
    byId('context-close').addEventListener('click', closePanels);
    byId('panel-scrim').addEventListener('click', closePanels);
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closePanels(); });
    byId('privacy-info').addEventListener('click', () => {
      openPanel('隐私与记录说明').append(node('p', byId('support-context-notice').textContent));
    });
    document.querySelector('.history').addEventListener('click', () => {
      const item = entries.find(entry => entry.id === currentId) || entries[0];
      if (item && host.integrated()) openHistory(item);
      else host.append('暂无可查看的历史咨询。开始咨询后，这里会展示服务端仍保留的记录。');
    });
    document.querySelectorAll('.service-nav button, #support-human').forEach(button => button.addEventListener('click', () => { showCurrent(); closePanels(); }));
    loadEntries();
    try {
      if (document.referrer && new URL(document.referrer).origin === location.origin && new URL(document.referrer).pathname !== '/customer-service.html' && !new URL(document.referrer).searchParams.has('customer-service-return')) {
        const previous = new URL(document.referrer);
        sessionStorage.setItem(returnKey, previous.pathname + previous.search + previous.hash);
      }
      const saved = sessionStorage.getItem(returnKey);
      if (saved?.startsWith('/') && !saved.startsWith('//')) {
        const target = new URL(saved, location.origin);
        if (target.origin === location.origin && target.pathname !== '/customer-service.html') document.querySelectorAll('.storefront-return').forEach(link => { link.href = target.pathname + target.search + target.hash; });
      }
    } catch { /* Returning to the storefront root remains available. */ }
  }
  window.ShopWorkspace = {
    init, order: renderOrder, product: renderProduct, products: renderProducts, evidence, orders: renderOrders, ordersError, remember, showCurrent, openPanel, closePanel: closeUtility, serviceState,
    account(user) {
      const nextOwner = user?.id || 'guest';
      if (owner !== nextOwner) { historyVersion += 1; orders.clear(); selectedOrder = null; currentId = null; accountVersion += 1; productCards.clear(); closeUtility(); window.ShopSupport.reset(); }
      owner = nextOwner; loadEntries();
      byId('account-label').textContent = user ? (user.role === 'buyer' ? '商城买家' : '管理员') : '登录 / 注册';
      if (user?.role !== 'buyer') {
        byId('sidebar-orders').replaceChildren(node('p', user ? '请切换买家账号查看本人订单。' : '登录商城账号后，可在这里选择本人订单。', 'empty-state'));
        byId('order-count').textContent = user ? '需要买家账号' : '登录后查看';
        const login = localLink('登录查看订单 →', '/?customer-service-return=1'); login.id = 'sidebar-login';
        if (!user) byId('sidebar-orders').append(login);
        byId('order-hints').replaceChildren(); byId('order-hints').hidden = true;
      }
    },
    busy(value) {
      querying = value;
      byId('reply-status').hidden = !value;
      byId('messages').setAttribute('aria-busy', String(value));
      byId('new-conversation').disabled = value;
      byId('send-button').disabled = value || byId('message-input').disabled || operationState === 'CLOSED' || !byId('message-input').value.trim();
      if (operationState === 'AI_ACTIVE') byId('assistant-status-label').textContent = value ? '正在查询' : byId('service-state').hidden ? '智能服务中' : byId('service-state-title').textContent;
    },
    operation(title, copy = '') { if (operationState === 'AI_ACTIVE') serviceState({ state: 'AI_ACTIVE', title, copy }); },
    changed() { host.messages.scrollTop = host.messages.scrollHeight; },
    service(card) {
      const data = card.type === 'support_case' ? card.case : card.type === 'service_progress' ? card.progress : null;
      if (!data) return;
      const section = node('section', undefined, 'context-case');
      section.append(node('h3', card.type === 'support_case' ? '服务跟进' : '服务申请进度'));
      if (data.id) section.append(node('p', ['resolved', 'rejected'].includes(data.status) ? '本次处理已结束' : data.assigned === true ? '人工已接手此事' : '等待人工接手'));
      if (Array.isArray(data.items)) section.append(node('p', data.items.length ? `${data.items.length} 条服务申请，详见对话中的进度卡。` : '暂无匹配的服务申请。'));
      byId('current-context').querySelector('.context-case')?.remove();
      byId('current-context').append(section);
    },
    reset() { selectedOrder = null; productCards.clear(); byId('order-picker').open = true; byId('current-context').replaceChildren(node('p', '请重新选择本人订单或商品。', 'context-placeholder')); },
  };
})();
