import unittest

from elegoobridge.mapper import Mapper, fan_level, job_number, speed_level, version_report


def status(code, layer=0, total=128, progress=0, ticks=0.0, total_ticks=805, filename="cube.gcode",
           task="task-1", fans=None, light=0, speed=100, current=None):
    loaded = code not in (0, 16, 20, 1, 21) or total_ticks == 0
    return {
        "CurrentStatus": [current if current is not None else (0 if code in (0, 8, 9) else 1)],
        "TempOfNozzle": 209.6, "TempTargetNozzle": 210, "TempOfHotbed": 60.04, "TempTargetHotbed": 60,
        "TempOfBox": 28.9,
        "CurrentFanSpeed": fans or {"ModelFan": 98, "AuxiliaryFan": 0, "BoxFan": 68},
        "LightStatus": {"SecondLight": light, "RgbLight": [0, 0, 0]},
        "PrintInfo": {
            "Status": code, "CurrentLayer": layer, "TotalLayer": total, "CurrentTicks": ticks,
            "TotalTicks": total_ticks, "Filename": filename if loaded else "", "TaskId": task if loaded else "",
            "PrintSpeedPct": speed, "Progress": progress,
        },
    }


def report(mapper, *args, **kwargs):
    return mapper.update(status(*args, **kwargs))["print"]


class StateTests(unittest.TestCase):
    def test_full_print_from_the_recordings(self):
        m = Mapper()
        sequence = [
            (0, "IDLE"), (16, "PREPARE"), (20, "PREPARE"), (18, "PREPARE"), (1, "PREPARE"), (21, "PREPARE"),
            (13, "RUNNING"), (9, "FINISH"), (0, "FINISH"),
        ]
        for code, expected in sequence:
            with self.subTest(code=code):
                self.assertEqual(report(m, code)["gcode_state"], expected)

    def test_finish_reports_100_percent_and_keeps_the_file(self):
        m = Mapper()
        report(m, 13, layer=128, progress=88, ticks=700, filename="cube.gcode")
        done = report(m, 9, layer=128, progress=0, ticks=725, filename="")
        self.assertEqual((done["mc_percent"], done["mc_remaining_time"]), (100, 0))
        self.assertEqual(done["gcode_file"], "cube.gcode")
        idle = report(m, 0, filename="")
        self.assertEqual((idle["gcode_state"], idle["gcode_file"]), ("FINISH", "cube.gcode"))

    def test_stop_is_failed_and_sticky(self):
        m = Mapper()
        report(m, 13)
        self.assertEqual(report(m, 7)["gcode_state"], "FAILED")
        self.assertEqual(report(m, 8, filename="")["gcode_state"], "FAILED")
        self.assertEqual(report(m, 0, filename="")["gcode_state"], "FAILED")
        self.assertEqual(report(m, 16)["gcode_state"], "PREPARE")

    def test_power_loss_mid_print_is_failed(self):
        m = Mapper()
        report(m, 13, layer=18)
        # The printer came back after a power cut and reports idle.
        self.assertEqual(report(m, 0, filename="", total_ticks=0)["gcode_state"], "FAILED")

    def test_idle_after_start_up_is_idle(self):
        self.assertEqual(report(Mapper(), 0, filename="")["gcode_state"], "IDLE")

    def test_progress_and_remaining_time(self):
        r = report(Mapper(), 13, layer=74, progress=49, ticks=399.2, total_ticks=805)
        self.assertEqual((r["mc_percent"], r["layer_num"], r["total_layer_num"]), (49, 74, 128))
        self.assertEqual(r["mc_remaining_time"], 7)  # 405.8 s, rounded up


class PauseTests(unittest.TestCase):
    def test_user_pause(self):
        m = Mapper()
        report(m, 13)
        r = report(m, 6)
        self.assertEqual((r["gcode_state"], r["stg_cur"], r["print_error"]), ("PAUSE", 16, 0))

    def test_runout_pause_reports_bambu_runout_error(self):
        m = Mapper()
        report(m, 13)
        report(m, 5)
        m.pause_reason = 45
        r = report(m, 6)
        self.assertEqual((r["gcode_state"], r["stg_cur"]), ("PAUSE", 6))
        self.assertEqual(f"{r['print_error']:08X}", "03008004")

    def test_reason_clears_on_resume(self):
        m = Mapper()
        report(m, 6)
        m.pause_reason = 45
        self.assertEqual(report(m, 20)["print_error"], 0)
        self.assertEqual(m.pause_reason, 0)

    def test_unknown_reason_is_a_plain_pause(self):
        m = Mapper()
        report(m, 6)
        m.pause_reason = 99
        r = report(m, 6)
        self.assertEqual((r["stg_cur"], r["print_error"]), (16, 0))


class FieldTests(unittest.TestCase):
    def test_temperatures_fans_and_light(self):
        r = report(Mapper(), 13, light=1)
        self.assertEqual((r["nozzle_temper"], r["nozzle_target_temper"]), (209.6, 210))
        self.assertEqual((r["bed_temper"], r["chamber_temper"]), (60.0, 28.9))
        self.assertEqual((r["cooling_fan_speed"], r["big_fan1_speed"], r["big_fan2_speed"]), ("15", "0", "10"))
        self.assertEqual(r["lights_report"], [{"node": "chamber_light", "mode": "on"}])

    def test_names_and_job_ids(self):
        r = report(Mapper(), 13, filename="PlateBridge-test-cube.gcode", task="3553fdae-1b4e")
        self.assertEqual((r["gcode_file"], r["subtask_name"]), ("PlateBridge-test-cube.gcode", "PlateBridge-test-cube"))
        self.assertTrue(r["subtask_id"].isdigit())
        self.assertEqual(r["subtask_id"], job_number("3553fdae-1b4e"))

    def test_refused_job_shows_failed_with_error_until_next_job(self):
        m = Mapper()
        report(m, 0, filename="")
        m.refuse_job(0x05004037)
        r = report(m, 0, filename="")
        self.assertEqual((r["gcode_state"], f"{r['print_error']:08X}"), ("FAILED", "05004037"))
        # The next job clears it.
        self.assertEqual(report(m, 16)["print_error"], 0)
        self.assertEqual(report(m, 9)["print_error"], 0)

    def test_refused_job_after_a_completed_job_stays_failed(self):
        # The printer keeps reporting status 9 (completed) until its next job.
        m = Mapper()
        self.assertEqual(report(m, 9)["gcode_state"], "FINISH")
        m.refuse_job(0x05004037)
        for _ in range(3):
            r = report(m, 9)
            self.assertEqual((r["gcode_state"], r["print_error"]), ("FAILED", 0x05004037))
        m.job_error = 0  # cleared from Bambuddy
        self.assertEqual(report(m, 9)["gcode_state"], "FINISH")

    def test_homing_from_the_control_panel(self):
        r = report(Mapper(), 0, filename="", current=9)
        self.assertEqual((r["gcode_state"], r["stg_cur"]), ("IDLE", 13))
        self.assertEqual(report(Mapper(), 0, filename="", current=0)["stg_cur"], 255)

    def test_version_never_looks_outdated(self):
        version = version_report("SERIAL", "1")["info"]["module"][0]["sw_ver"]
        self.assertTrue(version.startswith("99."))

    def test_reports_developer_mode(self):
        self.assertEqual(Mapper().update(status(0))["fun"], "0")

    def test_scales(self):
        self.assertEqual([fan_level(p) for p in (0, 50, 68, 100, 140)], ["0", "8", "10", "15", "15"])
        self.assertEqual([speed_level(p) for p in (50, 100, 130, 160)], [1, 2, 3, 4])
        self.assertEqual(job_number(""), "0")


if __name__ == "__main__":
    unittest.main()
