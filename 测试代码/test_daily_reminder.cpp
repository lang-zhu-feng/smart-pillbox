#include "ReminderSchedule.h"
#include <cstdio>
#include <sstream>
#include <stdexcept>

using namespace BoxReminder;

namespace {
const uint32_t TODAY = 20261109;
const uint32_t TOMORROW = 20261110;
const uint32_t AT8 = 8U * 3600U;
const uint32_t AT9 = 9U * 3600U;
int cases = 0;
int failures = 0;

void check(bool value, const char* expression, int line) {
  if (value) return;
  std::ostringstream error;
  error << "line " << line << ": " << expression;
  throw std::runtime_error(error.str());
}
#define CHECK(expression) check((expression), #expression, __LINE__)

template <class Test>
void run(const char* name, Test test) {
  ++cases;
  try {
    test();
    std::printf("PASS %s\n", name);
  } catch (const std::exception& error) {
    ++failures;
    std::printf("FAIL %s: %s\n", name, error.what());
  }
}

void sameState(const DayState& left, const DayState& right) {
  CHECK(left.day == right.day);
  CHECK(left.flags == right.flags);
}
}  // namespace

int main() {
  run("before 08:00 stays silent", [] {
    Schedule schedule;
    Decision first = schedule.initialize(TODAY, AT8 - 1, true);
    CHECK(first.changed && !first.clockBlocked);
    CHECK(schedule.tick(TODAY, AT8 - 1).action == NoAction);
    CHECK(schedule.state().flags == 0);
  });

  run("08:00 triggers three beeps exactly once", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 - 1, true);
    Decision due = schedule.tick(TODAY, AT8);
    CHECK(due.action == ThreeBeeps && due.changed);
    CHECK(schedule.has(ReminderDone));
    CHECK(schedule.tick(TODAY, AT8).action == NoAction);
    CHECK(schedule.tick(TODAY, AT8 + 1).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9 - 1).action == NoAction);
  });

  run("first sync inside window catches up reminder", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 + 1800, true);
    CHECK(schedule.tick(TODAY, AT8 + 1800).action == ThreeBeeps);
    CHECK(schedule.tick(TODAY, AT8 + 1801).action == NoAction);
  });

  run("09:00 triggers ten-second request once", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 - 1, true);
    CHECK(schedule.tick(TODAY, AT8).action == ThreeBeeps);
    Decision overdue = schedule.tick(TODAY, AT9);
    CHECK(overdue.action == ContinuousTenSeconds && overdue.changed);
    CHECK(schedule.has(OverdueDone));
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9 + 10).action == NoAction);
    CHECK(schedule.tick(TODAY, 86399).action == NoAction);
  });

  run("opening inside window cancels timeout", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    Decision opened = schedule.opening(TODAY, AT8 + 1800);
    CHECK(opened.action == StopSound && opened.changed);
    CHECK(schedule.has(OpenedInWindow));
    CHECK(!schedule.has(OpenedLate));
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9 + 100).action == NoAction);
  });

  run("opening at 08:00 before tick suppresses reminder", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 - 1, true);
    CHECK(schedule.opening(TODAY, AT8).action == StopSound);
    CHECK(schedule.has(OpenedInWindow));
    CHECK(schedule.tick(TODAY, AT8).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("opening one second before deadline is on time", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 - 1, true);
    schedule.tick(TODAY, AT8);
    CHECK(schedule.opening(TODAY, AT9 - 1).action == StopSound);
    CHECK(schedule.has(OpenedInWindow));
    CHECK(!schedule.has(OpenedLate));
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("pre-08 opening does not complete daily window", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 - 10, true);
    CHECK(schedule.opening(TODAY, AT8 - 1).action == StopSound);
    CHECK(!schedule.has(OpenedInWindow));
    CHECK(!schedule.has(OpenedLate));
    CHECK(schedule.tick(TODAY, AT8).action == ThreeBeeps);
    CHECK(schedule.tick(TODAY, AT9).action == ContinuousTenSeconds);
  });

  run("opening at exact deadline is late and stops sound", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    Decision opened = schedule.opening(TODAY, AT9);
    CHECK(opened.action == StopSound);
    CHECK(schedule.has(OpenedLate));
    CHECK(!schedule.has(OpenedInWindow));
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("late opening cancels an already-started timeout", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    CHECK(schedule.tick(TODAY, AT9).action == ContinuousTenSeconds);
    CHECK(schedule.opening(TODAY, AT9 + 1).action == StopSound);
    CHECK(schedule.has(OpenedLate));
    CHECK(!schedule.has(OpenedInWindow));
    CHECK(schedule.has(OverdueDone));
    CHECK(schedule.tick(TODAY, AT9 + 2).action == NoAction);
  });

  run("fresh sync at deadline skips already-due schedule", [] {
    Schedule schedule;
    Decision initialized = schedule.initialize(TODAY, AT9, true);
    CHECK(initialized.changed && initialized.action == NoAction);
    CHECK(schedule.has(PastSkipped));
    CHECK(schedule.has(ReminderDone));
    CHECK(schedule.has(OverdueDone));
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("fresh evening sync does not sound old alarm", [] {
    Schedule schedule;
    schedule.initialize(TODAY, 20U * 3600U, true);
    CHECK(schedule.has(PastSkipped));
    CHECK(schedule.tick(TODAY, 20U * 3600U).action == NoAction);
    CHECK(!schedule.has(OpenedInWindow));
    CHECK(!schedule.has(OpenedLate));
  });

  run("explicit non-skipping start after deadline requests timeout only", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT9 + 1, false);
    CHECK(schedule.tick(TODAY, AT9 + 1).action == ContinuousTenSeconds);
    CHECK(schedule.has(ReminderDone));
    CHECK(schedule.has(OverdueDone));
    CHECK(!schedule.has(PastSkipped));
  });

  run("restore reminded pending day permits overdue recovery", [] {
    Schedule schedule;
    CHECK(schedule.restore(TODAY, ReminderDone));
    Decision initialized = schedule.initialize(TODAY, AT9 + 60, true);
    CHECK(!initialized.changed);
    CHECK(!schedule.has(PastSkipped));
    CHECK(schedule.tick(TODAY, AT9 + 60).action == ContinuousTenSeconds);
    CHECK(schedule.tick(TODAY, AT9 + 61).action == NoAction);
  });

  run("restore same-day record without reminder can recover overdue", [] {
    Schedule schedule;
    CHECK(schedule.restore(TODAY, 0));
    schedule.initialize(TODAY, AT9 + 1, true);
    CHECK(!schedule.has(PastSkipped));
    CHECK(schedule.tick(TODAY, AT9 + 1).action == ContinuousTenSeconds);
  });

  run("restore completed timeout never repeats", [] {
    Schedule schedule;
    CHECK(schedule.restore(TODAY, ReminderDone | OverdueDone));
    schedule.initialize(TODAY, AT9 + 60, true);
    CHECK(schedule.tick(TODAY, AT9 + 60).action == NoAction);
  });

  run("restore timely opening prevents morning and overdue alarms", [] {
    Schedule schedule;
    CHECK(schedule.restore(TODAY, OpenedInWindow));
    schedule.initialize(TODAY, AT8 + 300, true);
    CHECK(schedule.tick(TODAY, AT8 + 300).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("restore late opening never starts another timeout", [] {
    Schedule schedule;
    CHECK(schedule.restore(TODAY, ReminderDone | OpenedLate));
    schedule.initialize(TODAY, AT9 + 300, true);
    CHECK(schedule.tick(TODAY, AT9 + 300).action == NoAction);
  });

  run("repeated sync keeps reminder and opening progress", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    schedule.opening(TODAY, AT8 + 1);
    DayState before = schedule.state();
    CHECK(!schedule.initialize(TODAY, AT8 + 5, true).changed);
    sameState(before, schedule.state());
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("day rollover re-arms next morning", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    schedule.opening(TODAY, AT8 + 1);
    Decision midnight = schedule.tick(TOMORROW, 0);
    CHECK(midnight.changed && midnight.action == NoAction);
    CHECK(schedule.state().day == TOMORROW);
    CHECK(schedule.state().flags == 0);
    CHECK(schedule.tick(TOMORROW, AT8).action == ThreeBeeps);
    CHECK(schedule.tick(TOMORROW, AT9).action == ContinuousTenSeconds);
  });

  run("year rollover uses increasing calendar keys", [] {
    Schedule schedule;
    schedule.initialize(20261231, AT8, true);
    schedule.tick(20261231, AT8);
    CHECK(schedule.tick(20270101, 0).action == NoAction);
    CHECK(schedule.tick(20270101, AT8).action == ThreeBeeps);
  });

  run("same-day clock rewind cannot repeat morning reminder", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8 - 1, true);
    CHECK(schedule.tick(TODAY, AT8).action == ThreeBeeps);
    CHECK(schedule.tick(TODAY, AT8 - 1).action == NoAction);
    CHECK(schedule.tick(TODAY, AT8).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9).action == ContinuousTenSeconds);
  });

  run("same-day rewind after timeout cannot sound either old stage", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT9, false);
    CHECK(schedule.tick(TODAY, AT9).action == ContinuousTenSeconds);
    CHECK(schedule.tick(TODAY, AT8).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("past-skipped day remains skipped after clock rewind", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT9 + 1, true);
    CHECK(schedule.tick(TODAY, AT8).action == NoAction);
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
    CHECK(schedule.has(PastSkipped));
  });

  run("opening after timeout clock rewind cannot become on-time", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    CHECK(schedule.tick(TODAY, AT9).action == ContinuousTenSeconds);
    DayState before = schedule.state();
    Decision opening = schedule.opening(TODAY, AT8 + 1800);
    CHECK(opening.action == StopSound);
    CHECK(!schedule.has(OpenedInWindow));
    CHECK(schedule.has(OverdueDone));
    sameState(before, schedule.state());
  });

  run("late opening remains late after rewind and another opening", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    schedule.opening(TODAY, AT9 + 1);
    CHECK(schedule.has(OpenedLate));
    DayState before = schedule.state();
    CHECK(schedule.opening(TODAY, AT8 + 1800).action == StopSound);
    CHECK(schedule.has(OpenedLate));
    CHECK(!schedule.has(OpenedInWindow));
    sameState(before, schedule.state());
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("past-skipped record cannot become on-time after rewind", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT9 + 1, true);
    DayState before = schedule.state();
    CHECK(schedule.opening(TODAY, AT8 + 1800).action == StopSound);
    CHECK(!schedule.has(OpenedInWindow));
    CHECK(schedule.has(PastSkipped));
    sameState(before, schedule.state());
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("earlier calendar day is blocked without clearing state", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    DayState before = schedule.state();
    Decision blocked = schedule.tick(TODAY - 1, AT9);
    CHECK(blocked.clockBlocked && !blocked.changed);
    CHECK(blocked.action == NoAction);
    CHECK(schedule.opening(TODAY - 1, AT8).clockBlocked);
    CHECK(schedule.initialize(TODAY - 1, AT9, true).clockBlocked);
    sameState(before, schedule.state());
    CHECK(schedule.tick(TODAY, AT9).action == ContinuousTenSeconds);
  });

  run("invalid clock inputs cannot trigger alarms or mutate state", [] {
    Schedule schedule;
    CHECK(schedule.tick(0, AT8).clockBlocked);
    CHECK(schedule.tick(TODAY, 86400U).clockBlocked);
    CHECK(schedule.opening(TODAY, UINT32_MAX).clockBlocked);
    CHECK(schedule.initialize(0, AT9, true).clockBlocked);
    CHECK(schedule.state().day == 0 && schedule.state().flags == 0);
  });

  run("invalid clock after valid progress preserves flags", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    DayState before = schedule.state();
    CHECK(schedule.initialize(TOMORROW, 86400U, true).clockBlocked);
    CHECK(schedule.opening(TODAY, 86400U).clockBlocked);
    sameState(before, schedule.state());
  });

  run("invalid restored flags leave existing valid state intact", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.tick(TODAY, AT8);
    DayState before = schedule.state();
    CHECK(!schedule.restore(TODAY, 32));
    CHECK(!schedule.restore(0, ReminderDone));
    sameState(before, schedule.state());
  });

  run("empty restored state can be initialized safely", [] {
    Schedule schedule;
    CHECK(schedule.restore(0, 0));
    CHECK(schedule.initialize(TODAY, AT8 - 1, true).changed);
    CHECK(schedule.tick(TODAY, AT8).action == ThreeBeeps);
  });

  run("repeated opening does not repeatedly dirty persisted state", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    CHECK(schedule.opening(TODAY, AT8 + 1).changed);
    Decision second = schedule.opening(TODAY, AT8 + 2);
    CHECK(second.action == StopSound && !second.changed);
    CHECK(schedule.tick(TODAY, AT9).action == NoAction);
  });

  run("later opening does not downgrade an on-time opening", [] {
    Schedule schedule;
    schedule.initialize(TODAY, AT8, true);
    schedule.opening(TODAY, AT8 + 1);
    DayState before = schedule.state();
    CHECK(schedule.opening(TODAY, AT9 + 1).action == StopSound);
    CHECK(schedule.has(OpenedInWindow));
    CHECK(!schedule.has(OpenedLate));
    sameState(before, schedule.state());
  });

  run("demo instance cannot change real daily progress", [] {
    Schedule actual;
    actual.initialize(TODAY, AT8, true);
    actual.tick(TODAY, AT8);
    actual.opening(TODAY, AT8 + 1);
    DayState before = actual.state();
    Schedule demo;
    demo.initialize(1, AT8 - 5, false);
    CHECK(demo.tick(1, AT8).action == ThreeBeeps);
    CHECK(demo.tick(1, AT9).action == ContinuousTenSeconds);
    CHECK(demo.opening(1, AT9 + 1).action == StopSound);
    sameState(before, actual.state());
    CHECK(actual.tick(TODAY, AT9).action == NoAction);
  });

  run("demo opening cancels only demo timeout", [] {
    Schedule actual;
    actual.initialize(TODAY, AT8 - 1, true);
    actual.tick(TODAY, AT8);
    DayState before = actual.state();
    Schedule demo;
    demo.initialize(1, AT8 - 5, false);
    demo.tick(1, AT8);
    demo.opening(1, AT8 + 1);
    CHECK(demo.tick(1, AT9).action == NoAction);
    sameState(before, actual.state());
    CHECK(actual.tick(TODAY, AT9).action == ContinuousTenSeconds);
  });

  std::printf("\n%d cases, %d failures\n", cases, failures);
  return failures == 0 ? 0 : 1;
}
