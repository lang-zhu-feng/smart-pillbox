const store = require('../../utils/store')
Page({
  data: { items: [], selectedIndex: 0, names: [], current: null, editOpen: false, loading: true },
  onShow() { if (store.requireLogin()) this.refresh() },
  applySupport(result) {
    result.items = result.items.map(item => ({ ...item, timeLabel: item.updatedAt ? item.updatedAt.slice(0, 19).replace('T', ' ') : '' }))
    const previous = this.data.current && this.data.current.planId
    let index = result.items.findIndex(item => item.planId === previous)
    if (index < 0) index = 0
    this.setData({ ...result, names: result.items.map(item => item.medicine + (item.enabled ? '' : '（已暂停）')), selectedIndex: index, current: result.items[index] || null, loading: false, connectionError: '' })
  },
  async refresh() {
    try { this.applySupport(await store.request('/api/medicines')) }
    catch (e) { this.setData({ loading: false, connectionError: e.message }); store.error(e) }
  },
  selectMedicine(event) { const index = Number(event.detail.value); this.setData({ selectedIndex: index, current: this.data.items[index], editOpen: false }) },
  edit() { this.setData({ editOpen: !this.data.editOpen }) },
  async save(event) {
    const result = await store.run(this, () => store.request('/api/medicines/' + encodeURIComponent(this.data.current.planId), 'PATCH', event.detail.value), '说明书资料已保存')
    if (result) { this.applySupport(result); this.setData({ editOpen: false }) }
  },
  goPlans() { wx.switchTab({ url: '/pages/plans/plans' }) },
  copySource(event) { wx.setClipboardData({ data: event.currentTarget.dataset.url }) }
})
