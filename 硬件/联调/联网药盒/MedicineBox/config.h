#pragma once

// 与已验证的接线一致：OLED 21/22，低电平蜂鸣器 25，门磁 33。
constexpr int OLED_SDA_PIN = 21;
constexpr int OLED_SCL_PIN = 22;
constexpr int BUZZER_PIN = 25;
constexpr int REED_PIN = 33;
constexpr int DEFAULT_CLOSED_LEVEL = 0;

// 当前只有一个真实门磁；它只对应一个时段，默认早药格。
constexpr const char* SENSOR_SLOT_KEY = "morning";
constexpr const char* DEFAULT_SERVER_BASE = "http://172.20.10.7:8766";
constexpr unsigned long SCHEDULE_REFRESH_MS = 10000; // 家属确认后尽快停止本次提醒。
constexpr unsigned long NETWORK_RETRY_MS = 15000;
constexpr unsigned long DEBOUNCE_MS = 60;
constexpr unsigned long CHIRP_ON_MS = 200;
constexpr unsigned long CHIRP_GAP_MS = 400;
constexpr unsigned long REMINDER_SOUND_MS = 5000;
constexpr unsigned long OVERDUE_SOUND_MS = 15000;
