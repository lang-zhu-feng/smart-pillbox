#pragma once
#include <stdint.h>

// 本地测试计划，不修改服务端已有超时/微信规则。
// 时区按中国标准时间 UTC+8；真正的钟通过 USB time 命令校准。
static const int SDA_PIN = 21;
static const int SCL_PIN = 22;
static const int REED_PIN = 33;
static const int BUZZER_PIN = 25;
static const int VERIFIED_CLOSED_LEVEL = 0;  // 2026-11-08 本机实测磁铁贴近=0。
static const unsigned long DEBOUNCE_MS = 60;
static const unsigned long BEEP_ON_MS = 200;
static const unsigned long BEEP_OFF_MS = 400;
static const unsigned long OVERDUE_SOUND_MS = 10000;
static const unsigned long DEMO_END_MS = 32000;
static const unsigned long DEMO_START_MS = 5000;
static const unsigned long DEMO_DEADLINE_MS = 20000;

struct ClockReading {
  bool valid;
  uint32_t day;
  uint32_t second;
  ClockReading(bool ready = false, uint32_t date = 0, uint32_t seconds = 0)
      : valid(ready), day(date), second(seconds) {}
};
