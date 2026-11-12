#pragma once

// 2026-11-06 实测电脑 WLAN 地址；更换网络后可用串口 server 命令更新。
constexpr const char* DEFAULT_SERVER_BASE = "http://172.20.10.7:8766";
constexpr unsigned long SCHEDULE_REFRESH_MS = 60000;
constexpr unsigned long NETWORK_RETRY_MS = 15000;
