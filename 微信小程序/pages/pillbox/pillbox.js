const store = require('../../utils/store')

Page({
  data: {
    days: store.days,
    rows: [],
    todayIndex: 0,
    device: {}
  },

  onShow() {
    this.refresh()
  },

  refresh() {
    const state = store.loadState()
    const todayIndex = store.mondayIndex(new Date())
    const rows = store.slots.map((slot) => ({
      ...slot,
      startTime: slot.time.substring(0, 5),
      cells: store.days.map((day, dayIndex) => {
        const task = state.tasks.find((item) => item.dayIndex === dayIndex && item.slotKey === slot.key)
        const meta = store.statusMeta[task.status]
        return {
          ...task,
          shortLabel: meta.short,
          statusLabel: meta.label,
          statusClass: meta.className,
          isToday: dayIndex === todayIndex
        }
      })
    }))
    this.setData({ rows, todayIndex, device: state.device })
  },

  openTask(event) {
    const taskId = event.currentTarget.dataset.id
    const state = store.loadState()
    const task = state.tasks.find((item) => item.id === taskId)
    if (!task) return
    const meta = store.statusMeta[task.status]
    const medicineText = task.medicines.length ? task.medicines.join('\n') : '本时段无需服药'
    const canComplete = task.status !== 'NO_MEDICATION' && task.status !== 'COMPLETED'

    wx.showModal({
      title: `${task.day} · ${task.slotFullName}`,
      content: `${task.time}\n${medicineText}\n\n当前状态：${meta.label}`,
      showCancel: canComplete,
      cancelText: '关闭',
      confirmText: canComplete ? '模拟开盒' : '知道了',
      success: (result) => {
        if (canComplete && result.confirm) {
          store.completeTask(taskId)
          wx.showToast({ title: '状态已更新', icon: 'success' })
          this.refresh()
        }
      }
    })
  },

  simulateOverdue() {
    let candidate = null
    for (const row of this.data.rows) {
      candidate = row.cells.find((task) => task.status === 'REMINDING' || task.status === 'PENDING')
      if (candidate) break
    }
    store.simulateOverdue(candidate ? candidate.id : '')
    wx.showToast({ title: '已生成异常', icon: 'none' })
    this.refresh()
  }
})
