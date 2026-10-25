import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import binance_delisting_monitor as monitor


class DeliveryTests(unittest.TestCase):
    def test_http_error_and_invalid_json_fail(self):
        for http_error in (True, False):
            response = Mock(status_code=503 if http_error else 200)
            if http_error:
                response.raise_for_status.side_effect = monitor.requests.HTTPError("unavailable")
            else:
                response.json.side_effect = ValueError("invalid JSON")
            with self.subTest(http_error=http_error), \
                 patch.object(monitor.requests, "post", return_value=response):
                with self.assertRaises((monitor.requests.HTTPError, ValueError)):
                    monitor.push_webhook("https://open.larksuite.com/example", "test")

    def test_lark_receipts(self):
        for body, accepted in [
            ({"code": 0}, True),
            ({"StatusCode": 0}, True),
            ({"code": 19024, "msg": "rejected"}, False),
            ({"code": 0, "StatusCode": 1}, False),
            ({}, False),
            ([], False),
        ]:
            with self.subTest(body=body):
                response = Mock(status_code=200)
                response.json.return_value = body
                with patch.object(monitor.requests, "post", return_value=response):
                    if accepted:
                        monitor.push_webhook("https://open.larksuite.com/example", "test")
                    else:
                        with self.assertRaises(RuntimeError):
                            monitor.push_webhook("https://open.larksuite.com/example", "test")

    def test_failed_delivery_survives_missing_article_and_restarts(self):
        article = monitor.Announcement("test-code", "Will Delist TESTUSDT", 161, "Delisting", 0)
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "seen.json"
            args = monitor.build_parser().parse_args([
                "--state", str(state_path), "--webhook", "https://open.larksuite.com/example",
            ])
            with patch.dict(monitor.os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
                with patch.object(monitor, "collect", return_value=[article]), \
                     patch.object(monitor, "push_webhook", side_effect=RuntimeError("offline")):
                    self.assertEqual(monitor.run_once(args), 1)
                state = json.loads(state_path.read_text())
                self.assertIn(article.code, state["pending"])
                self.assertIn(article.code, state["seen"])
                # Dry runs must preserve the pending queue and never send.
                args.dry_run = True
                before = state_path.read_bytes()
                with patch.object(monitor, "collect", return_value=[]), \
                     patch.object(monitor, "push_webhook") as send:
                    self.assertEqual(monitor.run_once(args), 0)
                    send.assert_not_called()
                self.assertEqual(state_path.read_bytes(), before)
                args.dry_run = False
                with patch.object(monitor, "collect", return_value=[]), \
                     patch.object(monitor, "push_webhook") as send:
                    self.assertEqual(monitor.run_once(args), 0)
                    self.assertIn(article.title, send.call_args.args[1])
                    self.assertEqual(json.loads(state_path.read_text())["pending"], {})
                    self.assertEqual(monitor.run_once(args), 0)
                    self.assertEqual(send.call_count, 1)

    def test_without_webhook_keeps_incremental_behavior(self):
        article = monitor.Announcement("test-code", "Will Delist TESTUSDT", 161, "Delisting", 0)
        with tempfile.TemporaryDirectory() as directory:
            args = monitor.build_parser().parse_args(["--state", str(Path(directory) / "seen.json")])
            with patch.dict(monitor.os.environ, {}, clear=True), \
                 patch.object(monitor, "collect", return_value=[article]), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 patch.object(monitor, "push_webhook") as send:
                self.assertEqual(monitor.run_once(args), 0)
                self.assertEqual(monitor.run_once(args), 0)
                send.assert_not_called()
            state = json.loads(Path(args.state).read_text())
            self.assertIn(article.code, state["seen"])
            self.assertEqual(state["pending"], {})


if __name__ == "__main__":
    unittest.main()
