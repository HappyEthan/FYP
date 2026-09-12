"""Fault-injection checks for the exported-wire connectivity checker."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).with_name("check_easyeda_schematic.py")
SPEC=importlib.util.spec_from_file_location("checker",SCRIPT)
CHECKER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
SOURCE=SCRIPT.parents[1]/"easyeda_std"


class ConnectivityCheckerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="easyeda-check-")
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.manifest=json.loads((SOURCE/"sheets_manifest.json").read_text())
        self.docs={s["name"]:json.loads((SOURCE/s["file"]).read_text()) for s in self.manifest["sheets"]}
        for name in ["design_netlist.json","sheets_manifest.json"]:
            (self.path/name).write_bytes((SOURCE/name).read_bytes())
        self.old=CHECKER.ROOT;CHECKER.ROOT=self.path
        self.addCleanup(setattr,CHECKER,"ROOT",self.old)

    def check(self):
        for sheet in self.manifest["sheets"]:
            (self.path/sheet["file"]).write_text(json.dumps(self.docs[sheet["name"]]))
        with contextlib.redirect_stdout(io.StringIO()):CHECKER.main()

    def test_baseline(self):self.check()

    def test_missing_sensor_wire_rejected(self):
        # U2 SCL wire starts at (1430,310); deleting it opens an actual pin.
        doc=self.docs["02_SENSORS"]
        doc["shape"]=[s for s in doc["shape"] if not s.startswith("W~1430 310 ")]
        with self.assertRaisesRegex(AssertionError,"unconnected without NC"):self.check()

    def test_rail_short_rejected(self):
        # C20 at (2630,2570) has 3V3 on its left and GND on its right.
        self.docs["05_RF_BATTERY_DEBUG"]["shape"].append("W~2590 2570 2670 2570~#008800~1~0~none~ggeFAULT~0")
        with self.assertRaisesRegex(AssertionError,"Conflicting labels"):self.check()

    def test_swapped_mcu_usb_labels_rejected(self):
        doc=self.docs["01_MCU"]
        doc["shape"]=[s.replace("~USB_DM_SOC~","~USB_DP_SOC~") if s.startswith("N~285~1030~") else s for s in doc["shape"]]
        with self.assertRaises(AssertionError):self.check()


if __name__=="__main__":unittest.main()
