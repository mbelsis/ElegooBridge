import tempfile
import unittest
import zipfile
from pathlib import Path

from elegoobridge import jobs

CENTAURI_GCODE = (
    b"; HEADER_BLOCK_START\n; total layer number: 128\n; HEADER_BLOCK_END\nG28\nG1 X10\n"
    b"; CONFIG_BLOCK_START\n; printer_model = Elegoo Centauri Carbon\n"
    b"; printer_settings_id = Elegoo Centauri Carbon 0.4 nozzle\n; CONFIG_BLOCK_END\n"
)
P1S_GCODE = b"G28\n; CONFIG_BLOCK_START\n; printer_model = Bambu Lab P1S\n; CONFIG_BLOCK_END\n"


def make_3mf(path, plates):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", "<model/>")
        for name, data in plates.items():
            z.writestr(name, data)
    return path


class JobTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_print_files_only(self):
        for name in ("cube.gcode.3mf", "cube.3mf", "Cube.GCODE"):
            self.assertTrue(jobs.is_print_file(name), name)
        for name in ("P1S_01.08.00.00.bin", "firmware.zip", "update.img", "x.gcode.bin", ""):
            self.assertFalse(jobs.is_print_file(name), name)

    def test_file_names_from_bambuddy_urls(self):
        for url in ("ftp://cube.gcode.3mf", "file:///sdcard/cube.gcode.3mf", "/cache/cube.gcode.3mf", "cube.gcode.3mf"):
            self.assertEqual(jobs.file_name(url), "cube.gcode.3mf", url)
        self.assertEqual(jobs.file_name("ftp://../../etc/passwd"), "passwd")
        with self.assertRaises(jobs.JobError):
            jobs.file_name("ftp://")

    def test_find_upload_in_root_or_cache(self):
        (self.root / "cache").mkdir()
        (self.root / "cache" / "b.3mf").write_bytes(b"x")
        (self.root / "a.3mf").write_bytes(b"x")
        self.assertEqual(jobs.find_upload(self.root, "ftp://a.3mf"), self.root / "a.3mf")
        self.assertEqual(jobs.find_upload(self.root, "ftp://b.3mf"), self.root / "cache" / "b.3mf")
        with self.assertRaises(jobs.JobError):
            jobs.find_upload(self.root, "ftp://missing.3mf")

    def test_find_upload_uses_the_requested_folder(self):
        (self.root / "cache").mkdir()
        (self.root / "cube.gcode").write_text("old root copy")
        (self.root / "cache" / "cube.gcode").write_text("new cache copy")
        self.assertEqual(jobs.find_upload(self.root, "ftp:///cache/cube.gcode"), self.root / "cache" / "cube.gcode")
        self.assertEqual(jobs.find_upload(self.root, "file:///sdcard/cache/cube.gcode"),
                         self.root / "cache" / "cube.gcode")
        self.assertEqual(jobs.find_upload(self.root, "ftp://cube.gcode"), self.root / "cube.gcode")
        # A path outside the upload folder is never used, only the name.
        self.assertEqual(jobs.find_upload(self.root, "ftp://../cache/cube.gcode"), self.root / "cube.gcode")

    def test_extracts_the_requested_plate(self):
        path = make_3mf(self.root / "cube.gcode.3mf", {
            "Metadata/plate_1.gcode": CENTAURI_GCODE + b";1", "Metadata/plate_2.gcode": CENTAURI_GCODE + b";2"})
        self.assertTrue(jobs.extract_gcode(path, "Metadata/plate_2.gcode").endswith(b";2"))
        self.assertTrue(jobs.extract_gcode(path, "").endswith(b";1"))
        with self.assertRaises(jobs.JobError):
            jobs.extract_gcode(path, "Metadata/plate_3.gcode")

    def test_refuses_gcode_for_another_printer(self):
        path = make_3mf(self.root / "p1s.gcode.3mf", {"Metadata/plate_1.gcode": P1S_GCODE})
        with self.assertRaisesRegex(jobs.JobError, "Bambu Lab P1S"):
            jobs.extract_gcode(path, "Metadata/plate_1.gcode")
        plain = self.root / "unknown.gcode"
        plain.write_bytes(b"G28\nG1 X10\n")
        with self.assertRaisesRegex(jobs.JobError, "unknown printer"):
            jobs.extract_gcode(plain)

    def test_plain_gcode_and_unsliced_projects(self):
        plain = self.root / "cube.gcode"
        plain.write_bytes(CENTAURI_GCODE)
        self.assertEqual(jobs.extract_gcode(plain), CENTAURI_GCODE)
        project = make_3mf(self.root / "project.3mf", {})
        with self.assertRaisesRegex(jobs.JobError, "no sliced G-code"):
            jobs.extract_gcode(project)
        broken = self.root / "broken.3mf"
        broken.write_bytes(b"not a zip")
        with self.assertRaises(jobs.JobError):
            jobs.extract_gcode(broken)

    def test_printer_file_names(self):
        self.assertEqual(jobs.printer_file_name("ftp://Cube v2.gcode.3mf"), "Cube v2.gcode")
        self.assertEqual(jobs.printer_file_name("ftp://x.3mf", "My cube"), "My cube.gcode")
        self.assertEqual(jobs.printer_file_name("ftp://a/b:c?.3mf"), "b_c_.gcode")


if __name__ == "__main__":
    unittest.main()
