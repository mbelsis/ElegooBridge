"""The whole bridge: fake Centauri on one side, a recording MQTT stand-in on the other."""
import json
import threading
import time
import unittest

try:
    from elegoobridge.bridge import Bridge
except ImportError:  # paho-mqtt not installed
    Bridge = None

from elegoobridge import sdcp
from elegoobridge.config import Config
from tests.test_sdcp import BOARD, FakePrinter


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish(self, topic, body, qos=0):
        self.published.append((topic, json.loads(body)))

    def reports(self):
        return [b["print"] for t, b in self.published if b.get("print", {}).get("command") == "push_status"]


class Message:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()


def printing(code, task="t1", light=0):
    return {"CurrentStatus": [1], "LightStatus": {"SecondLight": light},
            "PrintInfo": {"Status": code, "Filename": "cube.gcode", "TaskId": task, "Progress": 40,
                          "CurrentTicks": 300, "TotalTicks": 805, "CurrentLayer": 58, "TotalLayer": 128}}


@unittest.skipIf(Bridge is None, "paho-mqtt is not installed")
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.old_delay = sdcp.RECONNECT_DELAY
        sdcp.RECONNECT_DELAY = 0.1
        self.server = FakePrinter()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        cfg = Config(printer_host="127.0.0.1", mainboard_id=BOARD, serial="0390000ELEGOO01", mqtt_host="x",
                     mqtt_port=1883, mqtt_user="bblp", mqtt_password="code", mqtt_tls=False)
        self.bridge = Bridge(cfg)
        self.bridge.printer.port = self.server.server_address[1]
        self.mqtt = self.bridge.mqtt = FakeMqtt()
        threading.Thread(target=self.bridge._worker, daemon=True).start()
        self.bridge.printer.start()
        self.wait(lambda: self.mqtt.reports())

    def tearDown(self):
        self.bridge.printer.close()
        self.server.shutdown()
        self.server.server_close()
        sdcp.RECONNECT_DELAY = self.old_delay

    def wait(self, condition, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if condition():
                return
            time.sleep(0.02)
        self.fail("timed out")

    def command(self, payload):
        self.bridge._on_mqtt_message(None, None, Message(payload))

    def test_publishes_status_on_the_report_topic(self):
        self.server.push(printing(13))
        self.wait(lambda: self.mqtt.reports()[-1]["gcode_state"] == "RUNNING")
        topic = self.mqtt.published[-1][0]
        self.assertEqual(topic, "device/0390000ELEGOO01/report")

    def test_pause_from_bambuddy_reaches_the_printer(self):
        self.command({"print": {"command": "pause", "sequence_id": "5"}})
        self.wait(lambda: (sdcp.PAUSE, {}) in self.server.received)

    def test_runout_pause_becomes_a_bambu_runout_error(self):
        self.server.push(printing(13))
        self.server.push(printing(5))
        self.wait(lambda: self.mqtt.reports()[-1]["print_error"] == 0x03008004)
        self.assertEqual(self.mqtt.reports()[-1]["stg_cur"], 6)
        self.assertIn((sdcp.HISTORY_DETAIL, {"Id": ["t1"]}), self.server.received)

    def test_user_pause_has_no_error(self):
        self.server.history = {"HistoryData": ["older"], "detail": []}
        self.server.push(printing(13))
        self.server.push(printing(6))
        self.wait(lambda: (sdcp.HISTORY, {}) in self.server.received)
        time.sleep(0.2)
        last = self.mqtt.reports()[-1]
        self.assertEqual((last["gcode_state"], last["print_error"], last["stg_cur"]), ("PAUSE", 0, 16))

    def test_light_is_only_sent_when_it_must_change(self):
        self.server.push(printing(13, light=0))
        self.wait(lambda: self.bridge.printer.status.get("LightStatus", {}).get("SecondLight") == 0)
        self.command({"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "off"}})
        self.command({"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "on"}})
        self.wait(lambda: (sdcp.SET_PARAMS, {"LightStatus": {"SecondLight": 0}}) in self.server.received)
        light_commands = [d for c, d in self.server.received if c == sdcp.SET_PARAMS]
        self.assertEqual(light_commands, [{"LightStatus": {"SecondLight": 0}}])

    def test_temperature_and_reply(self):
        self.command({"print": {"command": "gcode_line", "param": "M140 S60", "sequence_id": "9"}})
        self.wait(lambda: (sdcp.SET_PARAMS, {"TempTargetHotbed": 60}) in self.server.received)
        self.wait(lambda: any(b.get("print", {}).get("command") == "gcode_line" for _, b in self.mqtt.published))

    def test_jog_reaches_an_idle_printer(self):
        self.command({"print": {"command": "gcode_line", "param": "G91\nG1 X10.00 F6000\nG90"}})
        self.wait(lambda: (sdcp.MOVE_AXIS, {"Axis": "X", "Step": 10.0}) in self.server.received)

    def test_no_jog_while_busy(self):
        self.server.push(printing(13))
        self.wait(lambda: 1 in self.bridge.printer.status.get("CurrentStatus", []))
        self.command({"print": {"command": "gcode_line", "param": "G28"}})
        self.command({"print": {"command": "gcode_line", "param": "M140 S50"}})
        self.wait(lambda: (sdcp.SET_PARAMS, {"TempTargetHotbed": 50}) in self.server.received)
        self.assertNotIn(sdcp.HOME_AXES, [cmd for cmd, _ in self.server.received])

    def test_no_jog_while_homing(self):
        self.server.push({"CurrentStatus": [9], "PrintInfo": {"Status": 0}})
        self.wait(lambda: self.bridge.printer.status.get("CurrentStatus") == [9])
        self.command({"print": {"command": "gcode_line", "param": "G91\nG1 X10 F6000\nG90"}})
        self.command({"print": {"command": "gcode_line", "param": "M140 S50"}})
        self.wait(lambda: (sdcp.SET_PARAMS, {"TempTargetHotbed": 50}) in self.server.received)
        self.assertNotIn(sdcp.MOVE_AXIS, [cmd for cmd, _ in self.server.received])

    def test_version_reply(self):
        self.command({"info": {"command": "get_version", "sequence_id": "3"}})
        self.wait(lambda: any("info" in b for _, b in self.mqtt.published))


if __name__ == "__main__":
    unittest.main()
