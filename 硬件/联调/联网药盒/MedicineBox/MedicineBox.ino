#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <cJSON.h>
#include <sys/time.h>
#include <time.h>
#include "config.h"
#include "secrets.h"

// 联网版：计划以服务端为准；仅真实关->开边沿上传，不生成模拟事件或心跳。
Adafruit_SSD1306 screen(128, 64, &Wire, -1);
Preferences eventStore;
String deviceCode, deviceToken, serverBase = DEFAULT_SERVER_BASE;
String apiStatus = "Need binding", postStatus = "";
String serialLine;
bool serialOverflow = false, screenReady = false, clockReady = false;
bool scheduleReady = false, fetchRequested = true, wasConnected = false, storeReady = false;
unsigned long lastFetchAt = 0, lastPostAt = 0, lastFrameAt = 0, lastPlanAt = 0, lastQueueCheckAt = 0;
unsigned long postRetryDelay = NETWORK_RETRY_MS;
int closedLevel = DEFAULT_CLOSED_LEVEL, lastReading = HIGH, stableReading = -1;
unsigned long lastReadingAt = 0;
int soundMode = 0; // 0 静音，1 后续提醒五秒，2 超时十五秒，3 开盒确认两声，4 到点三声
unsigned long soundAt = 0;
int patternBeepsRemaining = 0;
bool patternBeepOn = false;
const char* QUEUE_KEYS[] = {"q0", "q1", "q2", "q3", "q4", "q5", "q6", "q7"};

struct TodayPlan {
  String date, slot, status, source;
  time_t start = 0, end = 0;
  int medicines = 0;
  int reminderCount = 0;
  bool resetSuppressed = false;
};
TodayPlan plan;
int intervalSeconds = 600, maxCount = 5, graceSeconds = 900;
int localReminderCount = 0;
bool localOverdueDone = false;
String localPlanDate;
time_t localPlanStart = 0;

const char* field(cJSON* object, const char* name) {
  cJSON* item = cJSON_GetObjectItemCaseSensitive(object, name);
  return cJSON_IsString(item) && item->valuestring ? item->valuestring : "";
}

bool parseBeijing(const String& value, time_t& result) {
  if (value.length() < 25 || !value.endsWith("+08:00") || value[10] != 'T') return false;
  String fractional = value.substring(19, value.length() - 6);
  if (fractional.length()) {
    if (fractional[0] != '.' || fractional.length() > 7) return false;
    for (size_t i = 1; i < fractional.length(); ++i)
      if (!isdigit((unsigned char)fractional[i])) return false;
  }
  int y, m, d, h, minute, s;
  if (sscanf(value.c_str(), "%4d-%2d-%2dT%2d:%2d:%2d+08:00", &y, &m, &d, &h, &minute, &s) != 6 ||
      y < 2020 || y > 2099 || m < 1 || m > 12 || d < 1 || d > 31 || h > 23 || minute > 59 || s > 59) return false;
  struct tm local = {};
  local.tm_year = y - 1900; local.tm_mon = m - 1; local.tm_mday = d;
  local.tm_hour = h; local.tm_min = minute; local.tm_sec = s; local.tm_isdst = -1;
  result = mktime(&local);
  return result > 0 && local.tm_year == y - 1900 && local.tm_mon == m - 1 && local.tm_mday == d &&
         local.tm_hour == h && local.tm_min == minute && local.tm_sec == s;
}

String dateText(time_t stamp) {
  struct tm local = {};
  localtime_r(&stamp, &local);
  char buffer[11];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d", &local);
  return String(buffer);
}

uint32_t dateNumber(time_t stamp) {
  struct tm local = {};
  localtime_r(&stamp, &local);
  return uint32_t(local.tm_year + 1900) * 10000U + uint32_t(local.tm_mon + 1) * 100U + local.tm_mday;
}

String timestampText(time_t stamp) {
  struct tm local = {};
  localtime_r(&stamp, &local);
  char buffer[26];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S+08:00", &local);
  return String(buffer);
}

bool saveBinding(const String& code, const String& token, const String& server) {
  cJSON* object = cJSON_CreateObject();
  if (!object) return false;
  cJSON_AddStringToObject(object, "code", code.c_str());
  cJSON_AddStringToObject(object, "token", token.c_str());
  cJSON_AddStringToObject(object, "server", server.c_str());
  char* encoded = cJSON_PrintUnformatted(object);
  cJSON_Delete(object);
  if (!encoded) return false;
  Preferences preferences;
  bool ok = preferences.begin("medguard-stage1", false) &&
      preferences.putString("binding", encoded) == strlen(encoded);
  preferences.end();
  cJSON_free(encoded);
  return ok;
}

void loadBinding() {
  Preferences preferences;
  if (!preferences.begin("medguard-stage1", true)) return;
  String encoded = preferences.getString("binding", "");
  preferences.end();
  cJSON* object = cJSON_Parse(encoded.c_str());
  if (!object) return;
  deviceCode = field(object, "code");
  deviceToken = field(object, "token");
  String savedServer = field(object, "server");
  if (savedServer.startsWith("http://") && savedServer.length() < 120) serverBase = savedServer;
  cJSON_Delete(object);
}

int firstPending() {
  if (!storeReady) return -1;
  for (int i = 0; i < 8; ++i) if (eventStore.getString(QUEUE_KEYS[i], "").length()) return i;
  return -1;
}

int pendingCount() {
  if (!storeReady) return 0;
  int count = 0;
  for (int i = 0; i < 8; ++i) if (eventStore.getString(QUEUE_KEYS[i], "").length()) ++count;
  return count;
}

bool queuedForDate(const String& date) {
  if (!storeReady) return false;
  for (int i = 0; i < 8; ++i) {
    String pending = eventStore.getString(QUEUE_KEYS[i], "");
    if (!pending.length()) continue;
    cJSON* object = cJSON_Parse(pending.c_str());
    bool match = object && String(field(object, "occurredAt")).startsWith(date + "T");
    cJSON_Delete(object);
    if (match) return true;
  }
  return false;
}

void clearQueuedForDate(const String& date) {
  if (!storeReady) return;
  for (int i = 0; i < 8; ++i) {
    String pending = eventStore.getString(QUEUE_KEYS[i], "");
    if (!pending.length()) continue;
    cJSON* object = cJSON_Parse(pending.c_str());
    bool match = object && String(field(object, "occurredAt")).startsWith(date + "T");
    cJSON_Delete(object);
    if (match) eventStore.remove(QUEUE_KEYS[i]);
  }
}

void persistReminderState() {
  if (!storeReady) return;
  eventStore.putUInt("planDay", dateNumber(localPlanStart));
  eventStore.putULong64("planStart", uint64_t(localPlanStart));
  eventStore.putInt("remCount", localReminderCount);
  eventStore.putBool("overdue", localOverdueDone);
}

void stopSound() {
  digitalWrite(BUZZER_PIN, HIGH);
  soundMode = 0;
  patternBeepsRemaining = 0;
  patternBeepOn = false;
}

void startSound(int mode, bool diagnostic = false) {
  stopSound();
  soundMode = mode;
  soundAt = millis();
  if (mode == 3 || mode == 4) {
    patternBeepsRemaining = mode == 3 ? 2 : 3;
    patternBeepOn = true;
  }
  digitalWrite(BUZZER_PIN, LOW);
  Serial.println(diagnostic ? "TEST_ACK 2 beeps (no event)" :
                 mode == 2 ? "LOCAL_OVERDUE 15s" : mode == 3 ? "OPEN_ACK 2 beeps" :
                 mode == 4 ? "LOCAL_START 3 beeps" : "LOCAL_REMINDER 5s");
}

void updateSound(unsigned long now) {
  if (soundMode == 3 || soundMode == 4) {
    if (patternBeepOn && now - soundAt >= CHIRP_ON_MS) {
      digitalWrite(BUZZER_PIN, HIGH);
      patternBeepOn = false;
      --patternBeepsRemaining;
      soundAt = now;
      if (patternBeepsRemaining == 0) stopSound();
    } else if (!patternBeepOn && now - soundAt >= CHIRP_GAP_MS) {
      digitalWrite(BUZZER_PIN, LOW);
      patternBeepOn = true;
      soundAt = now;
    }
    return;
  }
  unsigned long duration = soundMode == 1 ? REMINDER_SOUND_MS :
      soundMode == 2 ? OVERDUE_SOUND_MS : 0;
  if (soundMode != 0 && now - soundAt >= duration) stopSound();
}

bool decodeSchedule(const String& payload, time_t& serverStamp, TodayPlan& next,
                    int& nextInterval, int& nextMax, int& nextGrace, int& nextResetVersion) {
  cJSON* object = cJSON_Parse(payload.c_str());
  if (!object) return false;
  cJSON* tasks = cJSON_GetObjectItemCaseSensitive(object, "tasks");
  cJSON* policy = cJSON_GetObjectItemCaseSensitive(object, "reminderPolicy");
  cJSON* interval = cJSON_GetObjectItemCaseSensitive(policy, "intervalSeconds");
  cJSON* maximum = cJSON_GetObjectItemCaseSensitive(policy, "maxCount");
  cJSON* grace = cJSON_GetObjectItemCaseSensitive(policy, "graceSeconds");
  cJSON* resetVersion = cJSON_GetObjectItemCaseSensitive(object, "demoResetVersion");
  bool ok = deviceCode == field(object, "deviceCode") &&
      parseBeijing(field(object, "serverTime"), serverStamp) && cJSON_IsArray(tasks) &&
      cJSON_GetArraySize(tasks) == 3 && cJSON_IsNumber(interval) && cJSON_IsNumber(maximum) &&
      cJSON_IsNumber(grace) && cJSON_IsNumber(resetVersion) && resetVersion->valueint >= 0 &&
      resetVersion->valuedouble == resetVersion->valueint &&
      interval->valueint >= 60 && interval->valueint <= 3600 &&
      maximum->valueint >= 1 && maximum->valueint <= 12 && grace->valueint >= 0 && grace->valueint <= 7200;
  if (ok) {
    cJSON* task;
    int matches = 0;
    cJSON_ArrayForEach(task, tasks) {
      if (String(field(task, "slotKey")) != SENSOR_SLOT_KEY) continue;
      ++matches;
      cJSON* medicines = cJSON_GetObjectItemCaseSensitive(task, "medicines");
      cJSON* count = cJSON_GetObjectItemCaseSensitive(task, "reminderCount");
      next.date = field(task, "date"); next.slot = field(task, "slotKey");
      next.status = field(task, "status"); next.source = field(task, "source");
      next.resetSuppressed = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(task, "resetSuppressed"));
      next.medicines = cJSON_IsArray(medicines) ? cJSON_GetArraySize(medicines) : -1;
      next.reminderCount = cJSON_IsNumber(count) ? count->valueint : -1;
      ok = next.date == dateText(serverStamp) && next.medicines >= 0 && next.reminderCount >= 0 &&
          parseBeijing(field(task, "startAt"), next.start) &&
          parseBeijing(field(task, "endAt"), next.end) && next.start < next.end &&
          (next.status == "PENDING" || next.status == "REMINDING" ||
           next.status == "OVERDUE" || next.status == "COMPLETED" ||
           next.status == "CONFIRMED" || next.status == "NO_MEDICATION");
    }
    ok = ok && matches == 1;
  }
  if (ok) {
    nextInterval = interval->valueint; nextMax = maximum->valueint; nextGrace = grace->valueint;
    nextResetVersion = resetVersion->valueint;
  }
  cJSON_Delete(object);
  return ok;
}

void fetchSchedule() {
  fetchRequested = false;
  lastFetchAt = millis();
  if (!deviceCode.length() || !deviceToken.length()) { apiStatus = "Need binding"; return; }
  if (WiFi.status() != WL_CONNECTED) { apiStatus = "WiFi offline"; return; }
  WiFiClient connection;
  HTTPClient http;
  http.setConnectTimeout(2000); http.setTimeout(2000);
  if (!http.begin(connection, serverBase + "/api/device/schedule")) { apiStatus = "Bad address"; return; }
  http.addHeader("Authorization", "Bearer " + deviceToken);
  int code = http.GET();
  if (code == 200 && http.getSize() <= 32768) {
    String body = http.getString();
    TodayPlan next;
    time_t stamp = 0;
    int nextInterval, nextMax, nextGrace, nextResetVersion;
    if (body.length() <= 32768 && decodeSchedule(body, stamp, next, nextInterval, nextMax, nextGrace, nextResetVersion)) {
      struct timeval clockValue = {stamp, 0};
      if (settimeofday(&clockValue, nullptr) == 0) {
        clockReady = true; scheduleReady = true;
        bool justReset = false;
        if (storeReady && nextResetVersion != eventStore.getInt("resetVer", 0)) {
          clearQueuedForDate(next.date);
          eventStore.remove("doneDay"); eventStore.remove("doneStart");
          eventStore.remove("planDay"); eventStore.remove("planStart");
          eventStore.remove("remCount"); eventStore.remove("overdue");
          if (eventStore.putInt("resetVer", nextResetVersion) == sizeof(int32_t)) {
            localPlanDate = ""; localPlanStart = 0;
            localReminderCount = 0; localOverdueDone = false;
            justReset = true;
            Serial.println("DEMO_RESET applied; today's queued events cleared");
          } else postStatus = "Reset storage error";
        }
        if (next.date != localPlanDate || next.start != localPlanStart) {
          localPlanDate = next.date; localPlanStart = next.start;
          if (storeReady && eventStore.getUInt("planDay", 0) == dateNumber(next.start) &&
              eventStore.getULong64("planStart", 0) == uint64_t(next.start)) {
            localReminderCount = eventStore.getInt("remCount", 0);
            localOverdueDone = eventStore.getBool("overdue", false);
          } else {
            // 新计划下载时只补当前阶段，不连响错过的多个提醒。
            time_t now = time(nullptr);
            if (now >= next.start && now < next.end + nextGrace)
              localReminderCount = min(nextMax, int((now - next.start) / nextInterval) + 1) - (justReset ? 0 : 1);
            else localReminderCount = 0;
            localOverdueDone = now >= next.end + nextGrace;
            persistReminderState();
          }
        }
        plan = next;
        intervalSeconds = nextInterval; maxCount = nextMax; graceSeconds = nextGrace;
        if (plan.status == "CONFIRMED" || plan.status == "COMPLETED" ||
            plan.status == "NO_MEDICATION" || plan.resetSuppressed) stopSound();
        apiStatus = "Schedule OK";
      } else apiStatus = "Clock error";
    } else apiStatus = "Bad response";
  } else if (code == 401) { apiStatus = "Key invalid"; scheduleReady = false; stopSound(); }
  else if (code > 0) apiStatus = "HTTP " + String(code);
  else apiStatus = "PC unreachable";
  http.end();
  Serial.print("GET schedule -> "); Serial.println(apiStatus);
}

void postPending() {
  int index = firstPending();
  if (index < 0 || WiFi.status() != WL_CONNECTED || !deviceToken.length()) return;
  lastPostAt = millis();
  String body = eventStore.getString(QUEUE_KEYS[index], "");
  WiFiClient connection;
  HTTPClient http;
  http.setConnectTimeout(2000); http.setTimeout(2000);
  if (!http.begin(connection, serverBase + "/api/device/events")) { postStatus = "Bad address"; return; }
  http.addHeader("Authorization", "Bearer " + deviceToken);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  bool accepted = false;
  if (code == 200) {
    cJSON* reply = cJSON_Parse(http.getString().c_str());
    cJSON* ok = cJSON_GetObjectItemCaseSensitive(reply, "ok");
    cJSON* matched = cJSON_GetObjectItemCaseSensitive(reply, "matched");
    accepted = cJSON_IsTrue(ok) && cJSON_IsTrue(matched);
    cJSON_Delete(reply);
  }
  http.end();
  if (accepted) {
    eventStore.remove(QUEUE_KEYS[index]);
    postStatus = "Event uploaded";
    postRetryDelay = NETWORK_RETRY_MS;
  } else if (code == 401 || code == 403) { postStatus = "Check binding"; postRetryDelay = 60000; }
  else if (code == 409 || code == 422) { postStatus = "Event needs review"; postRetryDelay = 300000; }
  else { postStatus = "Upload retry"; postRetryDelay = NETWORK_RETRY_MS; }
  Serial.print("POST event -> "); Serial.print(code); Serial.print("; "); Serial.println(postStatus);
}

bool recordOpening(time_t stamp) {
  if (!clockReady || !scheduleReady || !storeReady || !plan.medicines ||
      plan.resetSuppressed || dateText(stamp) != plan.date || stamp < plan.start ||
      (plan.status == "COMPLETED" && plan.source == "hardware")) return false;
  // 同一天改设新时间是新的待办；只拦截同一次计划的重复开盒。
  if (eventStore.getULong64("doneStart", 0) == uint64_t(plan.start)) return false;
  if (queuedForDate(dateText(stamp))) return false;
  int freeSlot = -1;
  for (int i = 0; i < 8; ++i) if (!eventStore.getString(QUEUE_KEYS[i], "").length()) { freeSlot = i; break; }
  if (freeSlot < 0) { postStatus = "Queue full"; return false; }
  cJSON* object = cJSON_CreateObject();
  if (!object) return false;
  String id = deviceCode + "-" + String((uint32_t)stamp) + "-" + String(esp_random(), HEX);
  cJSON_AddStringToObject(object, "deviceCode", deviceCode.c_str());
  cJSON_AddStringToObject(object, "eventId", id.c_str());
  cJSON_AddStringToObject(object, "slotKey", SENSOR_SLOT_KEY);
  cJSON_AddStringToObject(object, "occurredAt", timestampText(stamp).c_str());
  char* encoded = cJSON_PrintUnformatted(object);
  cJSON_Delete(object);
  if (!encoded) return false;
  bool saved = eventStore.putString(QUEUE_KEYS[freeSlot], encoded) == strlen(encoded);
  cJSON_free(encoded);
  if (!saved) { postStatus = "Storage error"; return false; }
  eventStore.putULong64("doneStart", uint64_t(plan.start));
  postStatus = "Event queued";
  lastPostAt = 0;
  Serial.println("OPEN real edge; event queued");
  return true;
}

void updateReed(unsigned long now) {
  int reading = digitalRead(REED_PIN);
  if (reading != lastReading) { lastReading = reading; lastReadingAt = now; }
  if (now - lastReadingAt < DEBOUNCE_MS || reading == stableReading) return;
  int previous = stableReading;
  stableReading = reading;
  if (previous != closedLevel || reading == closedLevel) return;
  stopSound();
  if (clockReady) {
    time_t stamp = time(nullptr);
    if (recordOpening(stamp) && stamp < plan.end + graceSeconds) startSound(3);
  }
  else Serial.println("OPEN ignored: time not synchronized");
}

void updatePlan() {
  if (!clockReady || !scheduleReady || !storeReady ||
      plan.date != dateText(time(nullptr)) || !plan.medicines ||
      plan.resetSuppressed ||
      (plan.status == "COMPLETED" || plan.status == "CONFIRMED") ||
      eventStore.getULong64("doneStart", 0) == uint64_t(plan.start) ||
      queuedForDate(plan.date)) return;
  time_t now = time(nullptr);
  if (now < plan.start) return;
  time_t deadline = plan.end + graceSeconds;
  if (now >= deadline) {
    if (!localOverdueDone) { localOverdueDone = true; persistReminderState(); startSound(2); }
    return;
  }
  int dueCount = min(maxCount, int((now - plan.start) / intervalSeconds) + 1);
  if (dueCount > localReminderCount) {
    localReminderCount = dueCount;
    persistReminderState();
    startSound(localReminderCount == 1 ? 4 : 1);
  }
}

bool validIdentifier(const String& value, size_t maximum) {
  if (!value.length() || value.length() > maximum) return false;
  for (size_t i = 0; i < value.length(); ++i)
    if (!isalnum((unsigned char)value[i]) && value[i] != '-' && value[i] != '_') return false;
  return true;
}

void status() {
  Serial.print("WiFi: "); Serial.println(WiFi.status() == WL_CONNECTED ? "connected" : "offline");
  Serial.print("OLED: "); Serial.println(screenReady ? "OK" : "not detected");
  Serial.print("Backend: "); Serial.println(serverBase);
  Serial.print("Binding: "); Serial.println(deviceToken.length() ? "configured (key hidden)" : "not configured");
  Serial.print("Schedule: "); Serial.println(apiStatus);
  Serial.print("Open-event queue: "); Serial.println(pendingCount());
  Serial.print("Upload: "); Serial.println(postStatus);
  Serial.print("Lid: "); Serial.println(stableReading < 0 ? "unknown" : stableReading == closedLevel ? "closed" : "open");
  Serial.println("Commands: ? | r | s | c | t (2-beep test) | bind CODE KEY | server http://PC_IP:8766 | unbind");
}

void command(String line) {
  line.trim();
  if (line == "?") { status(); return; }
  if (line == "r") { fetchRequested = true; return; }
  if (line == "s") { stopSound(); return; }
  if (line == "t") { startSound(3, true); return; }
  if (line == "c") {
    if (stableReading < 0 || stableReading != digitalRead(REED_PIN)) { Serial.println("Close lid and retry c"); return; }
    closedLevel = stableReading;
    if (!storeReady || eventStore.putInt("closed", closedLevel) != sizeof(int32_t)) Serial.println("Calibration not saved");
    else Serial.println("Closed level saved");
    return;
  }
  if (line.startsWith("bind ")) {
    int split = line.indexOf(' ', 5);
    if (split < 0) { Serial.println("Format: bind CODE KEY"); return; }
    String code = line.substring(5, split), key = line.substring(split + 1);
    code.trim(); key.trim();
    if (!validIdentifier(code, 60) || !validIdentifier(key, 128) || key.length() < 16) { Serial.println("Invalid binding; key hidden"); return; }
    if (pendingCount() && code != deviceCode) { Serial.println("Pending events belong to old device; upload them first"); return; }
    if (!saveBinding(code, key, serverBase)) { Serial.println("Binding save failed"); return; }
    if (code != deviceCode) {
      localPlanDate = ""; localPlanStart = 0; localReminderCount = 0; localOverdueDone = false;
      if (storeReady) {
        eventStore.remove("doneDay"); eventStore.remove("doneStart"); eventStore.remove("resetVer"); eventStore.remove("planDay");
        eventStore.remove("planStart"); eventStore.remove("remCount"); eventStore.remove("overdue");
      }
    }
    deviceCode = code; deviceToken = key; scheduleReady = false; fetchRequested = true; lastPostAt = 0;
    Serial.println("Binding saved; key hidden"); return;
  }
  if (line.startsWith("server ")) {
    String address = line.substring(7); address.trim();
    while (address.endsWith("/")) address.remove(address.length() - 1);
    if (!address.startsWith("http://") || address.length() < 10 || address.length() > 119 ||
        address.indexOf('/', 7) >= 0 || address.indexOf('@') >= 0 || address.indexOf(' ') >= 0 ||
        address.indexOf('?') >= 0 || address.indexOf('#') >= 0 ||
        address.startsWith("http://127.") || address.startsWith("http://localhost")) {
      Serial.println("Use http://PC_LAN_IP:8766"); return;
    }
    if (!saveBinding(deviceCode, deviceToken, address)) { Serial.println("Address save failed"); return; }
    serverBase = address; scheduleReady = false; fetchRequested = true; lastPostAt = 0;
    Serial.println("Backend address saved"); return;
  }
  if (line == "unbind") {
    if (pendingCount()) { Serial.println("Upload pending events before unbind"); return; }
    if (!saveBinding("", "", serverBase)) { Serial.println("Unbind failed"); return; }
    deviceCode = ""; deviceToken = ""; scheduleReady = false; stopSound();
    Serial.println("Local binding cleared; server key remains active"); return;
  }
  Serial.println("Unknown command. Send ? for help");
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (serialOverflow) Serial.println("Command too long");
      else if (serialLine.length()) command(serialLine);
      serialLine = ""; serialOverflow = false;
    } else if ((unsigned char)c >= 32 && !serialOverflow) {
      if (serialLine.length() < 256) serialLine += c;
      else { serialLine = ""; serialOverflow = true; }
    }
  }
}

void drawScreen(unsigned long now) {
  if (!screenReady || now - lastFrameAt < 1000) return;
  lastFrameAt = now;
  screen.clearDisplay(); screen.setTextSize(1); screen.setTextColor(SSD1306_WHITE); screen.setTextWrap(false);
  screen.setCursor(0, 0); screen.println("MEDICINE BOX LIVE");
  screen.setCursor(0, 10); screen.print(WiFi.status() == WL_CONNECTED ? "WiFi OK " : "WiFi OFF ");
  screen.println(clockReady ? timestampText(time(nullptr)).substring(11, 16) : "no time");
  screen.setCursor(0, 20); screen.println(apiStatus);
  screen.setCursor(0, 30);
  if (scheduleReady) {
    if (plan.status == "CONFIRMED") screen.println("Family confirmed");
    else {
      screen.print(SENSOR_SLOT_KEY); screen.print(" ");
      screen.print(timestampText(plan.start).substring(11, 16));
      screen.print(" x"); screen.println(plan.medicines);
    }
  } else screen.println("No current schedule");
  screen.setCursor(0, 40); screen.print(stableReading < 0 ? "Lid ? " : stableReading == closedLevel ? "Closed " : "Open ");
  screen.println(soundMode == 2 ? "ALARM 15s" : soundMode == 1 ? "REMIND 5s" :
                 soundMode == 3 ? "OPEN OK" : soundMode == 4 ? "START 3x" : "quiet");
  screen.setCursor(0, 50); screen.print("Queue "); screen.print(pendingCount());
  screen.print(" "); screen.print(postStatus.substring(0, 12));
  screen.display();
}

void setup() {
  digitalWrite(BUZZER_PIN, HIGH);
  pinMode(BUZZER_PIN, OUTPUT); stopSound();
  pinMode(REED_PIN, INPUT_PULLUP);
  Serial.begin(115200);
  setenv("TZ", "CST-8", 1); tzset();
  serialLine.reserve(256);
  storeReady = eventStore.begin("box-live", false);
  if (storeReady) {
    int saved = eventStore.getInt("closed", DEFAULT_CLOSED_LEVEL);
    if (saved == LOW || saved == HIGH) closedLevel = saved;
  }
  loadBinding();
  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  Wire.beginTransmission(0x3C);
  if (Wire.endTransmission() == 0) screenReady = screen.begin(SSD1306_SWITCHCAPVCC, 0x3C, true, false);
  lastReading = digitalRead(REED_PIN); lastReadingAt = millis();
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.println("MEDICINE_BOX_LIVE ready; real events only; no heartbeat");
  status();
}

void loop() {
  unsigned long now = millis();
  readSerial();
  now = millis();
  updateReed(now);
  updateSound(now);
  if (now - lastPlanAt >= 200) { lastPlanAt = now; updatePlan(); }
  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wasConnected) { fetchRequested = true; Serial.println("WiFi connected"); }
  if (!connected && wasConnected) { apiStatus = "WiFi offline"; Serial.println("WiFi disconnected"); }
  wasConnected = connected;
  if (connected) {
    unsigned long interval = scheduleReady ? SCHEDULE_REFRESH_MS : NETWORK_RETRY_MS;
    if (fetchRequested || now - lastFetchAt >= interval) fetchSchedule();
    if (soundMode == 0 && now - lastQueueCheckAt >= 1000) {
      lastQueueCheckAt = now;
      if (pendingCount() && (lastPostAt == 0 || now - lastPostAt >= postRetryDelay)) postPending();
    }
  }
  drawScreen(millis());
  delay(5);
}
