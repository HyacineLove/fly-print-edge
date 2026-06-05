import os
import sys
import unittest
from types import SimpleNamespace


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printer_fault_state import PrinterFaultStateStore, map_ipp_fault_reasons


class PrinterFaultStateTests(unittest.TestCase):
    def test_maps_media_empty_reasons_to_user_message(self):
        fault = map_ipp_fault_reasons(["media-empty-error", "media-needed-error"])

        self.assertEqual("printer_fault", fault["error_code"])
        self.assertEqual("缺纸", fault["reason_label"])
        self.assertEqual("打印机缺纸，请联系管理员补纸", fault["message"])
        self.assertEqual(["media-empty-error", "media-needed-error"], fault["raw_reasons"])

    def test_maps_unknown_reason_to_generic_fault_while_preserving_raw_reason(self):
        fault = map_ipp_fault_reasons(["vendor-specific-error"])

        self.assertEqual("打印机故障，请联系管理员处理", fault["message"])
        self.assertEqual("未知故障", fault["reason_label"])
        self.assertEqual(["vendor-specific-error"], fault["raw_reasons"])

    def test_store_sets_and_clears_fault_from_probe_results(self):
        store = PrinterFaultStateStore()

        fault = store.update_from_probe(
            printer_id="printer-1",
            printer_name="HP",
            result=SimpleNamespace(
                available=True,
                faulted=True,
                fault_reasons=["door-open-error"],
                printer_state=5,
                printer_state_name="stopped",
            ),
        )

        self.assertTrue(fault["faulted"])
        self.assertEqual("机盖未关闭", fault["reason_label"])

        restored = store.update_from_probe(
            printer_id="printer-1",
            printer_name="HP",
            result=SimpleNamespace(
                available=True,
                faulted=False,
                fault_reasons=[],
                printer_state=3,
                printer_state_name="idle",
            ),
        )

        self.assertFalse(restored["faulted"])
        self.assertEqual("ready", restored["reason_code"])
        self.assertEqual([], restored["raw_reasons"])


if __name__ == "__main__":
    unittest.main()
