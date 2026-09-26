"""Exercise the shipped commands against a local, fabricated HTTP service."""

from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import socket
import time
import sys
from threading import Thread
import unittest

ROOT = Path(__file__).resolve().parents[1]
CALCULATOR = "urn:sbrm:calculator:fbt:car-operating-cost"
PERIOD = "urn:sbrm:period:fbt:fy2026"
DEFAULT = object()
DISCONNECT = object()
DELAY = object()
SUCCESS = {"taxable_value": "123.45", "advisory": {"disclaimer": "Fabricated advisory"}}
LISTING = {"calc_uri": CALCULATOR, "label": "Fabricated example", "method": "car-operating-cost",
           "supported_periods": [PERIOD], "input_schema_ref": "#/components/schemas/FBTCarOperatingCostInput",
           "jurisdiction": "AU", "selection": {"kind": "election"}}


@contextmanager
def service(discovery, status, response, *, modules=DEFAULT, filtered=DEFAULT, sequence=None,
            get_sequence=None):
    requests = []
    gets = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, value):
            if value is DISCONNECT:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if value is DELAY:
                time.sleep(1.3)
                value = SUCCESS
            body = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            gets.append(self.path)
            if self.path == "/v1/modules":
                value = [{"module_uri": "urn:sbrm:module:fbt", "label": "FBT",
                          "jurisdiction": "AU", "calculators": [CALCULATOR]}] if modules is DEFAULT else modules
                self.reply(200, value)
            elif self.path == "/v1/calculators?module=urn:sbrm:module:fbt":
                self.reply(200, discovery if filtered is DEFAULT else filtered)
            elif self.path == "/v1/calculators":
                count = gets.count(self.path)
                code, value = get_sequence[min(count - 1, len(get_sequence) - 1)] if get_sequence else (200, discovery)
                self.reply(code, value)
            else:
                self.reply(404, {"detail": "Unknown fabricated route"})

        def do_POST(self):
            if self.headers.get("Transfer-Encoding") == "chunked":
                body = bytearray()
                while True:
                    size = int(self.rfile.readline().split(b";")[0], 16)
                    if not size:
                        while self.rfile.readline().strip():
                            pass
                        break
                    body.extend(self.rfile.read(size))
                    self.rfile.read(2)
            else:
                body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append({"path": self.path, "body": json.loads(body)})
            code, value = sequence[min(len(requests) - 1, len(sequence) - 1)] if sequence else (status, response)
            self.reply(code, value)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, gets
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ExampleTests(unittest.TestCase):
    def commands(self):
        executable = shutil.which("dotnet")
        assembly = ROOT / "examples/dotnet/bin/Debug/net8.0/ClawDogCalcKit.Quickstart.dll"
        self.assertIsNotNone(executable, "Install the documented .NET SDK before running the suite")
        self.assertTrue(assembly.is_file(), "Run dotnet build in examples/dotnet before the suite")
        return {"python": [sys.executable, "-X", "utf8", str(ROOT / "examples/python/quickstart.py")],
                "dotnet": [executable, str(assembly)]}

    def run_example(self, command, *, discovery=DEFAULT, status=200, response=DEFAULT, retries="0", timeout="5", expected_get_attempts=None, **server_options):
        if discovery is DEFAULT:
            discovery = [LISTING]
        if response is DEFAULT:
            response = SUCCESS
        with service(discovery, status, response, **server_options) as (url, requests, gets):
            environment = {"CLAWDOG_CALC_API_URL": url, "CLAWDOG_CALC_TIMEOUT": timeout,
                           "CLAWDOG_CALC_RETRIES": retries, "PYTHONIOENCODING": "utf-8"}
            if os.name == "nt":
                environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
            result = subprocess.run(command, env=environment, capture_output=True, text=True,
                                    encoding="utf-8", timeout=20, check=False)
        if result.returncode == 0:
            self.assertEqual(gets[0], "/v1/calculators")
            if command[0] == self.commands()["dotnet"][0]:
                self.assertEqual(gets[-2:], ["/v1/modules", "/v1/calculators?module=urn:sbrm:module:fbt"])
        if expected_get_attempts is not None:
            self.assertEqual(gets.count("/v1/calculators"), expected_get_attempts)
        return result, requests

    def test_successful_calculation_uses_the_actual_fbt_year_length(self):
        expected_days = (date(2026, 4, 1) - date(2025, 4, 1)).days
        for language, command in self.commands().items():
            with self.subTest(language=language):
                result, requests = self.run_example(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["path"], f"/v1/calculators/{CALCULATOR}/{PERIOD}")
                self.assertEqual(requests[0]["body"]["daysHeldInFBTYear"], expected_days)
                self.assertNotIn("openingDepreciatedValue", requests[0]["body"])
                self.assertIn("Fabricated advisory", result.stdout)
                self.assertIn("=== Done ===", result.stdout)
                self.assertIn("123.45", result.stdout)

    def test_failed_calculation_never_reports_success(self):
        for language, command in self.commands().items():
            for status in (422, 503):
                with self.subTest(language=language, status=status):
                    result, requests = self.run_example(command, status=status, response={"detail": "Fabricated failure"})
                    self.assertEqual(len(requests), 1)
                    self.assertIn(str(status), result.stderr)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("=== Done ===", result.stdout)

    def test_success_status_without_a_usable_calculation_is_a_failure(self):
        for language, command in self.commands().items():
            for response in ({}, [], None, b'{broken',
                             b'{"taxable_value":"1.00","taxable_value":"2.00","advisory":{"disclaimer":"test"}}',
                             b'{"taxable_value":"1.00","extra":NaN,"advisory":{"disclaimer":"test"}}', {"result": SUCCESS}, {**SUCCESS, "error": "failed"},
                             *({**SUCCESS, "taxable_value": value} for value in
                               (None, True, 123.45, "NaN", "Infinity", "1e2", "12.345", "12.34\n")),
                             *({**SUCCESS, "advisory": value} for value in
                               (None, [], {}, {"disclaimer": " "}, {"disclaimer": True}))):
                with self.subTest(language=language, response=response):
                    result, requests = self.run_example(command, response=response)
                    self.assertEqual(len(requests), 1)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("=== Done ===", result.stdout)

    def test_missing_calculator_or_period_prevents_invocation(self):
        for language, command in self.commands().items():
            for discovery in (None, {}, [None], [], [{**LISTING, "calc_uri": "urn:sbrm:calculator:other"}],
                              [{**LISTING, "supported_periods": []}], [{**LISTING, "supported_periods": PERIOD}]):
                with self.subTest(language=language, discovery=discovery):
                    result, requests = self.run_example(command, discovery=discovery)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(requests, [])

    def test_additional_calculators_are_compatible(self):
        for language, command in self.commands().items():
            with self.subTest(language=language):
                result, requests = self.run_example(command, discovery=[{**LISTING, "calc_uri": f"urn:sbrm:calculator:extra{i}"} for i in range(6)] + [LISTING], response={**SUCCESS, "extra": True})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(requests), 1)

    def test_negative_retry_limit_cannot_skip_the_calculation(self):
        for language, command in self.commands().items():
            with self.subTest(language=language):
                result, _ = self.run_example(command, retries="-1")
                self.assertNotEqual(result.returncode, 0)

    def test_zero_is_a_usable_calculation(self):
        for language, command in self.commands().items():
            with self.subTest(language=language):
                result, requests = self.run_example(command, response={**SUCCESS, "taxable_value": "0.00"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(requests), 1)

    def test_retries_only_repeat_server_errors(self):
        for language, command in self.commands().items():
            for sequence, expected_code, attempts in (
                ([(503, {}), (200, SUCCESS)], 0, 2),
                ([(503, b"unavailable")], 1, 2),
                ([(422, b"invalid request")], 1, 1),
                ([(200, b"invalid JSON")], 1, 1),
            ):
                with self.subTest(language=language, sequence=sequence):
                    result, requests = self.run_example(command, sequence=sequence, retries="1")
                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertEqual(len(requests), attempts)
                    self.assertEqual("=== Done ===" in result.stdout, expected_code == 0)

    def test_discovery_failures_and_retries(self):
        malformed = json.dumps([LISTING]).replace('"label":', '"extra":NaN,"label":').encode()
        for language, command in self.commands().items():
            for sequence, expected_code, attempts, post_count in (
                ([(503, {}), (200, [LISTING])], 0, 2, 1),
                ([(503, {})], 1, 2, 0),
                ([(422, {})], 1, 1, 0),
                ([(200, b"invalid JSON")], 1, 1, 0),
                ([(200, malformed)], 1, 1, 0),
            ):
                with self.subTest(language=language, sequence=sequence):
                    result, requests = self.run_example(command, get_sequence=sequence, retries="1", expected_get_attempts=attempts)
                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertEqual(len(requests), post_count)
                    self.assertEqual("=== Done ===" in result.stdout, expected_code == 0)

    def test_transport_and_read_timeouts_fail_without_retrying(self):
        for language, command in self.commands().items():
            for response in (DISCONNECT, DELAY):
                with self.subTest(language=language, response=response):
                    result, requests = self.run_example(command, response=response, retries="1", timeout="1")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(len(requests), 1)
                    self.assertNotIn("=== Done ===", result.stdout)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn("Unhandled exception", result.stderr)

    def test_dotnet_module_discovery_cannot_fail_silently(self):
        for option in ("modules", "filtered"):
            for response in (None, {}, [None], [], [{"module_uri": "urn:sbrm:module:other"}],
                             [{"module_uri": "urn:sbrm:module:fbt", "calculators": []}],
                             [{**LISTING, "supported_periods": []}], b"invalid JSON", DISCONNECT):
                with self.subTest(option=option, response=response):
                    result, requests = self.run_example(self.commands()["dotnet"], **{option: response})
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(len(requests), 1)
                    self.assertNotIn("=== Done ===", result.stdout)
                    self.assertNotIn("Unhandled exception", result.stderr)

    def test_mcp_probe_checks_the_envelope_and_required_capability(self):
        valid = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [
            {"name": "new-tool"}, {"name": "fbt-car-operating-cost", "extra": True}]}}
        command = [sys.executable, str(ROOT / "examples/python/probe_contract.py"), "mcp"]
        for value, expected in ((valid, 0), (None, 1), ([], 1), ({**valid, "error": {}}, 1),
                                ({**valid, "id": True}, 1), ({**valid, "id": "1"}, 1),
                                ({**valid, "id": 2}, 1), ({**valid, "jsonrpc": "1.0"}, 1),
                                ({**valid, "result": None}, 1), ({**valid, "result": {"tools": []}}, 1)):
            with self.subTest(value=value):
                result = subprocess.run(command, input=json.dumps(value), capture_output=True,
                                        text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, expected, result.stderr)

        for raw in (
            '{"jsonrpc":"2.0","id":2,"id":1,"result":{"tools":[{"name":"fbt-car-operating-cost"}]}}',
            '{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"fbt-car-operating-cost"}]},"extra":NaN}',
        ):
            with self.subTest(raw=raw):
                result = subprocess.run(command, input=raw, capture_output=True, text=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 1, result.stderr)



if __name__ == "__main__":
    unittest.main()
