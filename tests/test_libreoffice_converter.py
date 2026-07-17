import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
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
            profile = os.path.join(temp_dir, "profile")
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
                self.assertIn(f"-env:UserInstallation={Path(profile).as_uri()}", command)
                self.assertNotIn(temp_dir, kwargs["env"].get("PYTHONPATH", ""))
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("libreoffice_converter.subprocess.run", side_effect=run) as mocked_run:
                result, error = convert_document_to_pdf(soffice, source, temp_dir, profile)

            self.assertEqual(result, os.path.join(temp_dir, "sample.pdf"))
            self.assertIsNone(error)
            self.assertTrue(os.path.isdir(profile))
            mocked_run.assert_called_once()

    def test_conversions_are_serialized_through_one_libreoffice_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            soffice = os.path.join(temp_dir, "soffice.exe")
            source = os.path.join(temp_dir, "sample.docx")
            profile = os.path.join(temp_dir, "profile")
            with open(soffice, "wb") as handle:
                handle.write(b"exe")
            with open(source, "wb") as handle:
                handle.write(b"docx")

            state_lock = threading.Lock()
            active = 0
            maximum_active = 0

            def run(command, **kwargs):
                nonlocal active, maximum_active
                with state_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.05)
                    output_dir = command[command.index("--outdir") + 1]
                    with open(os.path.join(output_dir, "sample.pdf"), "wb") as handle:
                        handle.write(b"pdf")
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                finally:
                    with state_lock:
                        active -= 1

            results = []

            def convert(index):
                output_dir = os.path.join(temp_dir, f"output-{index}")
                results.append(convert_document_to_pdf(soffice, source, output_dir, profile))

            with patch("libreoffice_converter.subprocess.run", side_effect=run):
                threads = [threading.Thread(target=convert, args=(index,)) for index in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertEqual(1, maximum_active)
            self.assertEqual(2, len(results))
            self.assertTrue(all(error is None for _, error in results))


if __name__ == "__main__":
    unittest.main()
