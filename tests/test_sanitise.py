"""File publication and encoding regressions for the OpenAPI sanitiser."""

import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "openapi" / "sanitise.py"


class SanitiseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "input.json"
        self.output = self.root / "snapshot.json"
        self.spec = {
            "openapi": "3.1.0",
            "info": {"title": "Fabricated", "version": "1"},
            "paths": {},
            "x-fixture": "日本語",
        }
        module_spec = importlib.util.spec_from_file_location("sanitise_under_test", SCRIPT)
        self.module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(self.module)

    def run_sanitiser(self, *, utf8="0", ascii_json=False):
        self.source.write_text(
            json.dumps(self.spec, ensure_ascii=ascii_json), encoding="utf-8"
        )
        env = {
            name: os.environ[name]
            for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR")
            if name in os.environ
        }
        env.update(PYTHONUTF8=utf8, PYTHONIOENCODING="ascii")
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(self.source),
             "--output", str(self.output)],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=10,
        )

    def test_unicode_and_byte_count_with_ascii_console(self):
        self.output = self.root / "日本語.json"
        for utf8, ascii_json in (("0", False), ("0", True), ("1", False)):
            with self.subTest(utf8=utf8, ascii_json=ascii_json):
                result = self.run_sanitiser(utf8=utf8, ascii_json=ascii_json)
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = self.output.read_bytes()
                output = json.loads(raw.decode("utf-8"))
                self.assertEqual(output["x-fixture"], "日本語")
                self.assertNotIn("20 ", output["info"]["summary"])
                self.assertEqual(int(re.search(r"Size: (\d+) bytes", result.stdout)[1]), len(raw))
                self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                                 ["input.json", "日本語.json"])

    def test_residual_marker_preserves_existing_output(self):
        self.spec["x-fixture"] = "OT #17"
        self.output.write_bytes(b"previous snapshot\n")
        result = self.run_sanitiser()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Residual leaks found", result.stdout)
        self.assertEqual(self.output.read_bytes(), b"previous snapshot\n")

    def test_residual_marker_does_not_create_output(self):
        self.spec["x-fixture"] = "OT #17"
        result = self.run_sanitiser()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())

    def test_replace_failure_preserves_output_and_removes_temporary_file(self):
        self.source.write_text(json.dumps(self.spec), encoding="utf-8")
        self.output.write_bytes(b"previous snapshot\n")
        with patch.object(sys, "argv", [str(SCRIPT), "--input", str(self.source),
                                       "--output", str(self.output)]), \
                patch.object(self.module.os, "replace", side_effect=OSError("fabricated failure")):
            with self.assertRaisesRegex(OSError, "fabricated failure"):
                self.module.main()
        self.assertEqual(self.output.read_bytes(), b"previous snapshot\n")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ["input.json", "snapshot.json"])

    def test_partial_write_failure_preserves_output(self):
        self.source.write_text(json.dumps(self.spec), encoding="utf-8")
        self.output.write_bytes(b"previous snapshot\n")
        create_temporary = self.module.tempfile.NamedTemporaryFile

        @contextmanager
        def interrupted_write(*args, **kwargs):
            with create_temporary(*args, **kwargs) as output:
                def write(data):
                    output.write(data[:3])
                    raise OSError("fabricated partial write")
                yield SimpleNamespace(name=output.name, write=write)

        with patch.object(sys, "argv", [str(SCRIPT), "--input", str(self.source),
                                       "--output", str(self.output)]), \
                patch.object(self.module.tempfile, "NamedTemporaryFile", interrupted_write):
            with self.assertRaisesRegex(OSError, "fabricated partial write"):
                self.module.main()
        self.assertEqual(self.output.read_bytes(), b"previous snapshot\n")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ["input.json", "snapshot.json"])

    def test_invalid_input_preserves_output(self):
        self.source.write_bytes(b"{")
        self.output.write_bytes(b"previous snapshot\n")
        with patch.object(sys, "argv", [str(SCRIPT), "--input", str(self.source),
                                       "--output", str(self.output)]):
            with self.assertRaises(json.JSONDecodeError):
                self.module.main()
        self.assertEqual(self.output.read_bytes(), b"previous snapshot\n")

    def test_same_input_and_output_path(self):
        self.output = self.source
        result = self.run_sanitiser()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8"))["x-fixture"], "日本語")


if __name__ == "__main__":
    unittest.main()
