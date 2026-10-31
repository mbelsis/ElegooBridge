import unittest

from elegoobridge import sdcp
from elegoobridge.commands import translate, translate_gcode


def gcode(text):
    return translate({"print": {"command": "gcode_line", "param": text, "sequence_id": "7"}})


class CommandTests(unittest.TestCase):
    def test_pause_resume_stop(self):
        for name, cmd in (("pause", sdcp.PAUSE), ("resume", sdcp.RESUME), ("stop", sdcp.STOP)):
            with self.subTest(name=name):
                action = translate({"print": {"command": name, "sequence_id": "1"}})
                self.assertEqual(action.sdcp, [(cmd, {})])
                self.assertTrue(action.push_status)

    def test_temperatures_as_bambuddy_sends_them(self):
        self.assertEqual(gcode("M104 T0 S210").sdcp, [(sdcp.SET_PARAMS, {"TempTargetNozzle": 210})])
        self.assertEqual(gcode("M140 S60").sdcp, [(sdcp.SET_PARAMS, {"TempTargetHotbed": 60})])
        self.assertEqual(gcode("M140 S0").sdcp, [(sdcp.SET_PARAMS, {"TempTargetHotbed": 0})])

    def test_unsafe_temperatures_are_refused(self):
        action = gcode("M104 S400\nM140 S150")
        self.assertEqual(action.sdcp, [])
        self.assertEqual(len(action.unsupported), 2)
        self.assertEqual(action.reply["print"]["result"], "failed")

    def test_fans_use_bambu_indexes_and_0_255(self):
        self.assertEqual(gcode("M106 P1 S255").sdcp, [(sdcp.SET_PARAMS, {"TargetFanSpeed": {"ModelFan": 100}})])
        self.assertEqual(gcode("M106 P2 S128").sdcp, [(sdcp.SET_PARAMS, {"TargetFanSpeed": {"AuxiliaryFan": 50}})])
        self.assertEqual(gcode("M106 P3 S0").sdcp, [(sdcp.SET_PARAMS, {"TargetFanSpeed": {"BoxFan": 0}})])
        self.assertEqual(gcode("M107").sdcp, [(sdcp.SET_PARAMS, {"TargetFanSpeed": {"ModelFan": 0}})])
        self.assertEqual(gcode("M106 P10 S255").sdcp, [])

    def test_other_gcode_is_not_sent(self):
        commands, unsupported = translate_gcode("M104 S200 ; heat\nG1 X10\nM83\nG29")
        self.assertEqual(commands, [(sdcp.SET_PARAMS, {"TempTargetNozzle": 200})])
        self.assertEqual(unsupported, ["G1 X10", "M83", "G29"])
        self.assertEqual(gcode("G29\nM104 S200").reply["print"]["result"], "success")

    def test_jogs_as_bambuddy_sends_them(self):
        self.assertEqual(gcode("G91\nG1 X10.00 Y-1.00 F6000\nG90").sdcp, [
            (sdcp.MOVE_AXIS, {"Axis": "X", "Step": 10.0}), (sdcp.MOVE_AXIS, {"Axis": "Y", "Step": -1.0})])
        self.assertEqual(gcode("G91\nG1 Z-1.00 F600\nG90").sdcp, [(sdcp.MOVE_AXIS, {"Axis": "Z", "Step": -1.0})])
        self.assertEqual(gcode("G28").sdcp, [(sdcp.HOME_AXES, {"Axis": "XYZ"})])

    def test_unsafe_moves_are_not_sent(self):
        for text in ("G1 X10", "G90\nG1 X10", "G91\nG1 X150", "M83\nG91\nG1 E5 F300\nM82", "G91\nG1 F600"):
            with self.subTest(text=text):
                action = gcode(text)
                self.assertEqual(action.sdcp, [])
                self.assertEqual(action.reply["print"]["result"], "failed")

    def test_light(self):
        on = translate({"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "on"}})
        off = translate({"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "off"}})
        second = translate({"system": {"command": "ledctrl", "led_node": "chamber_light2", "led_mode": "on"}})
        self.assertEqual((on.light, off.light, second.light), (True, False, None))

    def test_speed_levels(self):
        for level, pct in (("1", 50), ("2", 100), ("3", 130), ("4", 160)):
            action = translate({"print": {"command": "print_speed", "param": level}})
            self.assertEqual(action.sdcp, [(sdcp.SET_PARAMS, {"PrintSpeedPct": pct})])
        self.assertEqual(translate({"print": {"command": "print_speed", "param": "9"}}).sdcp, [])

    def test_info_and_errors(self):
        self.assertTrue(translate({"pushing": {"command": "pushall"}}).push_status)
        self.assertTrue(translate({"info": {"command": "get_version"}}).version)
        self.assertTrue(translate({"print": {"command": "clean_print_error"}}).clear_error)

    def test_unknown_commands_send_nothing(self):
        for payload in ({"print": {"command": "ams_control"}}, {"upgrade": {"command": "start"}},
                        {"camera": {"command": "ipcam_record_set"}}, {}):
            with self.subTest(payload=payload):
                action = translate(payload)
                self.assertEqual(action.sdcp, [])
        self.assertEqual(translate({"print": {"command": "ams_control"}}).reply["print"]["result"], "failed")

    def test_project_file_starts_a_job(self):
        block = {"command": "project_file", "url": "ftp://cube.gcode.3mf", "param": "Metadata/plate_1.gcode"}
        action = translate({"print": block})
        self.assertEqual((action.start, action.sdcp, action.reply), (block, [], None))

    def test_every_translated_command_passes_the_allow_list(self):
        texts = ["M104 S210", "M140 S60", "M106 P1 S255\nM106 P2 S10\nM106 P3 S20", "M107",
                 "G91\nG1 X0.1 Y100 Z-10\nG90", "G28"]
        for text in texts:
            for cmd, data in gcode(text).sdcp:
                sdcp.check_command(cmd, data)


class AllowListTests(unittest.TestCase):
    def test_refuses_unknown_commands(self):
        for cmd, data in ((2, {}), (259, {}), (403, {}), (403, {"ZOffset": 1}), (386, {"Enable": 1}),
                          (401, {"Axis": "E", "Step": 1}), (401, {"Axis": "X", "Step": 101}),
                          (401, {"Axis": "X", "Step": 0}), (401, {"Axis": "X", "Step": "1"}),
                          (402, {"Axis": "XY"}), (402, {})):
            with self.subTest(cmd=cmd, data=data):
                with self.assertRaises(sdcp.SdcpError):
                    sdcp.check_command(cmd, data)


if __name__ == "__main__":
    unittest.main()
