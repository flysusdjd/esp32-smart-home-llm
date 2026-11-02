#include <WiFi.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>

/********************* 配置区域 *********************/
// WiFi配置
#include "secrets.h"  // WIFI_SSID / WIFI_PASS / MQTT_HOST / MQTT_USER / MQTT_PASS
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASS;

// MQTT配置
const char* mqttServer = MQTT_HOST;
const int mqttPort = 1883;
const char* mqttUser = MQTT_USER;
const char* mqttPassword = MQTT_PASS;
const char* clientId = "board3_esp32-c6-final";

// MQTT主题配置
#define TOPIC_PREFIX "board3/"
#define TOPIC_SMOKE_ANALOG TOPIC_PREFIX "sensor/smoke_analog"
#define TOPIC_BUZZER TOPIC_PREFIX "buzzer/control"
#define TOPIC_SERVO TOPIC_PREFIX "servo/control"
#define TOPIC_BUZZER_STATUS TOPIC_PREFIX "buzzer/status"
#define TOPIC_SERVO_STATUS TOPIC_PREFIX "servo/status"
#define TOPIC_MODE TOPIC_PREFIX "system/mode"
#define TOPIC_THRESHOLD TOPIC_PREFIX "config/smoke_threshold"

// 引脚定义
const int MQ2_AO_PIN = 1;    // GPIO1 - 烟雾传感器模拟输入
const int BUZZER_PIN = 8;    // GPIO8 - 蜂鸣器控制
const int SERVO_PIN = 9;     // GPIO9 - 舵机控制

// 舵机角度设置
const int SERVO_CLOSED_ANGLE = 0;    // 窗户关闭角度
const int SERVO_OPEN_ANGLE = 90;     // 窗户打开角度

// 阈值设置
int SMOKE_THRESHOLD = 500;   // 烟雾检测阈值(0-4095)
const long UPDATE_INTERVAL = 1000; // 更新间隔缩短为1秒

/********************* 全局变量 *********************/
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
Servo windowServo;  // 创建舵机对象

unsigned long previousMillis = 0;

struct SensorData {
  int analogValue;
  bool smokeDetected;
} sensor;

struct SystemStatus {
  bool buzzerOn;
  bool windowOpen;
  bool isManualMode;
} status;

/********************* 初始化设置 *********************/
void setup() {
  Serial.begin(115200);
  while (!Serial); // 等待串口准备好
  Serial.println("\n=== 烟雾检测与窗户控制系统启动 ===");

  // 初始化引脚
  pinMode(MQ2_AO_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // 初始化舵机
  ESP32PWM::allocateTimer(0);
  windowServo.setPeriodHertz(50); // 标准50Hz舵机频率
  windowServo.attach(SERVO_PIN, 500, 2400); // 设置舵机脉冲宽度范围
  
  // 初始状态（自动模式）
  digitalWrite(BUZZER_PIN, LOW);
  windowServo.write(SERVO_CLOSED_ANGLE);
  status.isManualMode = false;
  status.buzzerOn = false;
  status.windowOpen = false;

  // 连接WiFi
  WiFi.begin(ssid, password);
  Serial.print("连接WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi已连接, IP: " + WiFi.localIP().toString());

  // 配置MQTT
  mqttClient.setServer(mqttServer, mqttPort);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(256);
  
  // 初始读取传感器
  readSensorData();
}

/********************* 主循环 *********************/
void loop() {
  // MQTT连接管理
  if (!mqttClient.connected()) {
    reconnectMQTT();
  }
  mqttClient.loop();
  
  // 定时读取传感器
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= UPDATE_INTERVAL) {
    previousMillis = currentMillis;
    
    // 读取传感器数据
    readSensorData();
    
    // 自动模式控制逻辑
    if (!status.isManualMode) {
      bool shouldAlarm = (sensor.analogValue > SMOKE_THRESHOLD);
      bool shouldOpenWindow = shouldAlarm;
      
      // 更新蜂鸣器状态
      if (shouldAlarm != status.buzzerOn) {
        digitalWrite(BUZZER_PIN, shouldAlarm ? HIGH : LOW);
        status.buzzerOn = shouldAlarm;
        mqttClient.publish(TOPIC_BUZZER_STATUS, shouldAlarm ? "ON" : "OFF");
        Serial.printf("[自动] 蜂鸣器状态更新: %s\n", shouldAlarm ? "ON" : "OFF");
      }
      
      // 更新窗户状态
      if (shouldOpenWindow != status.windowOpen) {
        windowServo.write(shouldOpenWindow ? SERVO_OPEN_ANGLE : SERVO_CLOSED_ANGLE);
        status.windowOpen = shouldOpenWindow;
        mqttClient.publish(TOPIC_SERVO_STATUS, shouldOpenWindow ? "ON" : "OFF");
        Serial.printf("[自动] 舵机状态更新: %s\n", shouldOpenWindow ? "ON" : "OFF");
      }
    }
    
    // 发布传感器数据（仅在值变化时发布）
    static int lastAnalogValue = -1;
    if (sensor.analogValue != lastAnalogValue) {
      char payload[10];
      snprintf(payload, sizeof(payload), "%d", sensor.analogValue);
      mqttClient.publish(TOPIC_SMOKE_ANALOG, payload);
      lastAnalogValue = sensor.analogValue;
      Serial.printf("[传感器] 烟雾值发布: %d\n", sensor.analogValue);
    }
    
    // 调试输出
    Serial.printf("[状态] 烟雾值: %d | 阈值: %d | 蜂鸣器: %s | 窗户: %s | 模式: %s\n",
                 sensor.analogValue,
                 SMOKE_THRESHOLD,
                 status.buzzerOn ? "ON" : "OFF",
                 status.windowOpen ? "ON" : "OFF",
                 status.isManualMode ? "手动" : "自动");
  }
}

/********************* 功能函数 *********************/
// 读取传感器数据
void readSensorData() {
  sensor.analogValue = analogRead(MQ2_AO_PIN);
  sensor.smokeDetected = (sensor.analogValue > SMOKE_THRESHOLD);
}

// MQTT回调函数（关键修改部分）
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // 构造有效消息字符串
  String msg;
  for (int i = 0; i < length; i++) {
    char c = (char)payload[i];
    if (isAlphaNumeric(c) || c == '.' || c == '-') msg += c;
  }
  msg.trim();
  msg.toUpperCase(); // 统一转为大写

  Serial.printf("MQTT消息 [%s]: %s\n", topic, msg.c_str());

  // 蜂鸣器控制
  if (String(topic) == TOPIC_BUZZER) {
    if (msg == "1" || msg == "ON") {
      if (!status.isManualMode) {
        status.isManualMode = true;
        mqttClient.publish(TOPIC_MODE, "MANUAL");
        Serial.println("[模式] 切换为手动控制");
      }
      status.buzzerOn = true;
      digitalWrite(BUZZER_PIN, HIGH);
      mqttClient.publish(TOPIC_BUZZER_STATUS, "ON");
      Serial.println("[手动] 蜂鸣器强制启动");
    }
    else if (msg == "0" || msg == "OFF") {
      if (!status.isManualMode) {
        status.isManualMode = true;
        mqttClient.publish(TOPIC_MODE, "MANUAL");
        Serial.println("[模式] 切换为手动控制");
      }
      status.buzzerOn = false;
      digitalWrite(BUZZER_PIN, LOW);
      mqttClient.publish(TOPIC_BUZZER_STATUS, "OFF");
      Serial.println("[手动] 蜂鸣器强制关闭");
    }
    else if (msg == "AUTO") {
      status.isManualMode = false;
      mqttClient.publish(TOPIC_MODE, "AUTO");
      
      // 立即读取传感器并更新状态
      readSensorData();
      bool shouldAlarm = (sensor.analogValue > SMOKE_THRESHOLD);
      
      digitalWrite(BUZZER_PIN, shouldAlarm ? HIGH : LOW);
      windowServo.write(shouldAlarm ? SERVO_OPEN_ANGLE : SERVO_CLOSED_ANGLE);
      status.buzzerOn = shouldAlarm;
      status.windowOpen = shouldAlarm;
      
      mqttClient.publish(TOPIC_BUZZER_STATUS, shouldAlarm ? "ON" : "OFF");
      mqttClient.publish(TOPIC_SERVO_STATUS, shouldAlarm ? "ON" : "OFF");
      
      Serial.printf("[自动] 初始化 - 烟雾值: %d | 阈值: %d | 蜂鸣器: %s | 窗户: %s\n",
                    sensor.analogValue, SMOKE_THRESHOLD,
                    shouldAlarm ? "ON" : "OFF",
                    shouldAlarm ? "ON" : "OFF");
      Serial.println("[模式] 成功切换为自动控制");
    }
  }
  
  // 舵机(窗户)控制
  else if (String(topic) == TOPIC_SERVO) {
    if (msg == "1" || msg == "ON") {
      if (!status.isManualMode) {
        status.isManualMode = true;
        mqttClient.publish(TOPIC_MODE, "MANUAL");
        Serial.println("[模式] 切换为手动控制");
      }
      status.windowOpen = true;
      windowServo.write(SERVO_OPEN_ANGLE);
      mqttClient.publish(TOPIC_SERVO_STATUS, "ON");
      Serial.println("[手动] 窗户强制打开");
    }
    else if (msg == "0" || msg == "OFF") {
      if (!status.isManualMode) {
        status.isManualMode = true;
        mqttClient.publish(TOPIC_MODE, "MANUAL");
        Serial.println("[模式] 切换为手动控制");
      }
      status.windowOpen = false;
      windowServo.write(SERVO_CLOSED_ANGLE);
      mqttClient.publish(TOPIC_SERVO_STATUS, "OFF");
      Serial.println("[手动] 窗户强制关闭");
    }
    else if (msg == "AUTO") {
      status.isManualMode = false;
      mqttClient.publish(TOPIC_MODE, "AUTO");
      
      readSensorData();
      bool shouldAlarm = (sensor.analogValue > SMOKE_THRESHOLD);
      
      digitalWrite(BUZZER_PIN, shouldAlarm ? HIGH : LOW);
      windowServo.write(shouldAlarm ? SERVO_OPEN_ANGLE : SERVO_CLOSED_ANGLE);
      status.buzzerOn = shouldAlarm;
      status.windowOpen = shouldAlarm;
      
      mqttClient.publish(TOPIC_BUZZER_STATUS, shouldAlarm ? "ON" : "OFF");
      mqttClient.publish(TOPIC_SERVO_STATUS, shouldAlarm ? "ON" : "OFF");
      
      Serial.printf("[自动] 初始化 - 烟雾值: %d | 阈值: %d | 蜂鸣器: %s | 窗户: %s\n",
                    sensor.analogValue, SMOKE_THRESHOLD,
                    shouldAlarm ? "ON" : "OFF",
                    shouldAlarm ? "ON" : "OFF");
      Serial.println("[模式] 窗户控制切换为自动");
    }
  }
  
  // 阈值调整
  else if (String(topic) == TOPIC_THRESHOLD) {
    int newVal = msg.toInt();
    if (newVal > 0 && newVal < 4095) {
      SMOKE_THRESHOLD = newVal;
      Serial.printf("[配置] 新烟雾阈值: %d\n", SMOKE_THRESHOLD);
      
      // 自动模式下立即响应阈值变化
      if (!status.isManualMode) {
        readSensorData();
        bool shouldAlarm = (sensor.analogValue > SMOKE_THRESHOLD);
        
        digitalWrite(BUZZER_PIN, shouldAlarm ? HIGH : LOW);
        windowServo.write(shouldAlarm ? SERVO_OPEN_ANGLE : SERVO_CLOSED_ANGLE);
        status.buzzerOn = shouldAlarm;
        status.windowOpen = shouldAlarm;
        
        mqttClient.publish(TOPIC_BUZZER_STATUS, shouldAlarm ? "ON" : "OFF");
        mqttClient.publish(TOPIC_SERVO_STATUS, shouldAlarm ? "ON" : "OFF");
        
        Serial.printf("[自动] 阈值更新 - 烟雾值: %d | 阈值: %d | 蜂鸣器: %s | 窗户: %s\n",
                      sensor.analogValue, SMOKE_THRESHOLD,
                      shouldAlarm ? "ON" : "OFF",
                      shouldAlarm ? "ON" : "OFF");
      }
    }
  }
}

// MQTT重连函数
void reconnectMQTT() {
  static unsigned long lastTry = 0;
  if (millis() - lastTry > 5000) {
    Serial.print("尝试MQTT连接...");
    if (mqttClient.connect(clientId, mqttUser, mqttPassword)) {
      Serial.println("成功！");
      
      // 订阅控制主题
      mqttClient.subscribe(TOPIC_BUZZER);
      mqttClient.subscribe(TOPIC_SERVO);
      mqttClient.subscribe(TOPIC_THRESHOLD);
      
      // 发布初始状态
      mqttClient.publish(TOPIC_MODE, status.isManualMode ? "MANUAL" : "AUTO");
      mqttClient.publish(TOPIC_BUZZER_STATUS, status.buzzerOn ? "ON" : "OFF");
      mqttClient.publish(TOPIC_SERVO_STATUS, status.windowOpen ? "ON" : "OFF");
    } else {
      Serial.printf("失败(code=%d)\n", mqttClient.state());
    }
    lastTry = millis();
  }
}