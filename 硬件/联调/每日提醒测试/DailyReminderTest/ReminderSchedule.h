#pragma once
#include <stdint.h>

// 纯状态机：实际日与缩时演练各用一个实例，演练不能覆盖实际日记录。
namespace BoxReminder {
static const uint32_t REMINDER_SECOND = 8U * 3600U;
static const uint32_t DEADLINE_SECOND = 9U * 3600U;

enum Action { NoAction, ThreeBeeps, ContinuousTenSeconds, StopSound };
enum Flag {
  ReminderDone = 1,
  OverdueDone = 2,
  OpenedInWindow = 4,
  OpenedLate = 8,
  PastSkipped = 16
};

struct DayState {
  uint32_t day;
  uint8_t flags;
  DayState(uint32_t value = 0, uint8_t bits = 0) : day(value), flags(bits) {}
};

struct Decision {
  Action action;
  bool changed;
  bool clockBlocked;
  Decision(Action value = NoAction, bool dirty = false, bool blocked = false)
      : action(value), changed(dirty), clockBlocked(blocked) {}
};

class Schedule {
 public:
  Schedule() : state_() {}

  bool restore(uint32_t day, uint8_t flags) {
    if ((flags & ~31U) != 0 || (day == 0 && flags != 0)) return false;
    state_ = DayState(day, flags);
    return true;
  }

  const DayState& state() const { return state_; }
  bool has(Flag flag) const { return (state_.flags & flag) != 0; }

  // 初次校时如当天截止时间已过且无当天记录，不补响旧计划。
  // 若已存同一天记录，保留进度，以便恢复未完成的提醒。
  Decision initialize(uint32_t day, uint32_t second, bool skipPast) {
    Decision result = ensureDay(day, second);
    if (result.clockBlocked) return result;
    if (result.changed && skipPast && second >= DEADLINE_SECOND) {
      state_.flags = ReminderDone | OverdueDone | PastSkipped;
    }
    return result;
  }

  Decision tick(uint32_t day, uint32_t second) {
    Decision result = ensureDay(day, second);
    if (result.clockBlocked || has(OpenedInWindow) || has(OpenedLate)) return result;
    // 先判超时，避免晚于 9 点才启动时挤在一起响两种声音。
    if (second >= DEADLINE_SECOND) {
      if (!has(OverdueDone)) {
        state_.flags |= ReminderDone | OverdueDone;
        result.action = ContinuousTenSeconds;
        result.changed = true;
      }
    } else if (second >= REMINDER_SECOND && !has(ReminderDone)) {
      state_.flags |= ReminderDone;
      result.action = ThreeBeeps;
      result.changed = true;
    }
    return result;
  }

  // 只在去抖后的关->开边沿调用；开机已经开着不构成新开盒。
  // 截止点为 09:00:00：此后打开只记迟到，仍立即停止本地响铃。
  Decision opening(uint32_t day, uint32_t second) {
    Decision result = ensureDay(day, second);
    if (result.clockBlocked) return result;
    result.action = StopSound;
    uint8_t flag = 0;
    if (second >= REMINDER_SECOND && second < DEADLINE_SECOND &&
        !has(OverdueDone) && !has(OpenedLate)) flag = OpenedInWindow;
    else if (second >= DEADLINE_SECOND && !has(OpenedInWindow)) flag = OpenedLate;
    if (flag != 0 && (state_.flags & flag) == 0) {
      state_.flags |= flag;
      result.changed = true;
    }
    return result;
  }

 private:
  DayState state_;

  Decision ensureDay(uint32_t day, uint32_t second) {
    if (day == 0 || second >= 86400U || (state_.day != 0 && day < state_.day)) {
      return Decision(NoAction, false, true);
    }
    if (day != state_.day) {
      state_ = DayState(day, 0);
      return Decision(NoAction, true, false);
    }
    return Decision();
  }
};
}  // namespace BoxReminder
