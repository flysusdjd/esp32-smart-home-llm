import os

import paho.mqtt.client as mqtt
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import threading
import pyodbc
import logging
import time
import json

# ============ 配置区域 ============
# Broker 配置从环境变量读取（仓库里不放明文凭据）：
#   MQTT_BROKER / MQTT_PORT / MQTT_USERNAME / MQTT_PASSWORD
MQTT_BROKER = os.getenv("MQTT_BROKER", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = f"mqtt-flask-app-{int(time.time())}"

# 板子1主题
BOARD1_PREFIX = "board1/"
BOARD1_LED_CONTROL = BOARD1_PREFIX + "led/control"
BOARD1_LED_STATUS = BOARD1_PREFIX + "led/status"
BOARD1_LED_MODE = BOARD1_PREFIX + "led/mode"
BOARD1_LIGHT_SENSOR = BOARD1_PREFIX + "sensor/light"
BOARD1_PIR_SENSOR = BOARD1_PREFIX + "sensor/pir"
BOARD1_THRESHOLD = BOARD1_PREFIX + "config/light_threshold"
BOARD1_DEVICE_STATUS = BOARD1_PREFIX + "device/status"

# 板子2主题
BOARD2_PREFIX = "board2/"
BOARD2_FAN_CONTROL = BOARD2_PREFIX + "relay/control"
BOARD2_FAN_STATUS = BOARD2_PREFIX + "relay/status"
BOARD2_FAN_MODE = BOARD2_PREFIX + "relay/mode"
BOARD2_TEMP_SENSOR = BOARD2_PREFIX + "sensor/temperature"
BOARD2_HUMID_SENSOR = BOARD2_PREFIX + "sensor/humidity"
BOARD2_TEMP_SET = BOARD2_PREFIX + "config/temp_threshold"
BOARD2_HUMID_SET = BOARD2_PREFIX + "config/humidity_threshold"

# 板子3主题
BOARD3_PREFIX = "board3/"
BOARD3_SMOKE_SENSOR = BOARD3_PREFIX + "sensor/smoke_analog"
BOARD3_BUZZER_CONTROL = BOARD3_PREFIX + "buzzer/control"
BOARD3_SERVO_CONTROL = BOARD3_PREFIX + "servo/control"  # 修改为舵机控制
BOARD3_BUZZER_STATUS = BOARD3_PREFIX + "buzzer/status"
BOARD3_SERVO_STATUS = BOARD3_PREFIX + "servo/status"    # 修改为舵机状态
BOARD3_MODE = BOARD3_PREFIX + "system/mode"
BOARD3_THRESHOLD = BOARD3_PREFIX + "config/smoke_threshold"

SQL_CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    "DATABASE=iotdb;"
    "Trusted_Connection=yes;"
)

# ============ Flask ============
app = Flask(__name__)
CORS(app, supports_credentials=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# ============ 数据存储 ============
class DeviceData:
    def __init__(self):
        # 板子1数据
        self.board1 = {
            "light_intensity": None,
            "human_presence": None,
            "led_status": None,
            "led_mode": None,
            "light_threshold": 1500
        }
        # 板子2数据
        self.board2 = {
            "temperature": None,
            "humidity": None,
            "fan_status": None,
            "fan_mode": None,
            "temp_threshold": 20.0,
            "humidity_threshold": 90.0
        }
        # 板子3数据
        self.board3 = {
            "smoke_value": None,
            "buzzer_status": None,
            "servo_status": None,  # 修改为舵机状态
            "system_mode": None,
            "smoke_threshold": 500
        }
        self.lock = threading.Lock()

    def update_board1(self, topic, payload):
        with self.lock:
            try:
                if topic == BOARD1_LIGHT_SENSOR:
                    self.board1["light_intensity"] = int(payload)
                elif topic == BOARD1_PIR_SENSOR:
                    self.board1["human_presence"] = "有人" if payload == "1" else "无人"
                elif topic == BOARD1_LED_STATUS:
                    self.board1["led_status"] = payload
                elif topic == BOARD1_LED_MODE:
                    self.board1["led_mode"] = payload
                elif topic == BOARD1_THRESHOLD:
                    self.board1["light_threshold"] = int(payload)

                logging.info(f"板子1数据更新: {self.board1}")
                self._save_to_db("board1")
            except Exception as e:
                logging.error(f"更新板子1数据失败: {e}")

    def update_board2(self, topic, payload):
        with self.lock:
            try:
                if topic == BOARD2_TEMP_SENSOR:
                    self.board2["temperature"] = float(payload)
                elif topic == BOARD2_HUMID_SENSOR:
                    self.board2["humidity"] = float(payload)
                elif topic == BOARD2_FAN_STATUS:
                    self.board2["fan_status"] = payload
                elif topic == BOARD2_FAN_MODE:
                    self.board2["fan_mode"] = payload
                elif topic == BOARD2_TEMP_SET:
                    self.board2["temp_threshold"] = float(payload)
                elif topic == BOARD2_HUMID_SET:
                    self.board2["humidity_threshold"] = float(payload)

                logging.info(f"板子2数据更新: {self.board2}")
                self._save_to_db("board2")
            except Exception as e:
                logging.error(f"更新板子2数据失败: {e}")

    def update_board3(self, topic, payload):
        with self.lock:
            try:
                if topic == BOARD3_SMOKE_SENSOR:
                    self.board3["smoke_value"] = int(payload)
                elif topic == BOARD3_BUZZER_STATUS:
                    self.board3["buzzer_status"] = payload.upper()
                elif topic == BOARD3_SERVO_STATUS:
                    self.board3["servo_status"] = payload.upper()  # 直接存储ON/OFF
                elif topic == BOARD3_MODE:
                    self.board3["system_mode"] = payload.upper()
                elif topic == BOARD3_THRESHOLD:
                    self.board3["smoke_threshold"] = int(payload)

                logging.info(f"板子3数据更新: {self.board3}")
                self._save_to_db("board3")

                # 自动控制逻辑
                if topic == BOARD3_SMOKE_SENSOR:
                    if self.board3["system_mode"] == "AUTO":
                        smoke_value = int(payload)
                        threshold = self.board3["smoke_threshold"]

                        if smoke_value > threshold:
                            self.publish(BOARD3_BUZZER_CONTROL, "ON")
                            self.publish(BOARD3_SERVO_CONTROL, "ON")  # 修改点4：使用ON
                        else:
                            self.publish(BOARD3_BUZZER_CONTROL, "OFF")
                            self.publish(BOARD3_SERVO_CONTROL, "OFF")  # 修改点5：使用OFF

            except Exception as e:
                logging.error(f"更新板子3数据失败: {e}")



    def _save_to_db(self, device):
        try:
            conn = pyodbc.connect(SQL_CONN_STR)
            cursor = conn.cursor()

            if device == "board1":
                cursor.execute("""
                               INSERT INTO board1_data
                               (light_intensity, human_presence, led_status, led_mode, light_threshold)
                               VALUES (?, ?, ?, ?, ?)
                               """,
                               self.board1["light_intensity"],
                               self.board1["human_presence"],
                               self.board1["led_status"],
                               self.board1["led_mode"],
                               self.board1["light_threshold"]
                               )
            elif device == "board2":
                cursor.execute("""
                               INSERT INTO board2_data
                               (temperature, humidity, fan_status, fan_mode, temp_threshold, humidity_threshold)
                               VALUES (?, ?, ?, ?, ?, ?)
                               """,
                               self.board2["temperature"],
                               self.board2["humidity"],
                               self.board2["fan_status"],
                               self.board2["fan_mode"],
                               self.board2["temp_threshold"],
                               self.board2["humidity_threshold"]
                               )
            elif device == "board3":
                cursor.execute("""
                               INSERT INTO board3_data
                               (smoke_value, buzzer_status, servo_status, system_mode, smoke_threshold)
                               VALUES (?, ?, ?, ?, ?)
                               """,
                               self.board3["smoke_value"],
                               self.board3["buzzer_status"],
                               self.board3["servo_status"],
                               self.board3["system_mode"],
                               self.board3["smoke_threshold"],
                               )

            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"保存到数据库失败: {e}")

    def get_board1_data(self):
        with self.lock:
            return self.board1.copy()

    def get_board2_data(self):
        with self.lock:
            return self.board2.copy()

    def get_board3_data(self):
        with self.lock:
            return self.board3.copy()


# ============ MQTT 客户端 ============
class MQTTClient:
    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.device_data = DeviceData()
        self.lock = threading.Lock()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logging.info("MQTT连接成功")
            # 订阅所有相关主题
            client.subscribe([
                (BOARD1_LIGHT_SENSOR, 0),
                (BOARD1_PIR_SENSOR, 0),
                (BOARD1_LED_STATUS, 0),
                (BOARD1_LED_MODE, 0),
                (BOARD1_THRESHOLD, 0),
                (BOARD2_TEMP_SENSOR, 0),
                (BOARD2_HUMID_SENSOR, 0),
                (BOARD2_FAN_STATUS, 0),
                (BOARD2_FAN_MODE, 0),
                (BOARD3_SMOKE_SENSOR, 0),
                (BOARD3_BUZZER_STATUS, 0),
                (BOARD3_SERVO_STATUS, 0),
                (BOARD3_MODE, 0),
                (BOARD3_THRESHOLD, 0)
            ])
        else:
            logging.error(f"MQTT连接失败，错误码: {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            logging.info(f"收到消息 [{msg.topic}]: {payload}")

            # 根据主题前缀分发到不同的处理函数
            if msg.topic.startswith(BOARD1_PREFIX):
                self.device_data.update_board1(msg.topic, payload)
            elif msg.topic.startswith(BOARD2_PREFIX):
                self.device_data.update_board2(msg.topic, payload)
            elif msg.topic.startswith(BOARD3_PREFIX):
                self.device_data.update_board3(msg.topic, payload)

                if msg.topic == BOARD3_SMOKE_SENSOR:
                    with self.device_data.lock:
                        board3_data = self.device_data.board3
                        if board3_data["system_mode"] == "AUTO":
                            smoke_value = int(payload)
                            threshold = board3_data["smoke_threshold"]

                            if smoke_value > threshold:
                                self.publish(BOARD3_BUZZER_CONTROL, "ON")
                                self.publish(BOARD3_SERVO_CONTROL, "ON")
                            else:
                                self.publish(BOARD3_BUZZER_CONTROL, "OFF")
                                self.publish(BOARD3_SERVO_CONTROL, "OFF")

        except Exception as e:
            logging.error(f"处理MQTT消息失败: {e}")

    def start(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        self.client.loop_start()

    def publish(self, topic, payload):
        self.client.publish(topic, payload)
        logging.info(f"已发布消息 [{topic}]: {payload}")


# ============ Flask 路由 ============
@app.route("/")
def home():
    return render_template("index.html")


@app.route('/status/board1', methods=['GET'])
def get_board1_status():
    try:
        board1_data = mqtt_client.device_data.get_board1_data()
        return jsonify({
            "status": "success",
            "data": {
                "light_intensity": board1_data["light_intensity"],
                "human_presence": board1_data["human_presence"],
                "led_status": board1_data["led_status"],
                "led_mode": board1_data["led_mode"],
                "light_threshold": board1_data["light_threshold"]
            }
        })
    except Exception as e:
        logging.error(f"获取板子1状态失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/status/board2', methods=['GET'])
def get_board2_status():
    try:
        board2_data = mqtt_client.device_data.get_board2_data()
        return jsonify({
            "status": "success",
            "data": {
                "temperature": board2_data["temperature"],
                "humidity": board2_data["humidity"],
                "fan_status": board2_data["fan_status"],
                "fan_mode": board2_data["fan_mode"],
                "temp_threshold": board2_data["temp_threshold"],
                "humidity_threshold": board2_data["humidity_threshold"]
            }
        })
    except Exception as e:
        logging.error(f"获取板子2状态失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/status/board3', methods=['GET'])
def get_board3_status():
    try:
        board3_data = mqtt_client.device_data.get_board3_data()
        return jsonify({
            "status": "success",
            "data": {
                "smoke_value": board3_data["smoke_value"],
                "buzzer_status": board3_data["buzzer_status"],
                "servo_status": board3_data["servo_status"],
                "system_mode": board3_data["system_mode"],
                "smoke_threshold": board3_data["smoke_threshold"]
            }
        })
    except Exception as e:
        logging.error(f"获取板子3状态失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/control/board1', methods=['POST'])
def control_board1():
    try:
        data = request.get_json()
        command = data.get("command", "").upper()

        if command not in ["ON", "OFF", "AUTO"]:
            return jsonify({"status": "error", "message": "无效命令"}), 400

        # 如果是手动控制，设置模式为MANUAL
        if command in ["ON", "OFF"]:
            with mqtt_client.device_data.lock:
                mqtt_client.device_data.board1["led_mode"] = "MANUAL"

        mqtt_client.publish(BOARD1_LED_CONTROL, command)
        return jsonify({
            "status": "success",
            "message": f"已发送LED控制命令: {command}",
            "mode": "MANUAL" if command in ["ON", "OFF"] else "AUTO"
        })
    except Exception as e:
        logging.error(f"控制板子1失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/control/board2', methods=['POST'])
def control_board2():
    try:
        data = request.get_json()
        command = data.get("command", "").upper()

        if command not in ["ON", "OFF", "AUTO"]:
            return jsonify({"status": "error", "message": "无效命令"}), 400

        mqtt_client.publish(BOARD2_FAN_CONTROL, command)
        return jsonify({"status": "success", "message": f"已发送风扇控制命令: {command}"})
    except Exception as e:
        logging.error(f"控制板子2失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/control/board3', methods=['POST'])
def control_board3():
    try:
        data = request.get_json()
        device = data.get("device", "").upper()  # "BUZZER" 或 "SERVO"
        command = data.get("command", "").upper()  # "ON"/"OFF" 或 "AUTO"  # 修改点2：去除OPEN/CLOSED

        if device not in ["BUZZER", "SERVO"]:
            return jsonify({"status": "error", "message": "无效设备"}), 400
        if command not in ["ON", "OFF", "AUTO"]:  # 修改点3：简化命令选项
            return jsonify({"status": "error", "message": "无效命令"}), 400

        # 对于设备3，AUTO模式是全局的
        if command == "AUTO":
            topic = BOARD3_MODE
            response_msg = f"已设置为自动模式"
            mqtt_client.publish(topic, command)
        else:
            if device == "BUZZER":
                topic = BOARD3_BUZZER_CONTROL
                cmd = command  # 直接使用ON/OFF
            else:  # SERVO
                topic = BOARD3_SERVO_CONTROL
                cmd = command  # 直接使用ON/OFF
            response_msg = f"已控制{device}: {cmd}"
            # 手动命令时明确设置模式为MANUAL
            mqtt_client.publish(BOARD3_MODE, "MANUAL")
            mqtt_client.device_data.board3["system_mode"] = "MANUAL"

        mqtt_client.publish(topic, command)
        return jsonify({
            "status": "success",
            "message": response_msg,
            "mode": "MANUAL" if command in ["ON", "OFF"] else "AUTO"
        })
    except Exception as e:
        logging.error(f"控制板子3失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/config/board1', methods=['POST'])
def config_board1():
    try:
        data = request.get_json()
        threshold = int(data.get("threshold", 0))

        if not (0 < threshold < 4095):
            return jsonify({"status": "error", "message": "无效阈值"}), 400

        mqtt_client.publish(BOARD1_THRESHOLD, str(threshold))
        return jsonify({"status": "success", "message": f"已设置光强阈值为: {threshold}"})
    except Exception as e:
        logging.error(f"配置板子1失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/config/board2', methods=['POST'])
def config_board2():
    try:
        data = request.get_json()

        # 初始化变量为None，表示不更新
        temp_threshold = None
        humid_threshold = None

        # 只处理提供的参数
        if 'temp_threshold' in data:
            temp_threshold = float(data['temp_threshold'])
            if not (-20 <= temp_threshold <= 80):
                return jsonify({"status": "error", "message": "无效温度阈值"}), 400

        if 'humidity_threshold' in data:
            humid_threshold = float(data['humidity_threshold'])
            if not (0 <= humid_threshold <= 100):
                return jsonify({"status": "error", "message": "无效湿度阈值"}), 400

        # 更新本地存储
        with mqtt_client.device_data.lock:
            if temp_threshold is not None:
                mqtt_client.device_data.board2["temp_threshold"] = temp_threshold
                mqtt_client.publish(BOARD2_TEMP_SET, str(temp_threshold))

            if humid_threshold is not None:
                mqtt_client.device_data.board2["humidity_threshold"] = humid_threshold
                mqtt_client.publish(BOARD2_HUMID_SET, str(humid_threshold))

        # 返回当前实际值
        current_data = mqtt_client.device_data.get_board2_data()
        return jsonify({
            "status": "success",
            "data": {
                "temp_threshold": current_data["temp_threshold"],
                "humidity_threshold": current_data["humidity_threshold"]
            },
            "message": "阈值更新成功"
        })
    except Exception as e:
        logging.error(f"配置板子2失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/config/board3', methods=['POST'])
def config_board3():
    try:
        data = request.get_json()
        threshold = int(data.get("threshold", 0))

        if not (0 < threshold < 4095):
            return jsonify({"status": "error", "message": "无效阈值"}), 400

        mqtt_client.publish(BOARD3_THRESHOLD, str(threshold))
        return jsonify({"status": "success", "message": f"已设置烟雾阈值为: {threshold}"})
    except Exception as e:
        logging.error(f"配置板子3失败: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ 初始化 ============
def init_database():
    try:
        conn = pyodbc.connect(SQL_CONN_STR)
        cursor = conn.cursor()

        # 创建板子1数据表
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM sysobjects WHERE name='board1_data' AND xtype='U'
            )
            CREATE TABLE board1_data (
                id INT IDENTITY(1,1) PRIMARY KEY,
                light_intensity INT,
                human_presence NVARCHAR(10),
                led_status NVARCHAR(10),
                led_mode NVARCHAR(10),
                light_threshold INT,
                timestamp DATETIME DEFAULT GETDATE()
            )
        """)

        # 创建板子2数据表
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM sysobjects WHERE name='board2_data' AND xtype='U'
            )
            CREATE TABLE board2_data (
                id INT IDENTITY(1,1) PRIMARY KEY,
                temperature FLOAT,
                humidity FLOAT,
                fan_status NVARCHAR(10),
                fan_mode NVARCHAR(10),
                temp_threshold FLOAT,
                humidity_threshold FLOAT,
                timestamp DATETIME DEFAULT GETDATE()
            )
        """)

        # 创建板子3数据表
        cursor.execute("""
            IF NOT EXISTS (
                SELECT * FROM sysobjects WHERE name='board3_data' AND xtype='U'
            )
            CREATE TABLE board3_data (
                id INT IDENTITY(1,1) PRIMARY KEY,
                smoke_value INT,
                buzzer_status NVARCHAR(10),
                servo_status NVARCHAR(20),
                system_mode NVARCHAR(10),
                smoke_threshold INT,
                timestamp DATETIME DEFAULT GETDATE()
            )
        """)

        conn.commit()
        conn.close()
        logging.info("数据库表初始化完成")
    except Exception as e:
        logging.error(f"数据库初始化失败: {e}")


# ============ 主程序 ============
if __name__ == "__main__":
    # 初始化数据库
    init_database()

    # 启动MQTT客户端
    mqtt_client = MQTTClient()
    mqtt_client.start()

    # 启动Flask应用
    logging.info("系统启动完成，访问 http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
