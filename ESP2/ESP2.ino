#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>

// 网络配置
#include "secrets.h"  // WIFI_SSID / WIFI_PASS / MQTT_HOST / MQTT_USER / MQTT_PASS
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASS;
const char* mqttServer = MQTT_HOST;
const int mqttPort = 1883;
const char* mqttUser = MQTT_USER;
const char* mqttPassword = MQTT_PASS;
const char* clientId = "board2_esp32-c6-final";

// 硬件引脚定义
#define RELAY_PIN 8     // 继电器控制引脚（接IN）
#define I2C_SDA 21      // I2C数据线
#define I2C_SCL 22      // I2C时钟线

// 阈值设置
float tempThreshold = 26.0;      // 温度阈值(℃)
float humidityThreshold = 90.0;  // 湿度阈值(%)

// 传感器配
#define HT30_I2C_ADDR 0x44       // GT-HT30默认地址

// MQTT主题配置
#define TOPIC_PREFIX "board2/"
#define TOPIC_TEMP TOPIC_PREFIX "sensor/temperature"
#define TOPIC_HUMID TOPIC_PREFIX "sensor/humidity"
#define TOPIC_RELAY TOPIC_PREFIX "relay/control"
#define TOPIC_RELAY_STATUS TOPIC_PREFIX "relay/status"
#define TOPIC_MODE TOPIC_PREFIX "relay/mode"
#define TOPIC_TEMP_SET TOPIC_PREFIX "config/temp_threshold"
#define TOPIC_HUMID_SET TOPIC_PREFIX "config/humidity_threshold"

WiFiClient espClient;
PubSubClient client(espClient);
unsigned long previousMillis = 0;
const long interval = 2000;  // 传感器读取间隔(ms)

// 系统状态
bool isManualMode = false;
bool relayState = false;

void setup() {
  Serial.begin(115200);
  
  // 初始化I2C
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000);
  Wire.setTimeOut(50);
  
  // 初始化继电器（默认关闭风扇）
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  
  Serial.println("\n=== 风扇控制系统启动 ===");
  Serial.println("继电器初始化完成（默认关闭状态）");

  // 连接WiFi
  WiFi.begin(ssid, password);
  Serial.print("连接WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi已连接, IP: " + WiFi.localIP().toString());

  // 配置MQTT
  client.setServer(mqttServer, mqttPort);
  client.setCallback(callback);
  client.setBufferSize(256);
}

void loop() {
  // MQTT连接管理
  if (!client.connected()) {
    reconnect();
  }
  client.loop();
  
  // 定时读取传感器
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;
    
    float temperature, humidity;
    if (readHT30(temperature, humidity)) {
      // 控制逻辑
      bool needFanOn = false;
      
      if (isManualMode) {
        // 手动模式：保持当前状态
        needFanOn = relayState;
      } else {
        // 自动模式：双超标时启动风扇
        needFanOn = (temperature > tempThreshold) && (humidity > humidityThreshold);
      }
      
      // 更新继电器状态
      digitalWrite(RELAY_PIN, needFanOn ? HIGH : LOW);
      
      // 状态报告
      Serial.printf("[状态] 温度: %.1f℃ | 湿度: %.1f%% | 风扇: %s | 模式: %s\n",
                   temperature, humidity, 
                   needFanOn ? "ON" : "OFF",
                   isManualMode ? "手动" : "自动");
      
      // 发布传感器数据
      char payload[10];
      dtostrf(temperature, 4, 1, payload);
      client.publish(TOPIC_TEMP, payload);
      dtostrf(humidity, 4, 1, payload);
      client.publish(TOPIC_HUMID, payload);
      
      // 发布继电器状态
      client.publish(TOPIC_RELAY_STATUS, needFanOn ? "ON" : "OFF");
    } else {
      Serial.println("[错误] 传感器读取失败！");
    }
  }
}

bool readHT30(float &temperature, float &humidity) {
  // 发送测量命令（带重试）
  for (int retry = 0; retry < 3; retry++) {
    Wire.beginTransmission(HT30_I2C_ADDR);
    Wire.write(0x2C);
    Wire.write(0x06);
    if (Wire.endTransmission() == 0) break;
    delay(5);
  }
  
  delay(50);  // 等待测量完成
  
  // 读取6字节数据
  Wire.requestFrom(HT30_I2C_ADDR, 6);
  unsigned long start = millis();
  while (Wire.available() < 6 && millis() - start < 100) delay(1);
  
  if (Wire.available() < 6) return false;
  
  uint8_t data[6];
  for (int i = 0; i < 6; i++) data[i] = Wire.read();
  
  // CRC校验
  if (!checkCRC(data, 2) || !checkCRC(data+3, 2)) return false;
  
  // 数据转换
  temperature = (((data[0] << 8) | data[1]) * 175.0 / 65535.0) - 45.0;
  humidity = ((data[3] << 8) | data[4]) * 100.0 / 65535.0;
  return true;
}

bool checkCRC(uint8_t *data, uint8_t len) {
  uint8_t crc = 0xFF;
  for (uint8_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t j = 0; j < 8; j++) {
      crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : (crc << 1);
    }
  }
  return (crc == data[len]);
}

void callback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (int i = 0; i < length; i++) {
    char c = (char)payload[i];
    if (isAlphaNumeric(c) || c == '.' || c == '-') msg += c;
  }
  msg.trim();

  if (String(topic) == TOPIC_RELAY) {
    if (msg == "1" || msg.equalsIgnoreCase("ON")) {
      isManualMode = true;
      relayState = true;
      digitalWrite(RELAY_PIN, HIGH);
      Serial.println("[手动] 风扇强制启动");
    }
    else if (msg == "0" || msg.equalsIgnoreCase("OFF")) {
      isManualMode = true;
      relayState = false;
      digitalWrite(RELAY_PIN, LOW);
      Serial.println("[手动] 风扇强制关闭");
    }
    else if (msg.equalsIgnoreCase("AUTO")) {
      isManualMode = false;
      Serial.println("[模式] 切换为自动控制");
    }
    // 统一在loop()中发布状态，避免重复
  }
  
  // 阈值更新只修改本地变量，不发布状态
  else if (String(topic) == TOPIC_TEMP_SET) {
    float newVal = msg.toFloat();
    if (newVal >= -20 && newVal <= 80) {
      tempThreshold = newVal;
      Serial.printf("[配置] 新温度阈值: %.1f℃\n", tempThreshold);
    }
  }
  
  else if (String(topic) == TOPIC_HUMID_SET) {
    float newVal = msg.toFloat();
    if (newVal >= 0 && newVal <= 100) {
      humidityThreshold = newVal;
      Serial.printf("[配置] 新湿度阈值: %.1f%%\n", humidityThreshold);
    }
  }
}

void reconnect() {
  static unsigned long lastTry = 0;
  if (millis() - lastTry > 5000) {
    Serial.print("尝试MQTT连接...");
    if (client.connect(clientId, mqttUser, mqttPassword)) {
      Serial.println("成功！");
      
      // 订阅控制主题
      client.subscribe(TOPIC_RELAY);
      client.subscribe(TOPIC_TEMP_SET);
      client.subscribe(TOPIC_HUMID_SET);
      
      // 发布初始状态
      client.publish(TOPIC_MODE, "AUTO");
      client.publish(TOPIC_RELAY_STATUS, "OFF");
    } else {
      Serial.printf("失败(code=%d)\n", client.state());
    }
    lastTry = millis();
  }
}