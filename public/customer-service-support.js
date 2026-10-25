/* Structured service actions and case follow-up; generated text never executes actions. */
(() => {
  const labels = { human_handoff: '人工客服', complaint: '投诉处理', shipping_reminder: '催发货',
    address_change: '修改收货地址', invoice: '发票申请', return: '退货申请', exchange: '换货申请',
    refund: '退款申请', missing: '少件处理', damage: '破损处理', wrong_item: '发错货处理',
    warranty: '质保查询', replacement: '补发登记', compensation: '补偿协商' };
  const statuses = { open: '等待接手', in_progress: '人工跟进中', waiting_buyer: '需要你补充', resolved: '处理结束', rejected: '申请未通过' };
  const terminal = data => ['resolved', 'rejected'].includes(data.status);
  let host;
  let feedbackOffered = false;
  let activeCase = null;
  let requested = false;
  let previewOnly = false;
  let pending = false;
  let generation = 0;
  const caseViews = new Map();
  const previews = new Map();
  const uncertain = new Map();
  const requestViews = new Map();

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(text, action) {
    const node = element('button', text, 'quick-question'); node.type = 'button';
    node.addEventListener('click', action);
    return node;
  }
  function notice(section, text, tone = 'info') {
    let line = section.querySelector(':scope > .action-feedback');
    if (!line) { line = element('p', undefined, 'action-feedback'); line.setAttribute('role', 'status'); section.append(line); }
    line.textContent = text; line.dataset.tone = tone;
  }
  async function action(control, section, task, loading = '正在处理…', success = '') {
    if (control.disabled) return;
    const label = control.textContent;
    control.disabled = true; control.textContent = loading; control.setAttribute('aria-busy', 'true');
    notice(section, loading);
    try { await task(); if (section.isConnected && success) notice(section, success, 'success'); }
    catch (error) { if (section.isConnected) notice(section, error.message, 'error'); }
    finally { control.disabled = false; control.textContent = label; control.removeAttribute('aria-busy'); }
  }
  async function request(path, method = 'GET', body) {
    const version = generation;
    return host.lane(async () => {
      if (version !== generation) throw new Error('咨询或账号已变化，请重新打开此项服务。');
      const headers = {};
      if (method !== 'GET') {
        const response = await fetch('/api/auth/csrf', { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw Object.assign(new Error('请登录商城买家账号后继续。'), { status: response.status });
        headers['X-CSRF-Token'] = (await response.json()).csrf_token;
        if (body !== undefined) headers['Content-Type'] = 'application/json';
      }
      if (version !== generation) throw new Error('咨询或账号已变化，请重新打开此项服务。');
      let response;
      try {
        response = await fetch(`/api/customer-service/${path}`, { method, headers, credentials: 'same-origin', cache: 'no-store',
          signal: AbortSignal.timeout(10000), ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
      } catch {
        throw Object.assign(new Error(method === 'GET' ? '暂时未能加载，请点击重试。' : '发送结果待确认，请先刷新记录核对；不会自动重发。'), { uncertain: method !== 'GET' });
      }
      if (version !== generation) throw new Error('咨询或账号已变化，请重新打开此项服务。');
      if (response.status === 204) return null;
      const result = await response.json().catch(() => null);
      const expectsCase = method === 'POST' && (path === 'requests' || /^cases\/[^/]+\/(replies|share-context)$/.test(path));
      const validCase = result?.case && typeof result.case.id === 'string' && Object.hasOwn(labels, result.case.kind)
        && Object.hasOwn(statuses, result.case.status) && Array.isArray(result.case.messages) && typeof result.case.assigned === 'boolean';
      if (response.ok && expectsCase && !validCase) {
        throw Object.assign(new Error('发送结果待确认，请先刷新记录核对；不会自动重发。'), { uncertain: true });
      }
      if (!response.ok || !result) {
        const unknown = method !== 'GET' && (response.status >= 500 || [408, 425].includes(response.status) || response.ok);
        const delay = Number(response.headers.get('Retry-After'));
        const message = unknown ? '发送结果待确认，请先刷新记录核对；不会自动重发。'
          : response.status >= 500 ? '暂时未能加载，请点击重新加载重试。'
          : response.status === 429 ? (Number.isInteger(delay) && delay > 0 ? `操作较频繁，请在 ${delay} 秒后重试。` : '操作较频繁，请稍后重试。')
          : [401, 403, 410].includes(response.status) ? '记录已过期或当前账号无法访问，请重新登录后查看。'
          : typeof result?.detail === 'string' ? result.detail : '本次操作未完成，请刷新后重试。';
        if ([401, 403, 410].includes(response.status)) host.invalidate();
        throw Object.assign(new Error(message), { status: response.status, uncertain: unknown });
      }
      return result;
    });
  }
  function panel(title, container) {
    const section = element('section', undefined, 'support-card'); section.append(element('h2', title));
    if (container) container.append(section);
    else { host.activate(); host.messages.append(section); }
    return section;
  }
  function utility(title) { return window.ShopWorkspace.openPanel(title); }
  function field(form, title, tag = 'input') {
    const label = element('label', title), input = element(tag); input.setAttribute('aria-label', title);
    if (tag === 'input') input.type = 'text'; label.append(input); form.append(label); return input;
  }
  function checkbox(form, title, checked = false) {
    const label = element('label'), input = element('input'); input.type = 'checkbox'; input.checked = checked;
    label.append(input, document.createTextNode(title)); form.append(label); return input;
  }
  function summary(section, data, includeHistory = true) {
    if (!data || typeof data !== 'object') return;
    section.append(element('p', data.concern || '请补充你希望客服协助的问题。', 'handoff-concern'));
    const facts = Array.isArray(data.verified_facts) ? data.verified_facts : [];
    const orderStatus = { pending_payment: '待付款', pending_shipment: '待发货', pending_receipt: '待收货', completed: '已完成', closed: '已关闭' };
    for (const fact of facts) {
      const values = [];
      if (typeof fact.order_id === 'string') values.push(`订单尾号 ${fact.order_id.slice(-4)}`);
      if (Object.hasOwn(orderStatus, fact.status)) values.push(orderStatus[fact.status]);
      if (typeof fact.total === 'string') values.push(`¥${fact.total}`);
      if (values.length) section.append(element('p', values.join(' · ')));
    }
    if (includeHistory && Array.isArray(data.history) && data.history.length) {
      const details = element('details'); details.append(element('summary', '查看聊天片段'));
      for (const line of data.history) details.append(element('p', `${line.role === 'user' ? '你' : '智能客服'}：${line.text}`));
      section.append(details);
    }
  }
  function syncState(note = '') {
    let state = 'AI_ACTIVE', title = '智能服务中', copy = note, canSend = true;
    if (activeCase) {
      state = terminal(activeCase) ? 'CLOSED' : activeCase.assigned === true ? 'HUMAN_ACTIVE' : 'WAITING_HUMAN';
      title = terminal(activeCase) ? statuses[activeCase.status] : activeCase.assigned === true ? '人工已接手' : '等待人工接手';
      copy = note || (terminal(activeCase) ? '本次工单处理已结束。你可以返回智能客服，或在工单中继续补充。'
        : activeCase.status === 'waiting_buyer' ? '客服需要你补充资料，下方留言会发送到本次工单。'
        : activeCase.assigned === true ? '客服正在通过工单跟进，下方可继续留言。回复后请刷新进度查看。'
        : '已收到转人工请求，正在等待客服接手。你可以继续补充问题。');
      canSend = !terminal(activeCase) && !uncertain.has(activeCase.id);
      if (uncertain.has(activeCase.id)) copy = uncertain.get(activeCase.id);
    } else if (requested || previewOnly) {
      state = 'HANDOFF_REQUESTED'; title = requested ? '正在申请人工服务' : '转人工需要登录';
      copy = requested ? '正在提交请求，请稍候…' : '咨询摘要已准备，登录商城后才能登记到人工队列。';
      canSend = !requested;
    }
    window.ShopWorkspace.serviceState({ state, title, copy, canSend, pending, caseId: activeCase?.id });
    window.ShopWorkspace.busy(host.busy());
  }
  function adopt(data, activate = true) {
    if (activate || activeCase?.id === data.id) activeCase = data;
    if (activate) { requested = false; previewOnly = false; }
    const section = caseViews.get(data.id);
    if (section?.isConnected) fillCase(section, data);
    window.ShopWorkspace.service({ type: 'support_case', case: data });
    syncState();
  }
  function fillCase(section, data) {
    section.replaceChildren(); section.dataset.caseId = data.id;
    const heading = element('div', undefined, 'card-heading');
    const ended = terminal(data);
    const status = ended ? statuses[data.status] : data.assigned === true ? (data.status === 'waiting_buyer' ? '需要你补充' : '人工已接手') : '等待接入';
    heading.append(element('h2', labels[data.kind]), element('span', status, 'status-badge')); section.append(heading);
    section.append(element('p', ended ? '本次处理已结束，可查看回复或继续补充问题。'
      : data.assigned === true ? '客服已接手此事，将通过工单回复你。'
      : '已收到你的请求，正在安排客服接手。你可以继续补充问题。'));
    const steps = element('ul', undefined, 'handoff-steps');
    steps.append(element('li', '已整理本次咨询摘要'));
    if (data.order_id || data.summary?.verified_facts?.length) steps.append(element('li', '已准备相关订单信息'));
    steps.append(element('li', ended ? '本次工单处理已结束' : data.assigned === true ? '客服已确认接手' : '等待客服确认接手'));
    section.append(steps);
    const replies = Array.isArray(data.messages) ? data.messages : [];
    if (replies.length) {
      const thread = element('div', undefined, 'case-thread'); thread.setAttribute('aria-label', '工单留言');
      for (const message of replies.slice(-6)) {
        const row = element('div', undefined, message.role === 'staff' ? 'case-message staff' : 'case-message');
        row.append(element('strong', message.role === 'staff' ? '人工客服' : '你'), element('p', message.text)); thread.append(row);
      }
      section.append(thread);
    }
    section.append(element('p', data.summary?.history_shared ? '你已同意共享的聊天片段已交给客服。' : '分享聊天记录前会征求你的确认。', 'muted'));
    const actions = element('div', undefined, 'card-actions');
    actions.append(button('查看交接内容', () => showSummary(data)), button('补充问题', () => supplement(data)));
    const refreshButton = button('刷新状态', () => action(refreshButton, section, async () => {
      const current = await refreshCase(data.id);
      if (current && section.isConnected) fillCase(section, current);
    }, '正在刷新…', '状态已更新。'));
    actions.append(refreshButton); section.append(actions);
    if (uncertain.has(data.id)) {
      notice(section, uncertain.get(data.id), 'error');
      const checked = button('已核对留言，继续补充', () => { uncertain.delete(data.id); adopt(data); });
      section.append(checked);
    }
  }
  function renderCase(data, container, activate = true) {
    if (!data || typeof data.id !== 'string' || !Object.hasOwn(labels, data.kind) || !Object.hasOwn(statuses, data.status)) return;
    let section = !container ? caseViews.get(data.id) : null;
    if (!section?.isConnected) {
      section = element('section', undefined, 'support-card handoff-card'); section.setAttribute('aria-label', labels[data.kind]);
      if (container) container.append(section);
      else { host.activate(); host.messages.append(section); caseViews.set(data.id, section); }
    }
    fillCase(section, data);
    if (!container) adopt(data, activate);
  }
  async function refreshCase(id) {
    const version = generation;
    const result = await request('cases');
    if (version !== generation) return;
    const current = result.items.find(item => item.id === id);
    if (!current) throw new Error('暂未找到此工单，请在“我的工单”核对；这不表示处理已结束。');
    adopt(current, false);
    return current;
  }
  async function refresh() {
    if (!activeCase || pending) return;
    const control = document.getElementById('refresh-handoff');
    const section = caseViews.get(activeCase.id) || document.getElementById('service-state');
    const id = activeCase.id;
    await action(control, section, () => refreshCase(id), '正在刷新…', '状态已更新。');
  }
  function supplement(data) {
    if (pending || host.busy()) return;
    if (!terminal(data) && !uncertain.has(data.id)) {
      renderCase(data); window.ShopWorkspace.closePanel(); window.ShopWorkspace.showCurrent(); syncState();
      document.getElementById('message-input').focus(); return;
    }
    const section = panel('补充工单信息', utility('继续沟通'));
    if (uncertain.has(data.id)) { notice(section, uncertain.get(data.id), 'error'); section.append(button('刷新记录核对', () => cases())); return; }
    const form = element('form'), input = field(form, '补充工单信息', 'textarea'); input.maxLength = 1200; input.required = true;
    section.append(element('p', '发送补充后，客服将重新跟进此工单。'));
    const submit = element('button', '发送补充'); submit.type = 'submit'; form.append(submit); section.append(form);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (pending || host.busy()) return;
      activeCase = data;
      const result = await sendSupplement(input.value, section);
      if (result) { input.value = ''; form.remove(); notice(section, '补充已发送，客服将继续跟进。', 'success'); }
    });
  }
  async function sendSupplement(text, container) {
    if (!activeCase || pending || uncertain.has(activeCase.id) || !text.trim()) return false;
    if (text.length > 1200) { syncState('补充内容最多1200字，请精简后发送。'); return false; }
    const target = activeCase.id, version = generation;
    const section = container || caseViews.get(target) || document.getElementById('service-state');
    const control = container?.querySelector('button[type="submit"]');
    if (control) { control.disabled = true; control.textContent = '正在发送…'; }
    pending = true; syncState('正在发送补充，请稍候…'); notice(section, '正在发送补充…');
    try {
      const result = await request(`cases/${target}/replies`, 'POST', { text: text.trim() });
      if (version !== generation) return false;
      adopt(result.case); notice(section, '补充已发送。', 'success'); return true;
    } catch (error) {
      if (version !== generation) return false;
      if (error.uncertain) {
        uncertain.set(target, error.message);
        const view = caseViews.get(target);
        if (view && activeCase?.id === target) fillCase(view, activeCase);
      }
      notice(section, error.message, 'error'); return false;
    } finally {
      if (version === generation) {
        pending = false; syncState();
        if (control) { control.disabled = uncertain.has(target); control.textContent = uncertain.has(target) ? '结果待核对' : '发送补充'; }
      }
    }
  }
  async function showSummary(data) {
    const section = panel('交接内容', utility('人工客服 · 交接内容'));
    summary(section, data.summary);
    section.append(element('p', '摘要用于跟进本次问题。工单保留30天，聊天片段仅在你确认后共享。', 'muted'));
    const preview = previews.get(data.id);
    if (!data.summary?.history_shared && preview) section.append(button('查看并选择共享聊天记录', () => sharePreview(data.id)));
    else if (data.summary?.history_shared) section.append(element('p', '已共享经你确认的必要聊天片段。'));
  }
  async function sharePreview(id) {
    const context = host.context();
    const section = panel('确认共享内容', utility('共享聊天记录'));
    if (!context) { notice(section, '当前咨询已过期，请重新开始咨询后再共享。', 'error'); return; }
    const version = generation;
    const load = async () => {
      const result = await request(`history?consultation_id=${encodeURIComponent(context.consultation_id)}`);
      if (version !== generation || !section.isConnected) return;
      section.replaceChildren(element('h2', '确认共享内容'), element('p', '以下为本次最近的必要聊天片段，确认后交给跟进此事的客服。'));
      const transcript = element('div', undefined, 'share-transcript');
      for (const line of result.items.slice(-12)) transcript.append(element('p', `${line.role === 'user' ? '你' : '智能客服'}：${line.text}`));
      section.append(transcript);
      const share = button('同意共享以上必要对话', async () => {
        if (share.disabled) return;
        share.disabled = true; share.textContent = '正在共享…'; notice(section, '正在共享…');
        try {
          if (host.context()?.consultation_id !== context.consultation_id) throw new Error('咨询已变化，请重新查看共享内容。');
          const result = await request(`cases/${id}/share-context`, 'POST', { consultation_id: context.consultation_id, consent: true });
          if (version !== generation || !section.isConnected) return;
          adopt(result.case, false); share.textContent = '已共享'; notice(section, '已将你确认的必要聊天片段共享给客服。', 'success');
        } catch (error) {
          if (version !== generation || !section.isConnected) return;
          notice(section, error.message, 'error');
          if (error.uncertain) { share.textContent = '结果待核对'; section.append(button('刷新工单核对共享状态', () => cases())); }
          else { share.disabled = false; share.textContent = '重试共享'; }
        }
      });
      section.append(share);
    };
    const retry = button('重试加载', () => action(retry, section, load, '正在加载…')); section.append(retry);
    await action(retry, section, load, '正在加载…');
  }
  function previewHandoff(data) {
    if (data.case_id) {
      previews.set(data.case_id, data);
      if (caseViews.get(data.case_id)?.isConnected) return;
      const section = panel('人工客服 · 交接内容');
      section.append(element('p', '已准备交接摘要，请查看工单确认受理状态。'), button('查看我的工单', cases), button('查看并选择共享聊天记录', () => sharePreview(data.case_id)));
      return;
    }
    previewOnly = true;
    const section = panel('人工客服 · 交接准备');
    section.append(element('p', '已整理本次咨询摘要。登录后才能登记转人工请求，当前尚未进入人工队列。'));
    section.append(button('查看交接内容', () => { const view = panel('本次问题', utility('交接内容')); summary(view, data); }));
    if (!data.case_id) section.append(button('登录后继续转人工', () => window.location.assign('/?customer-service-return=1')));
    syncState();
  }
  async function handoff() {
    if (pending || requested || host.busy()) return;
    if (activeCase) { window.ShopWorkspace.showCurrent(); await refresh(); return; }
    requested = true; previewOnly = false; syncState();
    const version = generation;
    try { await host.send('我要转人工'); }
    finally {
      if (version === generation) { requested = false; syncState(activeCase || previewOnly ? '' : '转人工暂未确认，请稍后重试或查看我的工单。'); }
    }
  }
  async function requestForm(card) {
    if (!Object.hasOwn(labels, card.kind) || pending || host.busy()) return;
    const key = `${card.kind}:${card.order_id || ''}`;
    const existing = requestViews.get(key);
    if (existing) { utility('确认服务申请').append(existing); return; }
    const section = panel(`${labels[card.kind]} · 申请预览`, utility('确认服务申请'));
    requestViews.set(key, section);
    if (card.order_id) section.append(element('p', `订单尾号 ${card.order_id.slice(-4)}`));
    section.append(element('p', '提交后由客服审核办理。申请登记不代表已退款、发货或补偿。'));
    const form = element('form'), concern = field(form, '问题和期望处理方式', 'textarea');
    concern.maxLength = 1200; concern.required = true; concern.value = card.concern || '';
    let address, invoice;
    if (card.kind === 'address_change') {
      address = field(form, '选择商城地址簿中的新地址', 'select'); const empty = element('option', '请选择'); empty.value = ''; address.append(empty); address.required = true;
      try {
        const response = await fetch('/api/addresses', { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error();
        for (const item of (await response.json()).items) { const option = element('option', `${item.recipient_name} · ${item.province}${item.city}${item.district}${item.detail}`); option.value = item.id; address.append(option); }
      } catch { notice(section, '地址簿暂不可用，请先在商城维护地址后重试。', 'error'); }
      const link = element('a', '管理商城地址簿'); link.href = '/?view=account'; section.append(link);
    }
    if (card.kind === 'invoice') { invoice = field(form, '发票抬头'); invoice.required = true; invoice.maxLength = 120; }
    const history = checkbox(form, '同意共享本次必要对话片段（可选）');
    const consent = checkbox(form, '我已核对申请内容，同意交给客服并保存30天'); consent.required = true;
    const submit = element('button', '确认提交申请'); submit.type = 'submit'; form.append(submit); section.append(form);
    const requestId = crypto.randomUUID(), version = generation;
    let payload = null;
    form.addEventListener('submit', async event => {
      event.preventDefault(); const context = host.context();
      if (!context || submit.disabled) return;
      payload ||= { ...context, client_request_id: requestId, kind: card.kind, concern: concern.value, share_history: history.checked, consent: consent.checked,
        ...(card.order_id && !['complaint', 'human_handoff'].includes(card.kind) ? { selected_order_id: card.order_id } : {}),
        ...(address ? { address_id: address.value } : {}), ...(invoice ? { invoice_title: invoice.value } : {}) };
      submit.disabled = true; submit.textContent = '正在提交…'; notice(section, '正在提交申请…');
      try {
        const result = await request('requests', 'POST', payload);
        if (version !== generation) return;
        renderCase(result.case, undefined, ['human_handoff', 'complaint'].includes(card.kind));
        form.remove(); notice(section, '申请已登记，等待客服审核；尚未执行业务操作。', 'success');
        section.append(button('返回咨询', () => window.ShopWorkspace.closePanel()));
      } catch (error) {
        if (version !== generation) return;
        notice(section, error.message, 'error'); submit.disabled = false;
        if (error.uncertain) {
          form.querySelectorAll('input, textarea, select').forEach(input => { input.disabled = true; });
          submit.textContent = '重试同一申请';
          section.append(button('先查看我的工单核对', () => cases()));
        } else { payload = null; submit.textContent = '重试提交申请'; }
      }
    });
    const context = host.context();
    if (context) {
      try {
        const result = await request(`history?consultation_id=${encodeURIComponent(context.consultation_id)}`);
        if (version !== generation) return;
        const details = element('details'); details.append(element('summary', '查看可选共享的聊天片段'));
        for (const line of result.items.slice(-12)) details.append(element('p', `${line.role === 'user' ? '你' : '智能客服'}：${line.text}`)); section.append(details);
      } catch { history.disabled = true; }
    }
  }
  function sizeAdvice(card) {
    const advice = card.advice; if (!advice || !Array.isArray(advice.sizes)) return;
    const section = panel(`${card.product_name} · 尺码建议`);
    const names = { height_cm: '身高（厘米）', weight_kg: '体重（公斤）', chest_cm: '胸围（厘米）', waist_cm: '腰围（厘米）' };
    section.append(element('p', '仅按商品已发布尺码范围匹配，实际穿着需结合版型确认。本次尺寸随咨询过期，不进入长期推荐偏好。'));
    for (const row of advice.sizes) section.append(element('p', `${row.label}：${Object.entries(row.measurements).map(([key, bounds]) => `${names[key] || key} ${bounds.join('–')}`).join('，')}`));
    for (const text of [...(advice.recommendations || []), ...(advice.needs || [])]) section.append(element('p', text));
    if (!advice.sizes.length) return;
    const form = element('form'), keys = [...new Set(advice.sizes.flatMap(row => Object.keys(row.measurements)))].filter(key => Object.hasOwn(names, key));
    const inputs = keys.map(key => { const input = field(form, names[key]); input.type = 'number'; input.min = '1'; input.max = key === 'weight_kg' ? '400' : '250'; input.step = '0.1'; input.required = true; return { key, input }; });
    const submit = element('button', '按已发布尺码表核对'); submit.type = 'submit'; form.append(submit); section.append(form);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (submit.disabled || !host.context()) return;
      await action(submit, section, () => host.send(inputs.map(({ key, input }) => `${names[key].split('（')[0]}${input.value}${key === 'weight_kg' ? '公斤' : '厘米'}`).join('，') + '，请继续核对尺码'), '正在核对…');
    });
  }
  function serviceProgress(data) {
    if (!data || !Array.isArray(data.items)) return;
    const section = panel('服务申请进度'); section.append(element('p', data.notice));
    if (!data.items.length) section.append(element('p', '这笔订单暂无匹配的有效服务申请。'));
    for (const item of data.items) {
      section.append(element('h3', `${labels[item.kind] || item.kind_label} · ${statuses[item.status] || '状态待确认'}`));
      if (item.latest_reply) section.append(element('p', `人工最新回复：${item.latest_reply.text}`));
      section.append(element('p', item.execution_status === 'verified' ? '订单地址修改已有执行记录。' : '工单状态不代表退款到账、已开票或已补发；相关业务执行尚未接通。'));
    }
    if (data.has_more) section.append(element('p', '这里展示最近10条记录，请在“我的工单”查看其他申请。'));
    section.append(button('查看我的工单', cases));
  }
  async function listPanel(title, load) {
    const content = utility(title), section = panel(title, content), version = generation;
    const refreshButton = button('重新加载', () => action(refreshButton, section, run, '正在加载…'));
    section.append(refreshButton);
    async function run() { const data = await load(); if (version === generation && section.isConnected) return data(section); }
    await action(refreshButton, section, run, '正在加载…');
  }
  async function cases() {
    await listPanel('我的工单', async () => {
      const result = await request('cases');
      return section => {
        section.replaceChildren(element('h2', '我的工单'));
        if (!result.items.length) section.append(element('p', '当前账号暂无工单。可以先描述问题或选择本人订单。'));
        for (const item of result.items) renderCase(item, section, false);
        if (activeCase) { const current = result.items.find(item => item.id === activeCase.id); if (current) adopt(current, false); }
      };
    });
  }
  async function preferences() {
    await listPanel('推荐偏好', async () => {
      const result = await request('preferences');
      return section => {
        section.replaceChildren(element('h2', '我的推荐偏好'), element('p', '只保存你主动填写的分类、场景与预算，90天后删除，可随时清空。'));
        const form = element('form');
        const categories = field(form, '偏好商品分类（用逗号分隔）'); categories.value = (result.data.categories || []).join('，');
        const occasion = field(form, '使用场景'); occasion.value = result.data.occasion || ''; occasion.maxLength = 100;
        const budget = field(form, '预算上限（元）'); budget.type = 'number'; budget.min = '0'; budget.max = '1000000'; budget.step = '0.01'; budget.value = result.data.budget_max || '';
        const consent = checkbox(form, '同意为后续推荐保存以上偏好90天'); consent.required = true;
        const submit = element('button', '保存推荐偏好'); submit.type = 'submit'; form.append(submit); section.append(form);
        form.addEventListener('submit', async event => { event.preventDefault(); await action(submit, section, () => request('preferences', 'PUT', { consent: true,
          categories: categories.value.split(/[,，]/).map(value => value.trim()).filter(Boolean), occasion: occasion.value, budget_max: budget.value || null }), '正在保存…', '推荐偏好已保存。'); });
        const remove = button('删除全部推荐偏好', () => action(remove, section, async () => { await request('preferences', 'DELETE'); categories.value = ''; occasion.value = ''; budget.value = ''; consent.checked = false; }, '正在删除…', '推荐偏好已删除。'));
        section.append(remove);
      };
    });
  }
  function feedback() {
    const context = host.context(), section = panel('评价本次服务', utility('服务评价'));
    if (!context) { notice(section, '请先完成一次咨询再评价。'); return; }
    const form = element('form'), rating = field(form, '满意度', 'select');
    for (let i = 5; i >= 1; i--) { const option = element('option', `${i} 分`); option.value = String(i); rating.append(option); }
    const resolved = checkbox(form, '我的问题已经解决'), submit = element('button', '提交评价'); submit.type = 'submit'; form.append(submit); section.append(form);
    form.addEventListener('submit', async event => { event.preventDefault(); await action(submit, section, async () => {
      await request('feedback', 'POST', { consultation_id: context.consultation_id, rating: Number(rating.value), resolved: resolved.checked }); form.remove();
    }, '正在提交…', '评价已保存，谢谢你的反馈。'); });
  }
  async function notifications() {
    await listPanel('服务通知', async () => {
      const result = await request('notifications');
      return section => {
        section.replaceChildren(element('h2', '我的服务通知'));
        if (!result.items.length) section.append(element('p', '暂无通知；订单发货、确认收货和工单回复会在这里显示。'));
        for (const item of result.items) {
          const row = element('section', undefined, 'notification-row'); row.append(element('p', item.text), element('span', item.read ? '已读' : '未读', 'notification-status'));
          if (!item.read) {
            const control = button('标记已读', async () => {
              if (control.disabled) return;
              control.disabled = true; control.textContent = '正在标记…';
              try { await request(`notifications/${item.id}/read`, 'POST', {}); control.textContent = '已读'; row.querySelector('.notification-status').textContent = '已读'; notice(row, '已标记已读。', 'success'); }
              catch (error) { notice(row, error.message, 'error'); control.disabled = false; control.textContent = '重试标记已读'; }
            }); row.append(control);
          }
          section.append(row);
        }
      };
    });
  }
  function offerFeedback() {
    if (feedbackOffered) return; feedbackOffered = true;
    host.messages.append(button('转人工已受理，可对本次服务打分', feedback));
  }
  window.ShopSupport = {
    init(options) { host = options; }, cases, preferences, feedback, notifications, refresh, handoff,
    inHumanMode() { return Boolean(activeCase); },
    busy() { return pending || requested; },
    send: sendSupplement,
    resumeAI() { if (pending || requested || !activeCase && !previewOnly) return; activeCase = null; previewOnly = false; syncState('已返回智能客服，原工单仍可在“我的工单”继续跟进。'); },
    reset() {
      generation += 1; feedbackOffered = false; activeCase = null; requested = false; pending = false; previewOnly = false;
      for (const section of caseViews.values()) section.querySelectorAll('button').forEach(control => { control.disabled = true; });
      caseViews.clear(); previews.clear(); uncertain.clear(); requestViews.clear();
      if (host) { window.ShopWorkspace.closePanel(); syncState(); }
    },
    render(card) {
      if (card.type === 'support_case') { renderCase(card.case, undefined, ['human_handoff', 'complaint'].includes(card.case?.kind)); offerFeedback(); }
      if (card.type === 'size_advice') sizeAdvice(card);
      if (card.type === 'service_progress') serviceProgress(card.progress);
      if (card.type === 'handoff_preview') previewHandoff(card.summary);
      if (card.type === 'service_request') { const control = button(`申请${labels[card.kind] || '人工处理'}`, () => requestForm(card)); control.dataset.consultationAction = 'true'; host.messages.append(control); }
      if (card.type === 'product_comparison') {
        const section = panel('商品参数对比'), table = element('table');
        const head = element('tr'); head.append(element('th', '商品'), element('th', '价格'), element('th', '已登记参数')); table.append(head);
        for (const item of card.comparison?.items || []) { const row = element('tr'); row.append(element('td', item.product.name), element('td', `¥${item.product.price}`), element('td', JSON.stringify(item.attributes))); table.append(row); }
        section.append(table);
      }
      if (card.type === 'storefront_link' && card.href === '/?view=orders') { const link = element('a', card.label, 'quick-question'); link.href = card.href; host.messages.append(link); }
    },
    citations(items) {
      for (const citation of items || []) {
        if (typeof citation.title !== 'string' || typeof citation.source !== 'string') continue;
        host.activate(); const section = element('details', undefined, 'reply-evidence'); section.append(element('summary', `依据：${citation.title}`));
        const content = element('div'); content.append(element('p', `来源：${citation.source} · 版本 ${citation.version}`), element('p', citation.body)); section.append(content); host.messages.append(section);
      }
    },
  };
})();
