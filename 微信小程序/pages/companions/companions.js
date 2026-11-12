const store = require('../../utils/store')
const displayMessages = items => items.map(item => ({ ...item, timeLabel: item.createdAt ? item.createdAt.slice(0, 19).replace('T', ' ') : '' }))
Page({
  data: { profile: { enabled: false }, eligibleMedicines: [], names: [], selectedIndex: 0, candidates: [], requests: [], connections: [], formOpen: false, chatId: '', chatAlias: '', messages: [], draft: '', loading: true },
  onShow() {
    if (!store.requireLogin()) return
    this.refresh()
    this._timer = setInterval(() => { if (!this.data.formOpen && !this._acting) this.refresh(true) }, 8000)
  },
  onHide() { clearInterval(this._timer) },
  onUnload() { clearInterval(this._timer) },
  applySupport(result) {
    let index = result.eligibleMedicines.findIndex(p => p.planId === result.profile.planId)
    if (index < 0) index = 0
    const patch = { ...result, names: result.eligibleMedicines.map(p => p.medicine), selectedIndex: index, loading: false, connectionError: '' }
    if (this.data.chatId && !result.connections.some(c => c.id === this.data.chatId)) Object.assign(patch, { chatId: '', messages: [], draft: '' })
    this.setData(patch)
  },
  async refresh(silent = false) {
    if (this._refreshing || this._acting) return
    this._refreshing = true
    try { this.applySupport(await store.request('/api/companions')); if (this.data.chatId) await this.loadMessages() }
    catch (e) { this.setData({ loading: false, connectionError: e.message }); if (!silent) store.error(e) }
    finally { this._refreshing = false }
  },
  editProfile() { this.setData({ formOpen: !this.data.formOpen }) },
  selectMedicine(event) { this.setData({ selectedIndex: Number(event.detail.value) }) },
  async saveProfile(event) {
    const plan = this.data.eligibleMedicines[this.data.selectedIndex]
    const form = event.detail.value
    if (!plan || !form.alias.trim() || !form.consent || form.consent.indexOf('yes') < 0) { store.error('请选择计划、填写昵称，并确认参与者本人同意'); return }
    const result = await store.run(this, () => store.request('/api/companions/profile', 'PATCH', { enabled: true, alias: form.alias.trim(), about: form.about.trim(), planId: plan.planId, participantConsent: true }), '已开启自愿药友交流')
    if (result) { this.applySupport(result); this.setData({ formOpen: false }) }
  },
  disable() {
    wx.showModal({ title: '关闭药友交流？', content: '停止展示昵称与所选药名，结束待处理邀请和已有药友关系，双方不能继续发送或读取聊天。重新开启需重新邀请。', success: async result => {
      if (!result.confirm) return
      const value = await store.run(this, () => store.request('/api/companions/profile', 'PATCH', { enabled: false }), '已关闭药友交流')
      if (value) { this.applySupport(value); this.setData({ formOpen: false }) }
    } })
  },
  async invite(event) {
    const result = await store.run(this, () => store.request('/api/companions/requests', 'POST', { targetId: event.currentTarget.dataset.id }), '邀请已发出，等待对方接受')
    if (result) this.applySupport(result)
  },
  async decide(event) {
    const { id, action } = event.currentTarget.dataset
    if (action === 'disconnect') {
      const answer = await new Promise(resolve => wx.showModal({ title: '结束这段药友关系？', content: '双方将不能继续发送或读取这段聊天；如需恢复，请重新邀请。', success: resolve }))
      if (!answer.confirm) return
    }
    const result = await store.run(this, () => store.request('/api/companions/requests/' + encodeURIComponent(id), 'PATCH', { action }), '已更新')
    if (result) this.applySupport(result)
  },
  async openChat(event) {
    this.setData({ chatId: event.currentTarget.dataset.id, chatAlias: event.currentTarget.dataset.alias, messages: [], draft: '' })
    try { await this.loadMessages() } catch (e) { this.setData({ chatId: '' }); store.error(e) }
  },
  async loadMessages() {
    const id = this.data.chatId
    if (!id) return
    const result = await store.request('/api/companions/connections/' + encodeURIComponent(id) + '/messages')
    if (this.data.chatId === id) this.setData({ messages: displayMessages(result.items) })
  },
  closeChat() { this.setData({ chatId: '', messages: [], draft: '' }) },
  typeMessage(event) { this.setData({ draft: event.detail.value }) },
  async sendMessage() {
    const content = this.data.draft.trim(), id = this.data.chatId
    if (!content || !id) return
    const result = await store.run(this, () => store.request('/api/companions/connections/' + encodeURIComponent(id) + '/messages', 'POST', { content }), '已发送')
    if (result && this.data.chatId === id) this.setData({ messages: displayMessages(result.items), draft: '' })
  }
})
