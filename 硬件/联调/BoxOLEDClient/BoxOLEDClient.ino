#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <cJSON.h>
#include "config.h"
#include "secrets.h"

// 第一阶段只使用已接好的 OLED 与 Wi-Fi。
// 不配置 GPIO25/33，不驱动蜂鸣器，不读取悬空门磁，不上传任何开盒事件。
Adafruit_SSD1306 display(128, 64, &Wire, -1);
bool screenReady = false;
bool wasConnected = false;
bool plansValid = false;
bool fetchRequested = true;
String deviceCode, deviceToken;
String serverBase = DEFAULT_SERVER_BASE;
String apiStatus = "Need binding";
String serverClock;
String serialLine;
bool serialOverflow = false;
unsigned long lastFetchAt = 0;
unsigned long lastFrameAt = 0;

struct PlanRow {
  String time;
  int count = 0;
};
PlanRow planRows[3];
const char* SLOT_KEYS[] = {"morning", "noon", "evening"};
const char* SLOT_LABELS[] = {"AM", "NO", "PM"};

const char* jsonString(cJSON* object, const char* key) {
  cJSON* value = cJSON_GetObjectItemCaseSensitive(object, key);
  return cJSON_IsString(value) && value->valuestring ? value->valuestring : "";
}

bool saveBinding(const String& code, const String& token, const String& server) {
  cJSON* config = cJSON_CreateObject();
  if (!config) return false;
  cJSON_AddStringToObject(config, "code", code.c_str());
  cJSON_AddStringToObject(config, "token", token.c_str());
  cJSON_AddStringToObject(config, "server", server.c_str());
  char* encoded = cJSON_PrintUnformatted(config);
  cJSON_Delete(config);
  if (!encoded) return false;
  Preferences storage;
  bool ok = false;
  if (storage.begin("medguard-stage1", false)) {
    ok = storage.putString("binding", encoded) == strlen(encoded);
    storage.end();
  }
  cJSON_free(encoded);
  return ok;
}

void loadBinding() {
  Preferences storage;
  if (!storage.begin("medguard-stage1", false)) return;
  String saved = storage.isKey("binding") ? storage.getString("binding", "") : "";
  storage.end();
  cJSON* config = cJSON_Parse(saved.c_str());
  if (!config) return;
  deviceCode = jsonString(config, "code");
  deviceToken = jsonString(config, "token");
  String storedServer = jsonString(config, "server");
  if (storedServer.startsWith("http://") && storedServer.length() < 120) serverBase = storedServer;
  cJSON_Delete(config);
}

bool validIdentifier(const String& value, unsigned int maximum) {
  if (!value.length() || value.length() > maximum) return false;
  for (unsigned int i = 0; i < value.length(); i++) {
    char c = value[i];
    if (!isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_') return false;
  }
  return true;
}

void printStatus() {
  Serial.println("BoxOLEDClient stage 1: OLED + WiFi + read-only schedule.");
  Serial.print("OLED: "); Serial.println(screenReady ? "OK" : "not detected at 0x3C");
  Serial.print("WiFi: "); Serial.println(WiFi.status() == WL_CONNECTED ? "connected" : "not connected");
  if (WiFi.status() == WL_CONNECTED) { Serial.print("ESP32 IP: "); Serial.println(WiFi.localIP()); }
  Serial.print("Backend: "); Serial.println(serverBase);
  Serial.print("Device binding: "); Serial.println(deviceToken.length() ? "configured (key hidden)" : "not configured");
  Serial.print("Schedule: "); Serial.println(apiStatus);
  Serial.println("Commands: ? | r | bind DEVICE_CODE DEVICE_TOKEN | server http://PC_IP:8766 | unbind");
  Serial.println("Sensor and buzzer are NOT enabled. No open-box events are sent.");
}

void handleCommand(String command) {
  command.trim();
  if (command == "?") { printStatus(); return; }
  if (command == "r") { fetchRequested = true; return; }
  if (command.startsWith("bind ")) {
    int separator = command.indexOf(' ', 5);
    if (separator < 0) { Serial.println("Format: bind DEVICE_CODE DEVICE_TOKEN"); return; }
    String code = command.substring(5, separator), token = command.substring(separator + 1);
    code.trim(); token.trim();
    if (!validIdentifier(code, 60) || !validIdentifier(token, 128) || token.length() < 16) {
      Serial.println("Invalid binding format; key is not echoed."); return;
    }
    if (!saveBinding(code, token, serverBase)) { Serial.println("Binding could not be saved."); return; }
    deviceCode = code; deviceToken = token; plansValid = false; fetchRequested = true;
    Serial.println("Binding saved locally; key hidden. Requesting schedule.");
    return;
  }
  if (command.startsWith("server ")) {
    String server = command.substring(7); server.trim();
    while (server.endsWith("/")) server.remove(server.length() - 1);
    if (!server.startsWith("http://") || server.length() < 9 || server.length() > 119 ||
        server.indexOf('/', 7) >= 0 || server.indexOf('@') >= 0 || server.indexOf(' ') >= 0 ||
        server.indexOf('?') >= 0 || server.indexOf('#') >= 0 ||
        server.startsWith("http://127.") || server.startsWith("http://localhost")) {
      Serial.println("Use this PC's LAN HTTP address, e.g. http://172.20.10.7:8766"); return;
    }
    if (!saveBinding(deviceCode, deviceToken, server)) { Serial.println("Server address could not be saved."); return; }
    serverBase = server; plansValid = false; fetchRequested = true;
    Serial.println("Backend address saved."); return;
  }
  if (command == "unbind") {
    if (!saveBinding("", "", serverBase)) { Serial.println("Could not clear binding."); return; }
    deviceCode = ""; deviceToken = ""; plansValid = false; apiStatus = "Need binding";
    Serial.println("Local binding cleared. The server key has not been revoked."); return;
  }
  Serial.println("Unknown command. Send ? for help; do not paste passwords here.");
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (serialOverflow) Serial.println("Command too long; discarded.");
      else if (serialLine.length()) handleCommand(serialLine);
      serialLine = ""; serialOverflow = false;
    } else if (static_cast<unsigned char>(c) >= 32 && !serialOverflow) {
      if (serialLine.length() < 256) serialLine += c;
      else { serialOverflow = true; serialLine = ""; }
    }
  }
}

bool decodeSchedule(const String& payload) {
  cJSON* document = cJSON_Parse(payload.c_str());
  if (!document) return false;
  cJSON* tasks = cJSON_GetObjectItemCaseSensitive(document, "tasks");
  bool ok = deviceCode == jsonString(document, "deviceCode") && cJSON_IsArray(tasks) && cJSON_GetArraySize(tasks) == 3;
  PlanRow rows[3];
  bool seen[] = {false, false, false};
  if (ok) {
    cJSON* task;
    cJSON_ArrayForEach(task, tasks) {
      int slot = -1;
      for (int i = 0; i < 3; i++) if (!strcmp(jsonString(task, "slotKey"), SLOT_KEYS[i])) slot = i;
      cJSON* medicines = cJSON_GetObjectItemCaseSensitive(task, "medicines");
      String start = jsonString(task, "startAt");
      if (slot < 0 || seen[slot] || !cJSON_IsArray(medicines) || start.length() < 19 || start[10] != 'T') { ok = false; break; }
      seen[slot] = true;
      rows[slot].time = start.substring(11, 16);
      rows[slot].count = cJSON_GetArraySize(medicines);
    }
  }
  String clock = jsonString(document, "serverTime");
  ok = ok && seen[0] && seen[1] && seen[2] && clock.length() >= 19 && clock[10] == 'T';
  if (ok) {
    for (int i = 0; i < 3; i++) planRows[i] = rows[i];
    serverClock = clock.substring(11, 19);
  }
  cJSON_Delete(document);
  return ok;
}

void fetchSchedule() {
  fetchRequested = false;
  lastFetchAt = millis();
  if (!deviceCode.length() || !deviceToken.length()) { apiStatus = "Need binding"; return; }
  if (WiFi.status() != WL_CONNECTED) { apiStatus = "WiFi offline"; plansValid = false; return; }
  apiStatus = "Loading...";
  WiFiClient connection;
  HTTPClient http;
  http.setConnectTimeout(2000);
  http.setTimeout(2000);
  if (!http.begin(connection, serverBase + "/api/device/schedule")) { apiStatus = "Bad address"; plansValid = false; return; }
  http.addHeader("Authorization", "Bearer " + deviceToken);
  const int status = http.GET();
  plansValid = false;
  if (status == 200 && http.getSize() <= 32768) {
    String payload = http.getString();
    plansValid = payload.length() <= 32768 && decodeSchedule(payload);
    apiStatus = plansValid ? "Schedule OK" : "Bad response";
  } else if (status == 401) apiStatus = "Key invalid";
  else if (status > 0) apiStatus = "HTTP " + String(status);
  else apiStatus = "PC unreachable";
  http.end();
  Serial.print("GET /api/device/schedule -> "); Serial.print(status);
  Serial.print("; "); Serial.println(apiStatus);
  if (plansValid) {
    Serial.print("Server time: "); Serial.println(serverClock);
    for (int i = 0; i < 3; i++) {
      Serial.print(SLOT_KEYS[i]); Serial.print(" "); Serial.print(planRows[i].time);
      Serial.print("; planned items: "); Serial.println(planRows[i].count);
    }
  }
}

void drawScreen() {
  if (!screenReady) return;
  display.clearDisplay();
  display.setTextSize(1); display.setTextColor(SSD1306_WHITE); display.setTextWrap(false);
  display.setCursor(0, 0); display.println("Box stage1: READ ONLY");
  display.setCursor(0, 10); display.print("WiFi ");
  if (WiFi.status() == WL_CONNECTED) display.print(WiFi.localIP());
  else display.print("connecting...");
  display.setCursor(0, 20); display.print(apiStatus);
  if (plansValid) {
    for (int i = 0; i < 3; i++) {
      display.setCursor(0, 30 + i * 10);
      display.print(SLOT_LABELS[i]); display.print(" "); display.print(planRows[i].time);
      display.print(" "); display.print(planRows[i].count ? String(planRows[i].count) + " item(s)" : "no plan");
    }
  } else {
    display.setCursor(0, 34); display.print("USB serial: 115200");
    display.setCursor(0, 46); display.print("Send ? for setup");
  }
  display.display();
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Wire.beginTransmission(0x3C);
  bool screenAcknowledged = Wire.endTransmission() == 0;
  screenReady = screenAcknowledged && display.begin(SSD1306_SWITCHCAPVCC, 0x3C, true, false);
  serialLine.reserve(256);
  loadBinding();
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  drawScreen(); printStatus();
}

void loop() {
  readSerial();
  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wasConnected) {
    Serial.print("WiFi connected; ESP32 IP: "); Serial.println(WiFi.localIP()); fetchRequested = true;
  }
  if (!connected && wasConnected) { plansValid = false; apiStatus = "WiFi offline"; Serial.println("WiFi disconnected."); }
  wasConnected = connected;
  const unsigned long interval = plansValid ? SCHEDULE_REFRESH_MS : NETWORK_RETRY_MS;
  if (connected && (fetchRequested || millis() - lastFetchAt >= interval)) fetchSchedule();
  if (millis() - lastFrameAt >= 500) { lastFrameAt = millis(); drawScreen(); }
  delay(5);
}
