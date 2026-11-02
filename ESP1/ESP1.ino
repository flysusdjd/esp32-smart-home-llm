#include <WiFi.h>
#include <PubSubClient.h>

// 网络配置
#include "secrets.h"  // WIFI_SSID / WIFI_PASS / MQTT_HOST / MQTT_USER / MQTT_PASS
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASS;
const char* mqttServer = MQTT_HOST;
const int mqttPort = 1883;
const char* mqttUser = MQTT_USER;
const char* mqttPassword = MQTT_PASS;
const char* clientId = "board1_esp32-c6-final";

// 引脚定义
#define LED_BUILTIN 8
#define LIGHT_SENSOR_PIN 4
#define PIR_SENSOR_PIN 5

// 光强阈值
int lightThreshold = 1500;

// 全局变量
WiFiClient espClient;
PubSubClient client(espClient);
unsigned long previousMillis = 0;
const long interval = 1000;  // 传感器读取间隔(ms)
bool isManualMode = false;
bool pirState = false;
bool lastPirState = false;
bool lastLedState = false;

void setup() {
  Serial.begin(115200);
  
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(LIGHT_SENSOR_PIN, INPUT);
  pinMode(PIR_SENSOR_PIN, INPUT);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.println("Running hardware test...");
  digitalWrite(LED_BUILTIN, HIGH);
  delay(1000);
  digitalWrite(LED_BUILTIN, LOW);
  
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected");

  client.setServer(mqttServer, mqttPort);
  client.setCallback(callback);
  client.setBufferSize(256);
  
  // 初始连接MQTT
  reconnect();
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // 读取传感器数据
    int lightValue = 4095 - analogRead(LIGHT_SENSOR_PIN);
    pirState = digitalRead(PIR_SENSOR_PIN);
    bool currentLedState = digitalRead(LED_BUILTIN);

    // 发布传感器数据
    char lightMsg[10];
    sprintf(lightMsg, "%d", lightValue);
    client.publish("board1/sensor/light", lightMsg);
    
    if (pirState != lastPirState) {
      client.publish("board1/sensor/pir", pirState ? "1" : "0");
      lastPirState = pirState;
    }

    // 发布LED状态
    if (currentLedState != lastLedState) {
      client.publish("board1/led/status", currentLedState ? "ON" : "OFF");
      lastLedState = currentLedState;
    }

    // 自动控制逻辑
    if (!isManualMode) {
      bool shouldLightOn = (lightValue < lightThreshold && pirState);
      if (shouldLightOn != currentLedState) {
        digitalWrite(LED_BUILTIN, shouldLightOn ? HIGH : LOW);
        Serial.printf("自动控制: LED %s\n", shouldLightOn ? "开启" : "关闭");
      }
    }

    // 打印调试信息
    Serial.printf("光照: %d, 人体: %s, LED: %s, 模式: %s\n", 
                 lightValue, 
                 pirState ? "有人" : "无人", 
                 currentLedState ? "ON" : "OFF",
                 isManualMode ? "手动" : "自动");
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  // 确保payload以null结尾
  char message[length + 1];
  memcpy(message, payload, length);
  message[length] = '\0';
  
  Serial.printf("收到消息 [%s]: %s\n", topic, message);

  if (String(topic) == "board1/led/control") {
    String msg = String(message);
    msg.trim();
    
    if (msg == "1" || msg.equalsIgnoreCase("ON")) {
      isManualMode = true;
      digitalWrite(LED_BUILTIN, HIGH);
      client.publish("board1/led/status", "ON");
      Serial.println("LED手动开启");
    } else if (msg == "0" || msg.equalsIgnoreCase("OFF")) {
      isManualMode = true;
      digitalWrite(LED_BUILTIN, LOW);
      client.publish("board1/led/status", "OFF");
      Serial.println("LED手动关闭");
    } else if (msg.equalsIgnoreCase("AUTO")) {
      isManualMode = false;
      client.publish("board1/led/mode", "AUTO");
      Serial.println("恢复自动控制模式");
    }
  }

  if (String(topic) == "board1/config/light_threshold") {
    int newThreshold = String(message).toInt();
    if (newThreshold > 0 && newThreshold < 4095) {
      lightThreshold = newThreshold;
      Serial.printf("光强阈值已更新为: %d\n", lightThreshold);
      char thresholdMsg[10];
      sprintf(thresholdMsg, "%d", lightThreshold);
      client.publish("board1/config/current_threshold", thresholdMsg);
    }
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("尝试MQTT连接...");
    if (client.connect(clientId, mqttUser, mqttPassword)) {
      Serial.println("MQTT Connected");
      
      // 订阅主题
      client.subscribe("board1/led/control");
      client.subscribe("board1/config/light_threshold");
      
      // 发布初始状态
      client.publish("board1/device/status", "online");
      client.publish("board1/led/mode", isManualMode ? "MANUAL" : "AUTO");
      
    } else {
      Serial.printf("失败, rc=%d 重试中...\n", client.state());
      delay(5000);
    }
  }
}