# Smart Home System (ESP32 + LLM)

English | [中文](README.md)

A course project that wires three ESP32-C6 boards into an MQTT smart-home stack: lighting with motion sensing, temperature/humidity with a fan relay, and gas alarm with a servo. A Flask dashboard speaks MQTT both ways, logs telemetry to SQL Server, and an MCP server exposes the same controls to a large language model (Zhipu GLM).

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Arduino](https://img.shields.io/badge/Arduino-ESP32--C6-00979D?logo=arduino&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-EMQX-660066)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

| Board | Sensors / actuators | Behaviour |
| --- | --- | --- |
| ESP1 | LDR, PIR, LED | Turns the light on when ambient light drops below a threshold or motion is detected; supports manual and mode switching from the dashboard |
| ESP2 | DHT11/22, relay-driven fan | Starts the fan above a temperature threshold; manual relay control and configurable threshold |
| ESP3 | MQ-2 gas sensor, buzzer, servo | Raises an alarm above the smoke threshold and drives the servo to "open the window" |

The Flask console talks to all three boards over MQTT, stores telemetry in SQL Server, and renders live gauges and device state. `mqtt_web_control/联网查询python代码/` hosts an MCP service that turns "turn on the light", "stop the fan", "what is the temperature" into tool calls for an LLM.

## Architecture

```text
┌────────────┐   MQTT/TCP    ┌──────────────┐   HTTP    ┌───────────────┐
│ ESP1/2/3   │◄─────────────►│  EMQX broker │◄─────────►│  Flask web    │
│ (ESP32-C6) │               │  (cloud)     │           │  console :5000│
└────────────┘               └──────┬───────┘           └───────┬───────┘
                                    │                           │
                                    │ MQTT                      │ pyodbc
                             ┌──────▼───────┐            ┌──────▼───────┐
                             │  MCP server  │◄──────────►│  SQL Server  │
                             │  (iot_control)│   tools    │  iotdb       │
                             └──────┬───────┘            └──────────────┘
                                    │
                             ┌──────▼───────┐
                             │   LLM (GLM)  │  natural-language control
                             └──────────────┘
```

## Layout

```text
.
├── ESP1/ESP1.ino                 # lighting + motion
├── ESP2/ESP2.ino                 # climate + fan
├── ESP3/ESP3.ino                 # gas alarm + servo
├── mqtt_web_control/
│   ├── app.py                    # Flask console + MQTT client
│   ├── iot_control.py            # MCP tools for the LLM
│   ├── mcp_pipe.py               # MCP transport
│   ├── templates/index.html      # dashboard
│   └── 联网查询python代码/        # GLM web-search client + MCP bridge
├── requirements.txt
└── secrets.example.h             # credential template
```

## Getting started

### 1. Flash the ESP32 boards

In Arduino IDE select the ESP32-C6 board, install `PubSubClient` and `DHT sensor library`, then copy `secrets.example.h` to `secrets.h` and fill in:

```c
#define WIFI_SSID   "your-wifi-ssid"
#define WIFI_PASS   "your-wifi-password"
#define MQTT_HOST   "your-broker-host"
#define MQTT_USER   "your-mqtt-user"
#define MQTT_PASS   "your-mqtt-password"
```

Flash `ESP1/ESP1.ino`, `ESP2/ESP2.ino`, `ESP3/ESP3.ino` respectively.

### 2. Run the dashboard

```bash
pip install -r requirements.txt
set MQTT_BROKER=your-broker-host
set MQTT_USERNAME=your-mqtt-user
set MQTT_PASSWORD=your-mqtt-password
python mqtt_web_control/app.py
```

Open <http://127.0.0.1:5000>.

The database defaults to a local SQL Server `iotdb` with Windows authentication; edit `SQL_CONN_STR` in `app.py` for your instance.

### 3. LLM control (optional)

```bash
cd mqtt_web_control/联网查询python代码
pip install -r requirements.txt
set ZHIPU_API_KEY=your-api-key
python 启动_main.py
```

## Security

No Wi-Fi password, MQTT credential or API key is committed:

- ESP32 credentials live in a local `secrets.h` (git-ignored); only `secrets.example.h` is tracked
- the web console reads MQTT credentials from environment variables
- the LLM API key comes from the environment or local config

## License

Released under the [MIT License](LICENSE).
