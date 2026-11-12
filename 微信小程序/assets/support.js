'use strict';
window.MedSupport = (() => {
  let root, kind = '', context, data, generation = 0, editingMedicine = false, profileOpen = false;
  let selectedPlan = '', chatId = '', messages = [], draft = '', acting = false, session = '';
  const labels = {specification:'规格', manufacturer:'厂家', introduction:'药品介绍（按实际说明书）', precautions:'注意事项', storage:'该药贮藏要求', source:'资料来源（如厂家说明书、版本日期）'};
  const limits = {specification:100, manufacturer:100, introduction:1000, precautions:1000, storage:500, source:200};
  const esc = value => context.escape(value);
  const displayTime = value => String(value || '').slice(0,19).replace('T',' ');
  async function api(...args) {
    const version = generation;
    const result = await context.api(...args);
    if (version !== generation) throw new Error('页面已切换，请在当前页面继续');
    return result;
  }
  const button = (label, action, id = '', decision = '') => `<button type="button" class="secondary-btn" data-support-action="${action}" data-id="${esc(id)}" data-decision="${decision}">${label}</button>`;
  const copy = value => `<p class="support-copy">${esc(value)}</p>`;
  function reset() { generation++; kind = ''; data = null; chatId = ''; messages = []; draft = ''; selectedPlan = ''; profileOpen = false; editingMedicine = false; root = null; }
  function showError(error) {
    if (!root || !root.isConnected) return;
    let note = root.querySelector('[data-support-error]');
    if (!note) { note = document.createElement('p'); note.dataset.supportError = ''; note.className = 'form-error'; note.setAttribute('role', 'alert'); root.prepend(note); }
    note.textContent = error.message || String(error);
  }
  function medicinePage() {
    const current = data.items.find(item => item.planId === selectedPlan) || data.items[0];
    if (current) selectedPlan = current.planId;
    return `<button class="back" data-page="plans">‹ 返回计划</button><h2 class="page-heading">药品介绍与储存</h2><p class="page-sub">按实际说明书记录，让照料多一份依据。</p>${current ? `<article class="card"><label class="support-label" for="support-medicine">选择计划药品</label><select id="support-medicine">${data.items.map(item => `<option value="${esc(item.planId)}" ${item.planId === selectedPlan ? 'selected' : ''}>${esc(item.medicine)}${item.enabled ? '' : '（已暂停）'}</option>`).join('')}</select><p class="boundary">${esc(current.provenance)}。同药名计划共用资料；不同规格或厂家请在计划名称中区分。未填写表示资料待补充。</p>${Object.entries(labels).map(([key, label]) => `<h3 class="support-label">${label}</h3>${copy(current[key] || (key === 'storage' ? '未录入。先核对包装和说明书；不确定能否分装时请咨询药师。' : '待按实际包装或说明书补充'))}`).join('')}<p class="boundary">${current.updatedAt ? '更新于 ' + esc(displayTime(current.updatedAt)) : '尚无录入资料，不自动生成适应症或剂量。'}</p>${button(editingMedicine ? '取消编辑' : '按说明书补充资料', 'edit-medicine')}${editingMedicine ? `<form data-support-form="medicine">${Object.entries(labels).map(([key, label]) => `<div class="field"><label for="support-${key}">${label}</label>${limits[key] > 200 ? `<textarea id="support-${key}" name="${key}" maxlength="${limits[key]}">${esc(current[key])}</textarea>` : `<input id="support-${key}" name="${key}" maxlength="${limits[key]}" value="${esc(current[key])}">`}</div>`).join('')}<p class="boundary">填写任何药品资料时，来源必填；资料仅当前家庭可见。</p><button class="main-cta" type="submit">保存说明书资料</button></form>` : ''}</article>` : `<article class="card">${copy('先添加用药计划，再补充该药介绍和贮藏要求。')}<button class="main-cta" data-page="plans">去添加计划</button></article>`}<article class="card"><h3>日常储存提示</h3>${data.storageTips.map(copy).join('')}<p class="boundary">一般储存知识来源，不能替代具体药品说明书：</p>${data.sources.map(source => `<p><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a></p>`).join('')}</article><article class="card"><h3>方便取药 · 结构改进方案</h3>${data.retrievalTips.map(copy).join('')}</article><p class="support-notice">${esc(data.prototypeNotice)}</p>`;
  }
  function companionPage() {
    const profile = data.profile, selected = data.eligibleMedicines.find(p => p.planId === profile.planId);
    const card = entry => `<h3>${esc(entry.alias)}</h3>${copy('共同话题：' + entry.medicine)}${copy(entry.about || '对方暂未填写介绍')}`;
    const connection = data.connections.find(c => c.id === chatId);
    if (!connection) { chatId = ''; messages = []; draft = ''; }
    return `<button class="back" data-page="profile">‹ 返回我的</button><h2 class="page-heading">同药话题 · 药友</h2><p class="page-sub">由家属协助、参与者本人自愿开启。相同药名只是共同话题，不代表病情或用法相同。</p><article class="card"><h3>${profile.enabled ? '已开启自愿交流' : '默认关闭 · 由你决定'}</h3>${profile.enabled ? copy('昵称：' + profile.alias + '\n共同话题：' + (selected?.medicine || '')) : ''}<p class="boundary">开启后，仅向自愿选择相同药名的账号展示昵称、介绍和所选药名。家庭姓名、电话、地址、病史及完整药单不随推荐展示。请勿在昵称、介绍或聊天中填写敏感资料。</p>${button(profileOpen ? '取消编辑' : profile.enabled ? '修改交流设置' : '自愿开启药友交流', 'edit-profile')}${profile.enabled ? button('关闭交流并结束药友关系', 'disable') : ''}${profileOpen ? `<form data-support-form="profile"><div class="field"><label for="support-alias">交流昵称（不使用真实姓名）</label><input id="support-alias" name="alias" maxlength="24" value="${esc(profile.alias)}" required></div><div class="field"><label for="support-about">自我介绍（可选，不填病史和联系方式）</label><textarea id="support-about" name="about" maxlength="120">${esc(profile.about)}</textarea></div><div class="field"><label for="support-plan">自愿公开的一项用药话题</label><select id="support-plan" name="planId" required>${data.eligibleMedicines.length ? data.eligibleMedicines.map(p => `<option value="${esc(p.planId)}" ${p.planId === profile.planId ? 'selected' : ''}>${esc(p.medicine)}</option>`).join('') : '<option value="">请先添加并启用用药计划</option>'}</select></div><label class="support-consent"><input type="checkbox" name="consent" required>参与者本人已同意展示昵称、介绍和所选药名，并了解双方接受邀请后可在应用内交流；家属代操作也已征得本人同意。</label><p class="boundary">更换药名、关闭交流或暂停所选计划将结束已有邀请和关系。恢复计划不会自动恢复药友。</p><button class="main-cta" type="submit" ${data.eligibleMedicines.length ? '' : 'disabled'}>同意并保存</button></form>` : ''}</article>${profile.enabled ? `<div class="section-row"><h3>新的药友邀请</h3></div>${data.requests.length ? data.requests.map(entry => `<article class="card">${card(entry)}<p class="boundary">${entry.direction === 'sent' ? '邀请已发送，等待对方接受' : '对方邀请你交流'}</p><div class="support-actions">${entry.direction === 'sent' ? button('撤回邀请', 'decide', entry.id, 'cancel') : button('接受', 'decide', entry.id, 'accept') + button('拒绝', 'decide', entry.id, 'decline')}</div></article>`).join('') : '<p class="page-sub">暂无待处理邀请。</p>'}<div class="section-row"><h3>我的药友</h3></div>${data.connections.length ? data.connections.map(entry => `<article class="card">${card(entry)}<div class="support-actions">${button('聊一聊', 'chat', entry.id)}${button('结束关系', 'decide', entry.id, 'disconnect')}</div></article>`).join('') : '<p class="page-sub">双方接受邀请后，会显示在这里。</p>'}${chatId ? `<article class="card" id="support-chat"><h3>与 ${esc(connection.alias)} 交流</h3><p class="boundary">展示最近 100 条消息，每 8 秒刷新；编辑时暂停刷新。交流生活与陪伴话题，不照搬他人药物和剂量。</p>${messages.length ? messages.map(message => `<div class="support-message ${message.mine ? 'mine' : ''}"><small>${message.mine ? '我' : esc(connection.alias)} · ${esc(displayTime(message.createdAt))}</small>${copy(message.content)}</div>`).join('') : '<p class="page-sub">还没有消息，先打个招呼吧。</p>'}<form data-support-form="chat"><div class="field"><label for="support-message">写一句问候（最多 500 字）</label><textarea id="support-message" name="content" maxlength="500" required>${esc(draft)}</textarea></div><button class="main-cta" type="submit">发送</button></form>${button('收起聊天', 'close-chat')}</article>` : ''}<div class="section-row"><h3>相同药名 · 自愿认识</h3></div>${data.candidates.length ? data.candidates.map(entry => `<article class="card">${card(entry)}${button('发送药友邀请', 'invite', entry.id)}</article>`).join('') : '<p class="page-sub">暂时没有可邀请的人。只有双方自愿开启并选择相同药名时才会展示；不会编造药友。</p>'}` : ''}<p class="boundary">仅按填写药名做文字匹配，不推断疾病、不判断药品替代；不同规格或厂家请在药名中区分。演示账号与独立家庭不互相推荐。邀请和聊天保存在本地服务数据库；关闭交流后历史保留但不能继续访问聊天，重新邀请建立新会话。</p>`;
  }
  function paint() {
    if (!root?.isConnected || !data) return;
    const top = document.querySelector('#screen').scrollTop;
    root.innerHTML = kind === 'medicines' ? medicinePage() : companionPage();
    document.querySelector('#screen').scrollTop = top;
  }
  async function refresh(silent = false) {
    const version = generation, currentKind = kind;
    try {
      const value = await api('/api/' + currentKind);
      if (version !== generation || !root?.isConnected) return;
      data = value;
      if (chatId && data.connections?.some(c => c.id === chatId)) {
        const chat = await api('/api/companions/connections/' + encodeURIComponent(chatId) + '/messages');
        if (version !== generation || !root?.isConnected) return;
        messages = chat.items;
      }
      paint();
    } catch (error) { if (version === generation) { showError(error); if (!silent) context.toast(error.message); } }
  }
  async function perform(operation) {
    if (acting) return;
    acting = true;
    const version = generation;
    try { await operation(); }
    catch (error) { if (version === generation) { showError(error); context.toast(error.message); } }
    finally { acting = false; }
  }
  function mount(nextKind, helpers) {
    const token = localStorage.getItem('medguard.session.v2') || '';
    if (session !== token || kind !== nextKind) { reset(); session = token; }
    context = helpers; kind = nextKind; root = document.querySelector('#support-root'); generation++;
    root.innerHTML = '<p class="page-sub">正在加载…</p>';
    root.onclick = event => {
      const b = event.target.closest('[data-support-action]'); if (!b) return;
      const action = b.dataset.supportAction, id = b.dataset.id;
      if (action === 'edit-medicine') { editingMedicine = !editingMedicine; paint(); return; }
      if (action === 'edit-profile') { profileOpen = !profileOpen; paint(); return; }
      if (action === 'close-chat') { chatId = ''; messages = []; draft = ''; paint(); return; }
      if (action === 'disable' && !window.confirm('关闭后停止展示昵称与药名，结束已有邀请和药友关系，双方不能继续发送或读取聊天。重新开启需重新邀请。')) return;
      if (action === 'decide' && b.dataset.decision === 'disconnect' && !window.confirm('结束后，双方不能继续发送或读取这段聊天；如需恢复，请重新邀请。')) return;
      perform(async () => {
        if (action === 'disable') { data = await api('/api/companions/profile', 'PATCH', {enabled:false}); profileOpen = false; }
        if (action === 'invite') data = await api('/api/companions/requests', 'POST', {targetId:id});
        if (action === 'decide') data = await api('/api/companions/requests/' + encodeURIComponent(id), 'PATCH', {action:b.dataset.decision});
        if (action === 'chat') { chatId = id; messages = []; draft = ''; await refresh(); document.querySelector('#support-chat')?.scrollIntoView({block:'start'}); return; }
        paint(); context.toast('已更新');
      });
    };
    root.onchange = event => {
      if (event.target.id === 'support-medicine') { selectedPlan = event.target.value; editingMedicine = false; paint(); }
    };
    root.oninput = event => { if (event.target.id === 'support-message') draft = event.target.value; };
    root.onsubmit = event => {
      const form = event.target.closest('[data-support-form]'); if (!form) return;
      event.preventDefault(); if (!form.reportValidity()) return;
      const body = Object.fromEntries(new FormData(form));
      perform(async () => {
        if (form.dataset.supportForm === 'medicine') { data = await api('/api/medicines/' + encodeURIComponent(selectedPlan), 'PATCH', body); editingMedicine = false; }
        if (form.dataset.supportForm === 'profile') { delete body.consent; data = await api('/api/companions/profile', 'PATCH', {...body,enabled:true,participantConsent:true}); profileOpen = false; }
        if (form.dataset.supportForm === 'chat') { const result = await api('/api/companions/connections/' + encodeURIComponent(chatId) + '/messages', 'POST', {content:body.content}); messages = result.items; draft = ''; }
        paint(); context.toast('已保存');
      });
    };
    refresh();
  }
  setInterval(() => {
    if (kind === 'companions' && root?.isConnected && !acting && !profileOpen && !document.hidden && !root.contains(document.activeElement)) refresh(true);
  }, 8000);
  return { mount, reset, editing: () => !!root?.isConnected && (!!root.querySelector('form') || acting) };
})();
