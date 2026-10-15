const store = require('../../utils/store')

Page({
  data: {
    filter: 'ALL',
    filters: [
      { key: 'ALL', label: '全部' },
      { key: 'COMPLETED', label: '已完成' },
      { key: 'OVERDUE', label: '异常' }
    ],
    history: []
  },

  onShow() {
    this.refresh()
  },

  refresh() {
    const state = store.loadState()
    const filter = this.data.filter
    const history = state.history
      .filter((record) => filter === 'ALL' || record.result === filter)
      .map((record) => ({
        ...record,
        resultLabel: store.statusMeta[record.result].label,
        statusClass: store.statusMeta[record.result].className
      }))
    this.setData({ history })
  },

  changeFilter(event) {
    this.setData({ filter: event.currentTarget.dataset.key })
    this.refresh()
  }
})
