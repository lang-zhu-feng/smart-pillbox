const store = require('../../utils/store')
Page(store.page({
  data: { filter: 'ALL', filters: [{ key: 'ALL', label: '全部' }, { key: 'COMPLETED', label: '已开盒' }, { key: 'CONFIRMED', label: '家属确认' }, { key: 'OVERDUE', label: '待确认' }], history: [] },
  applyState(state) { this._state = state; this.renderRecords() },
  renderRecords() { this.setData({ history: this._state.history.filter(h => this.data.filter === 'ALL' || h.result === this.data.filter).map(h => ({ ...h, resultLabel: store.statusMeta[h.result].label, statusClass: store.statusMeta[h.result].className, sourceLabel: store.sourceLabel(h.source) })) }) },
  changeFilter(event) { this.setData({ filter: event.currentTarget.dataset.key }); if (this._state) this.renderRecords() }
}))
