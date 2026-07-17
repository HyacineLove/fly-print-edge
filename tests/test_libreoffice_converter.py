import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import libreoffice_converter
from libreoffice_converter import clean_external_dll_search_path, convert_document_to_pdf


class LibreOfficeConverterTests(unittest.TestCase):
    def test_frozen_windows_process_clears_and_restores_bundle_dll_directory(self):
        calls = []

        class FakeSetDllDirectory:
            argtypes = None
            restype = None

            def __call__(self, value):
                calls.append(value)
                return True

        fake_kernel32 = SimpleNamespace(SetDllDirectoryW=FakeSetDllDirectory())
        bundle_dir = r"C:\FlyPrint Edge\_internal"
        with patch.object(libreoffice_converter.sys, "platform", "win32"), \
             patch.object(libreoffice_converter.sys, "frozen", True, create=True), \
             patch.object(libreoffice_converter.sys, "_MEIPASS", bundle_dir, create=True), \
             patch.object(libreoffice_converter.ctypes, "WinDLL", return_value=fake_kernel32):
            with clean_external_dll_search_path():
                self.assertEqual([None], calls)

        self.assertEqual([None, bundle_dir], calls)

    def test_conversion_uses_one_configured_command_and_clean_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            soffice = os.path.join(temp_dir, "soffice.exe")
            source = os.path.join(temp_dir, "sample.docx")
            with open(soffice, "wb") as handle:
                handle.write(b"exe")
            with open(source, "wb") as handle:
                handle.write(b"docx")

            def run(command, **kwargs):
                output = os.path.join(temp_dir, "sample.pdf")
                with open(output, "wb") as handle:
                    handle.write(b"pdf")
                self.assertEqual(command[0], soffice)
                self.assertIn("--headless", command)
                self.assertIn("--norestore", command)
                self.assertIn("--nolockcheck", command)
                self.assertNotIn(temp_dir, kwargs["env"].get("PYTHONPATH", ""))
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("libreoffice_converter.subprocess.run", side_effect=run) as mocked_run:
                result, error = convert_document_to_pdf(soffice, source, temp_dir)

            self.assertEqual(result, os.path.join(temp_dir, "sample.pdf"))
            self.assertIsNone(error)
            mocked_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
