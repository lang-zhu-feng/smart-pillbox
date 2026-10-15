const STORAGE_KEY = 'medguard_demo_state_v1'

const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const slots = [
  { key: 'morning', name: '早', fullName: '早餐后', time: '08:00-08:30' },
  { key: 'noon', name: '中', fullName: '午餐后', time: '12:00-12:30' },
  { key: 'evening', name: '晚', fullName: '晚餐后', time: '19:00-19:30' }
]

const statusMeta = {
  NO_MEDICATION: { label: '无需服药', short: '无', className: 'status-none' },
  PENDING: { label: '待服药', short: '待', className: 'status-pending' },
  REMINDING: { label: '提醒中', short: '提醒', className: 'status-reminding' },
  COMPLETED: { label: '已完成', short: '完成', className: 'status-completed' },
  OVERDUE: { label: '已逾期', short: '逾期', className: 'status-overdue' },
  DEVICE_OFFLINE: { label: '设备离线', short: '离线', className: 'status-offline' }
}

function pad(value) {
  return String(value).padStart(2, '0')
}

function formatDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function formatTime(date) {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function mondayIndex(date) {
  const day = date.getDay()
  return day === 0 ? 6 : day - 1
}

function medicinesFor(slotKey, dayIndex) {
  if (slotKey === 'morning') {
    return ['氨氯地平片 1片', '阿司匹林肠溶片 1片']
  }
  if (slotKey === 'noon') {
    return [0, 2, 4].includes(dayIndex) ? ['二甲双胍片 1片'] : []
  }
  return ['阿托伐他汀钙片 1片']
}

function createInitialState() {
  const now = new Date()
  const todayIndex = mondayIndex(now)
  const tasks = []

  slots.forEach((slot) => {
    days.forEach((day, dayIndex) => {
      const medicines = medicinesFor(slot.key, dayIndex)
      let status = medicines.length ? 'PENDING' : 'NO_MEDICATION'

      if (medicines.length && dayIndex < todayIndex) status = 'COMPLETED'
      if (medicines.length && dayIndex === todayIndex && slot.key === 'morning') status = 'COMPLETED'
      if (medicines.length && dayIndex === todayIndex && slot.key === 'noon') status = 'REMINDING'

      tasks.push({
        id: `${dayIndex}-${slot.key}`,
        dayIndex,
        day,
        slotKey: slot.key,
        slotName: slot.name,
        slotFullName: slot.fullName,
        time: slot.time,
        medicines,
        status,
        completedAt: status === 'COMPLETED' ? '08:16' : ''
      })
    })
  })

  const previousIndex = todayIndex === 0 ? 6 : todayIndex - 1
  const overdueTask = tasks.find((task) => task.dayIndex === previousIndex && task.slotKey === 'evening')
  if (overdueTask) {
    overdueTask.status = 'OVERDUE'
    overdueTask.completedAt = ''
  }

  return {
    elder: {
      name: '李建国',
      age: 72,
      relation: '父亲',
      address: '青岛市市北区',
      conditions: ['高血压', '2型糖尿病'],
      emergencyContact: '李女士 138****2608'
    },
    device: {
      name: '客厅智能药盒',
      code: 'MG-2026-001',
      online: true,
      lastSeen: '刚刚',
      battery: 86
    },
    tasks,
    plans: [
      {
        id: 'plan-1',
        medicine: '氨氯地平片',
        dosage: '1片',
        time: '08:00',
        schedule: '每天 · 早餐后',
        enabled: true,
        note: '降压药'
      },
      {
        id: 'plan-2',
        medicine: '二甲双胍片',
        dosage: '1片',
        time: '12:00',
        schedule: '周一、周三、周五 · 午餐后',
        enabled: true,
        note: '随餐服用'
      },
      {
        id: 'plan-3',
        medicine: '阿托伐他汀钙片',
        dosage: '1片',
        time: '19:00',
        schedule: '每天 · 晚餐后',
        enabled: true,
        note: '晚间服用'
      }
    ],
    alerts: [
      {
        id: 'alert-1',
        level: 'high',
        title: '晚间用药可能漏服',
        detail: `${days[previousIndex]} 19:00 的药格在宽限时间内未检测到开盒事件`,
        time: '昨天 19:46',
        read: false,
        taskId: overdueTask ? overdueTask.id : ''
      },
      {
        id: 'alert-2',
        level: 'info',
        title: '药盒已恢复在线',
        detail: '设备 MG-2026-001 已重新连接家庭 Wi-Fi',
        time: '昨天 09:12',
        read: true,
        taskId: ''
      }
    ],
    history: [
      {
        id: 'history-1',
        date: formatDate(now),
        slot: '早餐后',
        medicine: '氨氯地平片、阿司匹林肠溶片',
        result: 'COMPLETED',
        event: '08:16 检测到开盒'
      },
      {
        id: 'history-2',
        date: '昨天',
        slot: '午餐后',
        medicine: '二甲双胍片',
        result: 'COMPLETED',
        event: '12:08 检测到开盒'
      },
      {
        id: 'history-3',
        date: '昨天',
        slot: '晚餐后',
        medicine: '阿托伐他汀钙片',
        result: 'OVERDUE',
        event: '未检测到开盒事件'
      }
    ],
    meta: {
      updatedAt: `${formatDate(now)} ${formatTime(now)}`
    }
  }
}

function ensureState() {
  const state = wx.getStorageSync(STORAGE_KEY)
  if (!state || !state.tasks) {
    const initialState = createInitialState()
    wx.setStorageSync(STORAGE_KEY, initialState)
    return initialState
  }
  return state
}

function loadState() {
  return ensureState()
}

function saveState(state) {
  state.meta.updatedAt = `${formatDate(new Date())} ${formatTime(new Date())}`
  wx.setStorageSync(STORAGE_KEY, state)
  return state
}

function resetState() {
  const state = createInitialState()
  wx.setStorageSync(STORAGE_KEY, state)
  return state
}

function completeTask(taskId) {
  const state = loadState()
  const task = state.tasks.find((item) => item.id === taskId)
  if (!task || task.status === 'NO_MEDICATION') return state

  const now = new Date()
  task.status = 'COMPLETED'
  task.completedAt = formatTime(now)
  state.history.unshift({
    id: `history-${Date.now()}`,
    date: formatDate(now),
    slot: task.slotFullName,
    medicine: task.medicines.map((item) => item.replace(/\s\d+片$/, '')).join('、'),
    result: 'COMPLETED',
    event: `${formatTime(now)} 检测到开盒`
  })
  state.alerts.forEach((alert) => {
    if (alert.taskId === taskId) alert.read = true
  })
  return saveState(state)
}

function simulateOverdue(taskId) {
  const state = loadState()
  let task = state.tasks.find((item) => item.id === taskId)
  if (!task || task.status === 'NO_MEDICATION') {
    task = state.tasks.find((item) => item.status === 'PENDING' || item.status === 'REMINDING')
  }
  if (!task) return state

  task.status = 'OVERDUE'
  task.completedAt = ''
  const existing = state.alerts.find((alert) => alert.taskId === task.id && alert.level === 'high')
  if (!existing) {
    state.alerts.unshift({
      id: `alert-${Date.now()}`,
      level: 'high',
      title: `${task.day}${task.slotFullName}可能漏服`,
      detail: `${task.time} 的药格在宽限时间内未检测到开盒事件，请及时联系老人确认`,
      time: '刚刚',
      read: false,
      taskId: task.id
    })
  } else {
    existing.read = false
    existing.time = '刚刚'
  }
  state.history.unshift({
    id: `history-${Date.now()}`,
    date: formatDate(new Date()),
    slot: task.slotFullName,
    medicine: task.medicines.map((item) => item.replace(/\s\d+片$/, '')).join('、'),
    result: 'OVERDUE',
    event: '未检测到开盒事件'
  })
  return saveState(state)
}

function markAlertRead(alertId) {
  const state = loadState()
  const alert = state.alerts.find((item) => item.id === alertId)
  if (alert) alert.read = true
  return saveState(state)
}

function markAllAlertsRead() {
  const state = loadState()
  state.alerts.forEach((alert) => {
    alert.read = true
  })
  return saveState(state)
}

function togglePlan(planId) {
  const state = loadState()
  const plan = state.plans.find((item) => item.id === planId)
  if (plan) plan.enabled = !plan.enabled
  return saveState(state)
}

function addDemoPlan() {
  const state = loadState()
  const existing = state.plans.find((item) => item.medicine === '维生素D滴剂')
  if (!existing) {
    state.plans.push({
      id: `plan-${Date.now()}`,
      medicine: '维生素D滴剂',
      dosage: '1粒',
      time: '09:00',
      schedule: '每周日 · 早餐后',
      enabled: true,
      note: '演示新增计划'
    })
  }
  return saveState(state)
}

module.exports = {
  days,
  slots,
  statusMeta,
  ensureState,
  loadState,
  resetState,
  completeTask,
  simulateOverdue,
  markAlertRead,
  markAllAlertsRead,
  togglePlan,
  addDemoPlan,
  mondayIndex,
  formatDate
}
