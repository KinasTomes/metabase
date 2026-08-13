import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_nightly


def sample_report(value=423.0):
    return {
        "schema": "analytics",
        "as_of": "2025-12",
        "findings": [{
            "id": "transaction_count_by_province:Bình Dương:2025-12",
            "direction": "up",
            "value": value,
            "baseline_median": 291.0,
            "z": 7.74,
            "n": 423,
            "kind": None,
        }],
        "suppressed": [],
    }


class PublishedStateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        state = Path(self.temp_dir.name) / ".last-published.json"
        self.state_patch = mock.patch.object(run_nightly, "LAST_SENT", state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_same_claims_are_duplicate_but_corrected_value_is_new(self):
        report = sample_report()
        run_nightly.remember_sent(report)

        self.assertTrue(run_nightly.already_sent(report))
        self.assertFalse(run_nightly.already_sent(sample_report(value=424.0)))

    def test_malformed_state_fails_open(self):
        run_nightly.LAST_SENT.write_text("[]", encoding="utf-8")
        self.assertFalse(run_nightly.already_sent(sample_report()))


class NarrationGatewayTest(unittest.TestCase):
    def test_read_timeout_becomes_a_degradable_gateway_error(self):
        with (
            mock.patch.dict("os.environ", {
                "MB_LLM_OPENROUTER_API_BASE_URL": "https://gateway.invalid",
                "MB_LLM_OPENROUTER_API_KEY": "test-key",
            }),
            mock.patch.object(
                run_nightly.narrate.urllib.request,
                "urlopen",
                side_effect=TimeoutError,
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "gateway timed out"):
                run_nightly.narrate.call_llm("payload", "model")


class OneCycleTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_patch = mock.patch.object(
            run_nightly, "LAST_SENT", Path(self.temp_dir.name) / ".last-published.json")
        self.out_patch = mock.patch.object(run_nightly, "OUT", Path(self.temp_dir.name) / "out")
        self.state_patch.start()
        self.out_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.addCleanup(self.out_patch.stop)

        print_patch = mock.patch("builtins.print")
        print_patch.start()
        self.addCleanup(print_patch.stop)

        connection = mock.Mock()
        patches = [
            mock.patch.object(run_nightly.scan, "load_env"),
            mock.patch.object(run_nightly.publish, "load_env"),
            mock.patch.object(run_nightly.scan, "connect", return_value=connection),
            mock.patch.object(run_nightly.scan, "fetch_series", return_value=["series"]),
            mock.patch.object(run_nightly.scan, "latest_month", return_value="2025-12"),
            mock.patch.object(run_nightly.scan, "build_report", return_value=sample_report()),
            mock.patch.object(run_nightly.link_questions, "link", return_value={"linked": 1}),
            mock.patch.object(run_nightly.narrate, "narrate", return_value={
                "text": "ok", "verified": True, "fidelity": "ok",
            }),
        ]
        self.mocks = [patch.start() for patch in patches]
        for patch in patches:
            self.addCleanup(patch.stop)

    def test_scheduled_duplicate_skips_expensive_and_delivery_steps(self):
        run_nightly.remember_sent(sample_report())
        with mock.patch.object(run_nightly.publish, "publish") as publish_report:
            run_nightly.one_cycle(
                "analytics", None, "model", {"file", "slack"}, False)

        self.assertFalse(self.mocks[6].called)  # link_questions.link
        self.assertFalse(self.mocks[7].called)  # narrate.narrate
        publish_report.assert_not_called()

    def test_slack_failure_keeps_file_and_does_not_mark_sent(self):
        def publish_side_effect(report, sinks, out_dir, quiet_empty=False):
            if sinks == {"slack"}:
                raise SystemExit("Slack unreachable")
            return {"file": "summary.md"}

        with mock.patch.object(
            run_nightly.publish, "publish", side_effect=publish_side_effect) as publish_report:
            run_nightly.one_cycle(
                "analytics", None, "model", {"file", "slack"}, False)

        self.assertEqual(publish_report.call_count, 2)
        self.assertFalse(run_nightly.LAST_SENT.exists())

    def test_successful_slack_delivery_marks_sent(self):
        def publish_side_effect(report, sinks, out_dir, quiet_empty=False):
            return {"slack": "200 ok"} if sinks == {"slack"} else {"file": "summary.md"}

        with mock.patch.object(run_nightly.publish, "publish", side_effect=publish_side_effect):
            run_nightly.one_cycle(
                "analytics", None, "model", {"file", "slack"}, False)

        state = json.loads(run_nightly.LAST_SENT.read_text(encoding="utf-8"))
        self.assertEqual(state["as_of"], "2025-12")
        self.assertTrue(run_nightly.already_sent(sample_report()))

    def test_manual_cycle_can_repeat_a_published_report(self):
        run_nightly.remember_sent(sample_report())
        with mock.patch.object(
            run_nightly.publish,
            "publish",
            return_value={"file": "summary.md"},
        ) as publish_report:
            run_nightly.one_cycle(
                "analytics", None, "model", {"file"}, False, allow_repeat=True)

        self.assertTrue(self.mocks[6].called)  # link_questions.link
        self.assertTrue(self.mocks[7].called)  # narrate.narrate
        publish_report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
