from mcp.server.fastmcp import FastMCP
import logging
import time
from app import (
    MQTTClient,
    BOARD1_LED_CONTROL, BOARD2_FAN_CONTROL, BOARD3_BUZZER_CONTROL, BOARD3_SERVO_CONTROL,
    BOARD1_LED_MODE, BOARD2_FAN_MODE, BOARD3_MODE,
    BOARD1_THRESHOLD, BOARD2_TEMP_SET, BOARD2_HUMID_SET, BOARD3_THRESHOLD
)

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('mcp.log'), logging.StreamHandler()]
)
logger = logging.getLogger('iot-mcp')

# 创建MCP服务器实例
mcp = FastMCP("IoT-Control-Server")

"""
设备映射表 - 物理设备的抽象表示
key: 开发板编号 (board_id)
value: 设备类型与MQTT控制主题的映射
物理设备解释:
1. 开发板1: LED灯 - 对应室内照明系统 (ON=开灯, OFF=关灯)
2. 开发板2: 风扇 - 对应排风/通风系统 (ON=启动排风, OFF=关闭排风)
3. 开发板3: 
   a) 蜂鸣器 - 对应报警装置 (ON=触发警报, OFF=关闭警报)
   b) 舵机(servo) - 对应窗户开关系统 (OPEN=开窗, CLOSED=关窗)
"""
DEVICE_MAPPING = {
    1: {
        "led": BOARD1_LED_CONTROL,  # LED照明控制
        "mode": BOARD1_LED_MODE,  # LED模式控制
        "threshold": BOARD1_THRESHOLD  # 光照阈值控制
    },
    2: {
        "fan": BOARD2_FAN_CONTROL,  # 风扇/排风系统控制
        "mode": BOARD2_FAN_MODE,  # 风扇模式控制
        "temp_threshold": BOARD2_TEMP_SET,  # 温度阈值
        "humid_threshold": BOARD2_HUMID_SET  # 湿度阈值
    },
    3: {
        "buzzer": BOARD3_BUZZER_CONTROL,  # 蜂鸣器/报警装置
        "servo": BOARD3_SERVO_CONTROL,  # 舵机/窗户开关
        "mode": BOARD3_MODE,  # 系统模式控制
        "smoke_threshold": BOARD3_THRESHOLD  # 烟雾阈值
    },
    # 扩展更多设备的位置...
}

# 阈值范围限制
THRESHOLD_LIMITS = {
    "light": (0, 4095),  # 光照传感器范围
    "temperature": (-20, 80),  # 温度传感器范围
    "humidity": (0, 100),  # 湿度传感器范围(百分比)
    "smoke": (0, 4095)  # 烟雾传感器范围
}


@mcp.tool()
def get_device_status(board_id: int = None) -> dict:
    """
    获取设备状态 - 获取物理设备的当前状态
    Args:
        board_id: (可选)指定开发板编号，不传则返回所有设备状态
    Returns:
        {
            "success": 操作状态,
            "data": {
                1: [板1的传感器数据和设备状态],
                2: [板2的传感器数据和设备状态],
                3: [板3的传感器数据和设备状态]
            }
        }

    实际设备解释:
    - 板1状态包含：LED灯的开关状态（反映实际照明状态）
    - 板2状态包含：风扇的转速/开关状态（反映排风系统状态）
    - 板3状态包含：
        a) 蜂鸣器状态（反映警报装置状态）
        b) 舵机角度/位置（反映窗户开合状态）
    """
    try:
        # 返回所有板卡状态（全系统概览）
        if board_id is None:
            return {
                "success": True,
                "data": {
                    1: MQTTClient.instance.device_data.get_board1_data(),
                    2: MQTTClient.instance.device_data.get_board2_data(),
                    3: MQTTClient.instance.device_data.get_board3_data()
                }
            }

        # 获取特定板卡状态
        data = {
            1: MQTTClient.instance.device_data.get_board1_data(),
            2: MQTTClient.instance.device_data.get_board2_data(),
            3: MQTTClient.instance.device_data.get_board3_data()
        }.get(board_id)

        return {
            "success": bool(data),
            "data": data if data else None,
            "error": f"Invalid board ID" if not data else None,
            "valid_ids": list(DEVICE_MAPPING.keys())
        }
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def control_device(board_id: int, device_type: str, action: str) -> dict:
    """
    控制物理设备 - 发送操作指令到实际设备
    Args:
        board_id: 开发板编号 (参见设备映射表)
        device_type: 设备类型 (led/fan/buzzer/servo/mode)
        action: 操作指令 (ON/OFF/AUTO)

    物理操作解释:
    - 控制LED: control_device(1, "led", "ON") = 开启室内照明
    - 控制风扇: control_device(2, "fan", "OFF") = 关闭排风系统
    - 控制蜂鸣器: control_device(3, "buzzer", "ON") = 触发安全警报
    - 控制舵机: control_device(3, "servo", "OFF") = 关闭窗户
    - 设置自动模式: control_device(1, "mode", "AUTO") = 设置LED自动控制模式

    Returns:
        {
            "success": 操作状态,
            "message": 执行结果描述,
            "timestamp": 操作时间戳
        }
    """
    try:
        action = action.upper()  # 统一转换为大写

        # 验证开发板ID有效性
        if board_id not in DEVICE_MAPPING:
            return {
                "success": False,
                "error": f"无效开发板ID，有效ID: {list(DEVICE_MAPPING.keys())}",
                "valid_ids": list(DEVICE_MAPPING.keys())
            }

        # 验证设备类型有效性
        if device_type not in DEVICE_MAPPING[board_id]:
            return {
                "success": False,
                "error": f"板卡{board_id}不支持{device_type}，支持类型: {list(DEVICE_MAPPING[board_id].keys())}",
                "valid_types": list(DEVICE_MAPPING[board_id].keys())
            }

        # 验证操作指令有效性
        valid_actions = ["ON", "OFF", "AUTO"]
        if action not in valid_actions:
            return {
                "success": False,
                "error": f"无效操作指令，有效指令: {valid_actions}",
                "valid_actions": valid_actions
            }

        # 处理模式设置的特殊情况
        if device_type == "mode":
            # 通过MQTT发送模式控制指令
            MQTTClient.instance.publish(
                topic=DEVICE_MAPPING[board_id][device_type],
                payload=action
            )

            # 生成设备名称映射 (用于友好消息)
            board_names = {
                1: "照明系统",
                2: "排风系统",
                3: "安全系统"
            }

            return {
                "success": True,
                "message": f"【{board_names.get(board_id, f'板卡{board_id}')}】已设置为{'自动' if action == 'AUTO' else '手动'}模式",
                "timestamp": int(time.time())
            }

        # 通过MQTT发送控制指令
        MQTTClient.instance.publish(
            topic=DEVICE_MAPPING[board_id][device_type],
            payload=action
        )

        # 如果是手动控制(ON/OFF)，设置模式为MANUAL
        if action in ["ON", "OFF"] and device_type != "mode":
            mode_topic = DEVICE_MAPPING[board_id].get("mode")
            if mode_topic:
                MQTTClient.instance.publish(mode_topic, "MANUAL")

        # 生成设备名称映射 (用于友好消息)
        device_names = {
            "led": "照明系统",
            "fan": "排风系统",
            "buzzer": "报警装置",
            "servo": "窗户"
        }

        return {
            "success": True,
            "message": f"【{device_names.get(device_type, device_type)}】已{'开启' if action == 'ON' else '关闭'}",
            "timestamp": int(time.time())
        }
    except Exception as e:
        logger.error(f"控制失败: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def set_threshold(board_id: int, threshold_type: str, value: float) -> dict:
    """
    设置设备阈值 - 配置自动控制系统的触发阈值
    Args:
        board_id: 开发板编号 (1,2,3)
        threshold_type: 阈值类型 (light/temperature/humidity/smoke)
        value: 阈值数值

    阈值设置示例:
    - 设置光照阈值: set_threshold(1, "light", 1500)
    - 设置温度阈值: set_threshold(2, "temperature", 25.5)
    - 设置湿度阈值: set_threshold(2, "humidity", 70.0)
    - 设置烟雾阈值: set_threshold(3, "smoke", 500)

    Returns:
        {
            "success": 操作状态,
            "message": 执行结果描述,
            "timestamp": 操作时间戳,
            "new_value": 设置后的阈值数值
        }
    """
    try:
        # 验证开发板ID有效性
        if board_id not in DEVICE_MAPPING:
            return {
                "success": False,
                "error": f"无效开发板ID，有效ID: {list(DEVICE_MAPPING.keys())}",
                "valid_ids": list(DEVICE_MAPPING.keys())
            }

        # 验证阈值类型与板卡匹配性
        threshold_mapping = {
            1: {"light": "threshold"},
            2: {"temperature": "temp_threshold", "humidity": "humid_threshold"},
            3: {"smoke": "smoke_threshold"}
        }

        if threshold_type not in threshold_mapping.get(board_id, {}):
            valid_types = list(threshold_mapping.get(board_id, {}).keys())
            return {
                "success": False,
                "error": f"板卡{board_id}不支持{threshold_type}阈值，支持类型: {valid_types}",
                "valid_types": valid_types
            }

        # 获取阈值范围限制
        min_val, max_val = THRESHOLD_LIMITS.get(threshold_type, (None, None))

        # 验证阈值范围
        if min_val is not None and max_val is not None:
            if not (min_val <= value <= max_val):
                return {
                    "success": False,
                    "error": f"无效{threshold_type}阈值，有效范围: {min_val}-{max_val}",
                    "min_value": min_val,
                    "max_value": max_val
                }

        # 获取对应的MQTT主题
        mqtt_topic_key = threshold_mapping[board_id][threshold_type]
        mqtt_topic = DEVICE_MAPPING[board_id][mqtt_topic_key]

        # 通过MQTT发送阈值设置指令
        MQTTClient.instance.publish(
            topic=mqtt_topic,
            payload=str(value)
        )

        # 更新本地数据存储
        if board_id == 1:
            MQTTClient.instance.device_data.board1["light_threshold"] = int(value)
        elif board_id == 2:
            if threshold_type == "temperature":
                MQTTClient.instance.device_data.board2["temp_threshold"] = float(value)
            else:
                MQTTClient.instance.device_data.board2["humidity_threshold"] = float(value)
        elif board_id == 3:
            MQTTClient.instance.device_data.board3["smoke_threshold"] = int(value)

        # 生成友好的阈值名称
        threshold_names = {
            "light": "光照",
            "temperature": "温度",
            "humidity": "湿度",
            "smoke": "烟雾"
        }

        return {
            "success": True,
            "message": f"【{threshold_names.get(threshold_type, threshold_type)}阈值】已设置为: {value}",
            "timestamp": int(time.time()),
            "new_value": value
        }
    except Exception as e:
        logger.error(f"设置阈值失败: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # 初始化MQTT客户端（单例模式）
    if not hasattr(MQTTClient, 'instance'):
        mqtt = MQTTClient()
        mqtt.start()
        MQTTClient.instance = mqtt

    # 启动MCP服务器
    mcp.run(transport="stdio")