import tempfile
import unittest
import zipfile
from pathlib import Path

import importlib.util

from elegoobridge import jobs

# The stamp script is standalone (stamp/stamp_for_bambuddy.py), not part of the package.
_SCRIPT = Path(__file__).resolve().parent.parent / "stamp" / "stamp_for_bambuddy.py"
_spec = importlib.util.spec_from_file_location("stamp_for_bambuddy", _SCRIPT)
stamp_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp_script)
StampError, output_path, stamp = stamp_script.StampError, stamp_script.output_path, stamp_script.stamp
from tests.test_jobs import CENTAURI_GCODE, P1S_GCODE

SLICE_INFO = '<config><plate><metadata key="index" value="1"/><metadata key="printer_model_id" value="Elegoo-CC"/></plate></config>'
SETTINGS = '{\n    "printer_model": "Elegoo Centauri Carbon",\n    "printer_settings_id": "Elegoo Centauri Carbon 0.4 nozzle"\n}'


def sliced_3mf(path, gcode=CENTAURI_GCODE):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Metadata/slice_info.config", SLICE_INFO)
        z.writestr("Metadata/project_settings.config", SETTINGS)
        z.writestr("Metadata/plate_1.gcode", gcode)
        z.writestr("Metadata/plate_1.png", b"\x89PNG")
    return path


class StampTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_only_the_model_labels_change(self):
        source = sliced_3mf(self.root / "cube.gcode.3mf")
        target = stamp(source)
        self.assertEqual(target.name, "cube.bambuddy.gcode.3mf")
        with zipfile.ZipFile(source) as a, zipfile.ZipFile(target) as b:
            self.assertIsNone(b.testzip())
            changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
            self.assertEqual(changed, ["Metadata/slice_info.config", "Metadata/project_settings.config"])
            self.assertIn('printer_model_id" value="C12"', b.read("Metadata/slice_info.config").decode())
            settings = b.read("Metadata/project_settings.config").decode()
            self.assertIn('"printer_model": "Bambu Lab P1S"', settings)
            self.assertIn('"printer_settings_id": "Elegoo Centauri Carbon 0.4 nozzle"', settings)
        # The bridge still recognises the G-code as Centauri G-code.
        self.assertEqual(jobs.extract_gcode(target, "Metadata/plate_1.gcode"), CENTAURI_GCODE)

    def test_refuses_other_printers_and_unsliced_files(self):
        with self.assertRaisesRegex(StampError, "Bambu Lab P1S"):
            stamp(sliced_3mf(self.root / "p1s.gcode.3mf", P1S_GCODE))
        project = self.root / "project.3mf"
        with zipfile.ZipFile(project, "w") as z:
            z.writestr("3D/3dmodel.model", "<model/>")
        with self.assertRaisesRegex(StampError, "no sliced G-code"):
            stamp(project)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["p1s.gcode.3mf", "project.3mf"])

    def test_never_overwrites(self):
        source = sliced_3mf(self.root / "cube.3mf")
        stamp(source)
        with self.assertRaisesRegex(StampError, "already exists"):
            stamp(source)

    def test_already_stamped_files_are_skipped(self):
        stamped = stamp(sliced_3mf(self.root / "cube.gcode.3mf"))
        with self.assertRaisesRegex(StampError, "already stamped"):
            stamp(stamped)
        renamed = stamped.rename(self.root / "renamed.gcode.3mf")
        with self.assertRaisesRegex(StampError, "already stamped"):
            stamp(renamed)

    def test_folder_argument_and_messages(self):
        sliced_3mf(self.root / "a.gcode.3mf")
        sliced_3mf(self.root / "b.gcode.3mf", P1S_GCODE)
        self.assertEqual(stamp_script.main([str(self.root)]), 1)  # b is refused
        self.assertTrue((self.root / "a.bambuddy.gcode.3mf").exists())
        self.assertFalse((self.root / "b.bambuddy.gcode.3mf").exists())
        # Running again over the folder skips everything, changes nothing.
        before = sorted(p.name for p in self.root.iterdir())
        stamp_script.main([str(self.root)])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)
        self.assertEqual(stamp_script.main([]), 2)

    def test_paths_file_lists_the_stamped_files(self):
        sliced_3mf(self.root / "a.gcode.3mf")
        listing = self.root / "paths.txt"
        stamp_script.main(["--paths-file", str(listing), str(self.root / "a.gcode.3mf")])
        self.assertEqual(listing.read_text().splitlines(), [str((self.root / "a.bambuddy.gcode.3mf").resolve())])

    def test_output_names(self):
        self.assertEqual(output_path(Path("a/x.gcode.3mf")).name, "x.bambuddy.gcode.3mf")
        self.assertEqual(output_path(Path("x.3mf")).name, "x.bambuddy.gcode.3mf")


if __name__ == "__main__":
    unittest.main()
