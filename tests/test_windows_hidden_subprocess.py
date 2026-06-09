import os
import sys
import subprocess
import unittest
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_node_info
import printer_windows


class WindowsHiddenSubprocessTests(unittest.TestCase):
    def test_windows_mac_lookup_hides_console_window(self):
        completed = MagicMock(returncode=0, stdout='"AA-BB-CC-DD-EE-FF","Ethernet"\n', stderr="")

        with patch("subprocess.run", return_value=completed) as mock_run:
            mac = edge_node_info.EdgeNodeInfo()._get_windows_mac()

        self.assertEqual(mac, "aa:bb:cc:dd:ee:ff")
        kwargs = mock_run.call_args.kwargs
        self.assertIn("startupinfo", kwargs)
        self.assertIsNotNone(kwargs["startupinfo"])
        self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(kwargs.get("creationflags"), getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_windows_cpu_lookup_hides_console_window(self):
        completed = MagicMock(returncode=0, stdout="Name=Intel(R) Test CPU\n", stderr="")

        with patch("subprocess.run", return_value=completed) as mock_run:
            cpu_info = edge_node_info.EdgeNodeInfo().get_cpu_info()

        self.assertEqual(cpu_info, "Intel(R) Test CPU")
        kwargs = mock_run.call_args.kwargs
        self.assertIn("startupinfo", kwargs)
        self.assertIsNotNone(kwargs["startupinfo"])
        self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(kwargs.get("creationflags"), getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_printer_wmi_batch_query_hides_console_window(self):
        completed = MagicMock(returncode=0, stdout="[]", stderr="")

        with patch("subprocess.run", return_value=completed) as mock_run:
            result = printer_windows.WindowsEnterprisePrinter()._query_all_printers_wmi_batch()

        self.assertEqual(result, {})
        kwargs = mock_run.call_args.kwargs
        self.assertIn("startupinfo", kwargs)
        self.assertIsNotNone(kwargs["startupinfo"])
        self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(kwargs.get("creationflags"), getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    unittest.main()
