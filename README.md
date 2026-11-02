# 智能家居系统（ESP32 + 大模型）

[English](README.en.md) | 中文

基于 ESP32-C6 与 MQTT 的智能家居课程设计：三块开发板分别负责照明与人体感应、温湿度与风扇、烟雾报警与舵机，配合 Flask 网页控制台、SQL Server 数据记录，以及接入了大模型（智谱 GLM）的自然语言控制入口。

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Arduino](https://img.shields.io/badge/Arduino-ESP32--C6-00979D?logo=arduino&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-EMQX-660066)
![License](https://img.shields.io/badge/License-MIT-green)

## 功能

| 板卡 | 传感器 / 执行器 | 功能 |
| --- | --- | --- |
| ESP1 | 光敏电阻、PIR 人体感应、LED | 环境光低于阈值自动开灯；检测到人自动亮灯；支持网页/语音手动开关与模式切换 |
| ESP2 | DHT 温湿度、继电器风扇 | 温度超过阈值自动开风扇；网页可手动控制继电器与设定阈值 |
| ESP3 | MQ-2 烟雾传感器、蜂鸣器、舵机 | 烟雾浓度超阈值报警并联动舵机（模拟开窗/排风） |

网页控制台（Flask）通过 MQTT 与三块板子双向通信，把遥测数据写入 SQL Server，并提供实时曲线与设备状态面板。`mqtt_web_control/联网查询python代码/` 里是一个 MCP 服务，把「开灯 / 关风扇 / 查温度」等操作暴露给大模型，实现自然语言控制。

## 系统架构

```text
┌────────────┐   MQTT/TCP    ┌──────────────┐   HTTP    ┌───────────────┐
│ ESP1/2/3   │◄─────────────►│  EMQX Broker │◄─────────►│  Flask Web    │
│ (ESP32-C6) │               │  (阿里云)     │           │  控制台 :5000 │
└────────────┘               └──────┬───────┘           └───────┬───────┘
                                    │                           │
                                    │ MQTT                      │ pyodbc
                             ┌──────▼───────┐            ┌──────▼───────┐
                             │  MCP Server  │◄──────────►│  SQL Server  │
                             │  (iot_control)│   工具调用  │  iotdb       │
                             └──────┬───────┘            └──────────────┘
                                    │
                             ┌──────▼───────┐
                             │ 大模型（GLM） │  自然语言控制
                             └──────────────┘
```

## 目录结构

```text
.
├── ESP1/ESP1.ino                 # 照明 + 人体感应
├── ESP2/ESP2.ino                 # 温湿度 + 风扇
├── ESP3/ESP3.ino                 # 烟雾报警 + 舵机
├── mqtt_web_control/
│   ├── app.py                    # Flask 控制台 + MQTT 客户端
│   ├── iot_control.py            # MCP 工具（供大模型调用）
│   ├── mcp_pipe.py               # MCP 传输层
│   ├── templates/index.html      # 前端页面
│   └── 联网查询python代码/        # 智谱 GLM 联网查询 + MCP 客户端
├── requirements.txt
└── secrets.example.h             # 凭据模板
```

## 快速开始

### 1. 烧录 ESP32

Arduino IDE 中选择对应开发板（ESP32-C6），安装 `PubSubClient`、`DHT sensor library` 库，然后把 `secrets.example.h` 复制为 `secrets.h` 并填入：

```c
#define WIFI_SSID   "your-wifi-ssid"
#define WIFI_PASS   "your-wifi-password"
#define MQTT_HOST   "your-broker-host"
#define MQTT_USER   "your-mqtt-user"
#define MQTT_PASS   "your-mqtt-password"
```

分别烧录 `ESP1/ESP1.ino`、`ESP2/ESP2.ino`、`ESP3/ESP3.ino`。

### 2. 启动网页控制台

```bash
pip install -r requirements.txt
set MQTT_BROKER=your-broker-host
set MQTT_USERNAME=your-mqtt-user
set MQTT_PASSWORD=your-mqtt-password
python mqtt_web_control/app.py
```

浏览器打开 <http://127.0.0.1:5000>。

数据库默认连接本机 SQL Server 的 `iotdb`（Windows 集成认证），可在 `app.py` 的 `SQL_CONN_STR` 中修改。

### 3. 大模型控制（可选）

```bash
cd mqtt_web_control/联网查询python代码
pip install -r requirements.txt
set ZHIPU_API_KEY=your-api-key
python 启动_main.py
```

## 安全说明

仓库内**不含**任何 Wi-Fi 密码、MQTT 账号或 API Key：

- ESP32 的配置放在本地 `secrets.h`（已被 `.gitignore` 忽略），仓库只提供 `secrets.example.h`
- 网页端从环境变量读取 MQTT 凭据
- 大模型 API Key 从环境变量或本地配置读取

## 许可

本项目采用 [MIT License](LICENSE)。
