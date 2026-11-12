#include <Arduino.h>
#include <Wire.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <driver/gpio.h>
#include <sys/time.h>
#include <time.h>
#include "config.h"
#include "ReminderSchedule.h"

// 每日本地提醒：08:00 三声，09:00 未开盒连续响 10 秒。
// 不联网、不上传事件、不修改后端或微信通知规则。
Adafruit_SSD1306 display(128, 64, &Wire, -1);
Preferences storage;
BoxReminder::Schedule realSchedule;
BoxReminder::Schedule demoSchedule;
bool oledReady = false;
bool storageReady = false;
bool clockSynced = false;
bool clockBlocked = false;
bool demoMode = false;
uint32_t demoStartedAt = 0;
int closedLevel = VERIFIED_CLOSED_LEVEL;
int lastReading = HIGH;
int stableReading = -1;
uint32_t lastChangeAt = 0;
uint32_t lastFrameAt = 0;
uint32_t lastStatusAt = 0;
bool displayDirty = true;
String commandLine;
bool commandOverflow = false;
uint32_t lastSerialAt = 0;

// 0=静音，1=三声，2=连续十秒。所有响铃均非阻塞。
int soundMode = 0;
bool soundOn = false;
int beepsRemaining = 0;
uint32_t soundChangedAt = 0;
uint32_t longSoundStartedAt = 0;

void stopSound() {
  digitalWrite(BUZZER_PIN, HIGH);
  soundMode = 0;
  soundOn = false;
  beepsRemaining = 0;
  displayDirty = true;
}

void startSound(bool continuous) {
  soundMode = continuous ? 2 : 1;
  soundOn = true;
  beepsRemaining = continuous ? 0 : 3;
  digitalWrite(BUZZER_PIN, LOW);
  soundChangedAt = millis();
  longSoundStartedAt = soundChangedAt;
  Serial.print("SOUND_START mode="); Serial.print(continuous ? "continuous_10s" : "three_beeps");
  Serial.print(" start_ms="); Serial.println(longSoundStartedAt);
  displayDirty = true;
}

void updateSound(uint32_t now) {
  if (soundMode == 2) {
    if (now - longSoundStartedAt >= OVERDUE_SOUND_MS) {
      stopSound();
      Serial.print("SOUND_END continuous_10s elapsed_ms=");
      Serial.println(now - longSoundStartedAt);
    }
  } else if (soundMode == 1) {
    if (soundOn && now - soundChangedAt >= BEEP_ON_MS) {
      digitalWrite(BUZZER_PIN, HIGH);
      soundOn = false;
      soundChangedAt = now;
      beepsRemaining--;
      displayDirty = true;
      if (beepsRemaining == 0) {
        soundMode = 0;
        Serial.println("SOUND_END three_beeps");
      }
    } else if (!soundOn && now - soundChangedAt >= BEEP_OFF_MS) {
      digitalWrite(BUZZER_PIN, LOW);
      soundOn = true;
      soundChangedAt = now;
      displayDirty = true;
    }
  }
}

ClockReading realClock() {
  if (!clockSynced) return ClockReading();
  time_t stamp = time(NULL);
  struct tm local = {};
  if (!localtime_r(&stamp, &local) || local.tm_year + 1900 < 2020) return ClockReading();
  uint32_t day = (local.tm_year + 1900) * 10000U + (local.tm_mon + 1) * 100U + local.tm_mday;
  return ClockReading(true, day, local.tm_hour * 3600U + local.tm_min * 60U + local.tm_sec);
}

ClockReading activeClock(uint32_t now) {
  if (!demoMode) return realClock();
  uint32_t elapsed = now - demoStartedAt;
  uint32_t second;
  if (elapsed < DEMO_START_MS) {
    second = BoxReminder::REMINDER_SECOND - 5U + elapsed / 1000U;
  } else if (elapsed < DEMO_DEADLINE_MS) {
    second = BoxReminder::REMINDER_SECOND +
        (elapsed - DEMO_START_MS) * 3600U / (DEMO_DEADLINE_MS - DEMO_START_MS);
  } else {
    second = BoxReminder::DEADLINE_SECOND + (elapsed - DEMO_DEADLINE_MS) / 1000U;
  }
  return ClockReading(true, 1, second);  // 虚拟日仅属于 demoSchedule，绝不写 NVS。
}

void saveRealState() {
  if (!storageReady) return;
  const BoxReminder::DayState& state = realSchedule.state();
  uint64_t packed = (static_cast<uint64_t>(state.day) << 8) | state.flags;
  if (storage.putULong64("daily", packed) != sizeof(packed)) {
    storageReady = false;
    stopSound();
    Serial.println("STORAGE_ERROR automatic_schedule_disabled");
  }
}

void applyDecision(const BoxReminder::Decision& decision) {
  if (decision.action == BoxReminder::StopSound) stopSound();
  if (decision.clockBlocked) {
    clockBlocked = true;
    stopSound();
    return;
  }
  clockBlocked = false;
  if (!demoMode && decision.changed) saveRealState();
  if (!demoMode && !storageReady) return;
  if (decision.action == BoxReminder::ThreeBeeps) {
    Serial.println(demoMode ? "DEMO EVENT REMINDER_08 three_beeps" : "REAL EVENT REMINDER_08 three_beeps");
    startSound(false);
  } else if (decision.action == BoxReminder::ContinuousTenSeconds) {
    Serial.println(demoMode ? "DEMO EVENT OVERDUE_09 continuous_10s" : "REAL EVENT OVERDUE_09 continuous_10s");
    startSound(true);
  }
  if (decision.changed) displayDirty = true;
}

void updateReed(uint32_t now, const ClockReading& clock) {
  int reading = digitalRead(REED_PIN);
  if (reading != lastReading) { lastReading = reading; lastChangeAt = now; }
  if (now - lastChangeAt < DEBOUNCE_MS || stableReading == reading) return;
  int previous = stableReading;
  stableReading = reading;
  displayDirty = true;
  Serial.print("REED level="); Serial.println(stableReading);
  if (previous != closedLevel || stableReading == closedLevel) return;
  stopSound();
  if (!clock.valid) {
    Serial.println("OPEN_IGNORED clock_not_set");
    return;
  }
  BoxReminder::Schedule& schedule = demoMode ? demoSchedule : realSchedule;
  BoxReminder::Decision decision = schedule.opening(clock.day, clock.second);
  applyDecision(decision);
  Serial.print(demoMode ? "DEMO OPEN " : "REAL OPEN ");
  Serial.println(schedule.has(BoxReminder::OpenedInWindow) ? "on_time" : "outside_window_or_late");
}

const char* phaseText(const ClockReading& clock) {
  if (!clock.valid) return "NEED USB TIME";
  if (!demoMode && !storageReady) return "STORAGE ERROR";
  if (clockBlocked) return "CHECK CLOCK";
  const BoxReminder::Schedule& schedule = demoMode ? demoSchedule : realSchedule;
  if (schedule.has(BoxReminder::PastSkipped)) return "NEXT DAY";
  if (schedule.has(BoxReminder::OpenedInWindow)) return "OPENED IN WINDOW";
  if (schedule.has(BoxReminder::OpenedLate)) return "LATE OPEN / STOP";
  if (schedule.has(BoxReminder::OverdueDone)) return "OVERDUE / DONE";
  if (schedule.has(BoxReminder::ReminderDone)) return "WAIT FOR OPEN";
  return "WAIT 08:00";
}

void printStatus() {
  ClockReading clock = activeClock(millis());
  Serial.print("STATUS mode="); Serial.print(demoMode ? "DEMO" : "REAL");
  Serial.print(" clock="); Serial.print(clock.valid ? "SET" : "UNSET");
  Serial.print(" day="); Serial.print(clock.day);
  Serial.print(" sec="); Serial.print(clock.second);
  Serial.print(" lid="); Serial.print(stableReading < 0 ? "UNKNOWN" : stableReading == closedLevel ? "CLOSED" : "OPEN");
  Serial.print(" closed="); Serial.print(closedLevel);
  Serial.print(" sound="); Serial.print(soundMode);
  Serial.print(" oled="); Serial.print(oledReady ? 1 : 0);
  Serial.print(" nvs="); Serial.print(storageReady ? 1 : 0);
  Serial.print(" flags="); Serial.print((demoMode ? demoSchedule : realSchedule).state().flags);
  Serial.print(" phase="); Serial.println(phaseText(clock));
}

void endDemo() {
  if (!demoMode) return;
  stopSound();
  demoMode = false;
  displayDirty = true;
  Serial.println("DEMO_FINISHED real_clock_and_daily_state_preserved");
}

bool setClockFromText(const String& text) {
  int year, month, day, hour, minute, second, consumed = 0;
  if (sscanf(text.c_str(), "%d-%d-%d %d:%d:%d%n", &year, &month, &day,
             &hour, &minute, &second, &consumed) != 6 || consumed != (int)text.length() ||
      year < 2020 || year > 2099 || month < 1 || month > 12 || day < 1 || day > 31 ||
      hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return false;
  struct tm local = {};
  local.tm_year = year - 1900; local.tm_mon = month - 1; local.tm_mday = day;
  local.tm_hour = hour; local.tm_min = minute; local.tm_sec = second; local.tm_isdst = -1;
  time_t stamp = mktime(&local);
  if (stamp < 0 || local.tm_year != year - 1900 || local.tm_mon != month - 1 ||
      local.tm_mday != day || local.tm_hour != hour || local.tm_min != minute || local.tm_sec != second) return false;
  endDemo();
  stopSound();
  struct timeval value = {stamp, 0};
  if (settimeofday(&value, NULL) != 0) return false;
  clockSynced = true;
  ClockReading clock = realClock();
  BoxReminder::Decision init = realSchedule.initialize(clock.day, clock.second, true);
  applyDecision(init);
  Serial.print("TIME_OK UTC+8 "); Serial.println(text);
  if (realSchedule.has(BoxReminder::PastSkipped)) Serial.println("PAST_SKIPPED next_reminder_tomorrow_08:00");
  displayDirty = true;
  return true;
}

void handleCommand(String command) {
  command.trim();
  if (command == "?") { printStatus(); return; }
  if (command == "s") { stopSound(); Serial.println("SOUND_STOP"); return; }
  if (command == "b") { startSound(false); Serial.println("MANUAL three_beeps"); return; }
  if (command == "real") { endDemo(); printStatus(); return; }
  if (command == "demo") {
    stopSound();
    demoSchedule.restore(0, 0);
    demoStartedAt = millis();
    demoMode = true;
    clockBlocked = false;
    demoSchedule.initialize(1, BoxReminder::REMINDER_SECOND - 5U, false);
    displayDirty = true;
    Serial.println("DEMO_STARTED simulated_08_in_5s simulated_09_in_20s auto_exit_32s");
    return;
  }
  if (command == "c") {
    if (stableReading < 0 || stableReading != lastReading || digitalRead(REED_PIN) != stableReading ||
        millis() - lastChangeAt < DEBOUNCE_MS) { Serial.println("CALIBRATION_RETRY keep_magnet_close"); return; }
    closedLevel = stableReading;
    stopSound();
    if (!storageReady || storage.putInt("closed", closedLevel) != sizeof(int32_t)) {
      Serial.println("CALIBRATION_NOT_SAVED");
    } else {
      Serial.print("CLOSED_LEVEL_SAVED "); Serial.println(closedLevel);
    }
    displayDirty = true;
    return;
  }
  if (command.startsWith("time ")) {
    if (!setClockFromText(command.substring(5))) Serial.println("TIME_ERROR use_time_YYYY-MM-DD_HH:MM:SS");
    return;
  }
  Serial.println("COMMANDS ? | b | s | c | demo | real | time YYYY-MM-DD HH:MM:SS");
}

void readSerial(uint32_t now) {
  while (Serial.available() > 0) {
    char byte = Serial.read();
    lastSerialAt = now;
    if (byte == '\r' || byte == '\n') {
      if (commandOverflow) Serial.println("COMMAND_TOO_LONG");
      else if (commandLine.length()) handleCommand(commandLine);
      commandLine = ""; commandOverflow = false;
    } else if (!commandOverflow && static_cast<unsigned char>(byte) >= 32) {
      if (commandLine.length() < 80) commandLine += byte;
      else { commandLine = ""; commandOverflow = true; }
    }
  }
  if (!commandOverflow && now - lastSerialAt >= 80 &&
      (commandLine == "?" || commandLine == "b" || commandLine == "s" ||
       commandLine == "c" || commandLine == "demo" || commandLine == "real")) {
    handleCommand(commandLine); commandLine = "";
  }
}

void drawScreen(uint32_t now) {
  if (!oledReady || (!displayDirty && now - lastFrameAt < 1000)) return;
  lastFrameAt = now; displayDirty = false;
  ClockReading clock = activeClock(now);
  display.clearDisplay(); display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE); display.setTextWrap(false);
  display.setCursor(0, 0); display.print("DAILY REMINDER");
  char line[28];
  display.setCursor(0, 10);
  if (clock.valid) {
    snprintf(line, sizeof(line), "%s %02lu:%02lu:%02lu", demoMode ? "DEMO" : "REAL",
             (unsigned long)(clock.second / 3600U), (unsigned long)(clock.second / 60U % 60U),
             (unsigned long)(clock.second % 60U));
    display.print(line);
  } else display.print("NEED USB TIME");
  display.setCursor(0, 20); display.print("08:00 -> 3 beeps");
  display.setCursor(0, 30); display.print("09:00 -> 10s overdue");
  display.setCursor(0, 40); display.print(phaseText(clock));
  display.setCursor(0, 50);
  display.print(stableReading < 0 ? "Lid:? " : stableReading == closedLevel ? "CLOSED " : "OPEN ");
  display.print(soundMode == 0 ? "SILENT" : soundMode == 1 ? "3 BEEPS" : "10s ALARM");
  display.display();
}

void setup() {
  gpio_set_level(static_cast<gpio_num_t>(BUZZER_PIN), 1);
  pinMode(BUZZER_PIN, OUTPUT); stopSound();
  pinMode(REED_PIN, INPUT_PULLUP);
  Serial.begin(115200); delay(300);
  setenv("TZ", "CST-8", 1); tzset();
  commandLine.reserve(80);
  storageReady = storage.begin("box-local-time", false);
  if (storageReady) {
    uint64_t packed = storage.getULong64("daily", 0);
    if (!realSchedule.restore(static_cast<uint32_t>(packed >> 8), static_cast<uint8_t>(packed))) storageReady = false;
    int savedLevel = storage.getInt("closed", VERIFIED_CLOSED_LEVEL);
    if (savedLevel == LOW || savedLevel == HIGH) closedLevel = savedLevel;
  }
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.beginTransmission(0x3C);
  if (Wire.endTransmission() == 0) oledReady = display.begin(SSD1306_SWITCHCAPVCC, 0x3C, true, false);
  lastReading = digitalRead(REED_PIN); lastChangeAt = millis();
  Serial.println("DAILY_REMINDER_READY UTC+8 08:00=3_beeps 09:00=10s_if_unopened");
  Serial.println("NEED_TIME send: time YYYY-MM-DD HH:MM:SS (Beijing time)");
  Serial.println("COMMANDS ? | b | s | c | demo | real | time YYYY-MM-DD HH:MM:SS");
  printStatus(); drawScreen(millis());
}

void loop() {
  uint32_t now = millis();
  readSerial(now);
  now = millis();  // 命令可能刚启动演练/响铃，不能沿用更早的 millis 值。
  if (demoMode && now - demoStartedAt >= DEMO_END_MS) endDemo();
  ClockReading clock = activeClock(now);
  // 先处理开盒，再判断超时；开盒不会额外触发旧测试中的三声。
  updateReed(now, clock);
  if (clock.valid && (demoMode || storageReady)) {
    BoxReminder::Schedule& schedule = demoMode ? demoSchedule : realSchedule;
    applyDecision(schedule.tick(clock.day, clock.second));
  }
  now = millis();  // NVS 写入完成后再计响铃时长，避免旧时间相减回绕。
  updateSound(now); drawScreen(now);
  if (now - lastStatusAt >= 5000) { lastStatusAt = now; printStatus(); }
  delay(5);
}
