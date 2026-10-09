import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "unified-android" / "tools" / "verify_volume_evidence.py"
SPEC = importlib.util.spec_from_file_location("verify_volume_evidence", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_report():
    pid = 4242
    pairs = []
    level = 5
    for _ in range(2):
        pairs.append({
            "direction": "down", "requestedHoldMs": 40, "holdMs": 40.2,
            "before": level, "after": level - 1, "settledAfter": level - 1,
            "downEventCount": 1, "upEventCount": 1, "repeatCount": 0,
            "levelChangedIndices": [level - 1],
            "controllerAppliedIndices": [level - 1, level - 1],
        })
        level -= 1
    for _ in range(2):
        pairs.append({
            "direction": "up", "requestedHoldMs": 40, "holdMs": 39.8,
            "before": level, "after": level + 1, "settledAfter": level + 1,
            "downEventCount": 1, "upEventCount": 1, "repeatCount": 0,
            "levelChangedIndices": [level + 1],
            "controllerAppliedIndices": [level + 1, level + 1],
        })
        level += 1
    sinks = []
    for role in sorted(MODULE.REQUIRED_SINK_ROLES):
        sink = {
            "id": role, "role": role, "pid": pid,
            "stream": "STREAM_MUSIC", "activeBefore": True,
            "activeAtMute": True, "registeredWithController": True,
            "localGainAtMute": 0.0,
            "mixerLeftDbBefore": -24.0, "mixerRightDbBefore": -24.0,
            "mixerLeftDbAtMute": "-inf", "mixerRightDbAtMute": "-inf",
            "mixerLeftDbRestored": -24.0, "mixerRightDbRestored": -24.0,
        }
        if role == "browser.webview":
            sink.update({
                "muteAuthority": "platform-stream",
                "registeredWithController": False,
                "localGainAtMute": None,
            })
        if role == "menu.soundpool":
            sink.update({
                "soundPoolStreamId": 17,
                "perIdGainLogAtMute": True,
                "startGain": 0.5,
                "startToMuteMs": 22.0,
            })
        sinks.append(sink)
    return {
        "schemaVersion": MODULE.SCHEMA,
        "package": MODULE.PACKAGE,
        "apkSha256": "a" * 64,
        "pid": pid,
        "quickPairs": pairs,
        "sinkInventoryComplete": True,
        "sinks": sinks,
        "registeredSinkIdsAtMute": [
            sink["id"] for sink in sinks
            if sink.get("muteAuthority", "app-local") == "app-local"
        ],
        "platformStreamSinkIdsAtMute": [
            sink["id"] for sink in sinks
            if sink.get("muteAuthority") == "platform-stream"
        ],
        "systemStreamIndexAtMute": 0,
        "controllerGainAtMute": 0.0,
    }


class VolumeEvidenceTest(unittest.TestCase):
    def test_complete_pid_bound_evidence_passes(self):
        self.assertEqual(MODULE.verify(valid_report()), [])

    def test_old_final_index_and_log_subsequence_cannot_pass(self):
        old = {
            "original": 12, "start": 5, "muted": 0, "restored": 5,
            "appliedGainIndices": [4, 4, 3, 3, 2, 2, 1, 1, 0, 0,
                                   1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "discreteDownUpPairs": 10, "longPressUsed": False,
        }
        errors = MODULE.verify(old)
        self.assertTrue(any("schemaVersion" in value for value in errors))
        self.assertTrue(any("quickPairs" in value for value in errors))
        self.assertTrue(any("sink" in value for value in errors))

    def test_double_transition_and_post_up_drift_fail(self):
        report = valid_report()
        pair = report["quickPairs"][0]
        pair["after"] = pair["before"] - 2
        pair["settledAfter"] = pair["before"] - 1
        pair["levelChangedIndices"] = [pair["before"] - 1,
                                       pair["before"] - 2]
        errors = MODULE.verify(report)
        self.assertTrue(any("pair moved" in value for value in errors))
        self.assertTrue(any("settled after UP" in value for value in errors))
        self.assertTrue(any("exactly one STREAM_MUSIC" in value for value in errors))

    def test_host_requested_duration_cannot_replace_kernel_timing(self):
        report = valid_report()
        report["quickPairs"][0]["holdMs"] = 141.0
        errors = MODULE.verify_quick_pairs(report)
        self.assertTrue(any("35-60 ms" in value for value in errors))

    def test_kernel_repeat_or_duplicate_edge_fails(self):
        report = valid_report()
        pair = report["quickPairs"][0]
        pair["downEventCount"] = 2
        pair["repeatCount"] = 1
        errors = MODULE.verify_quick_pairs(report)
        self.assertTrue(any("kernel DOWN" in value for value in errors))
        self.assertTrue(any("long-press repeat" in value for value in errors))

    def test_log_only_zero_does_not_prove_all_sinks_muted(self):
        report = valid_report()
        report["sinks"] = report["sinks"][:-1]
        report["registeredSinkIdsAtMute"] = [
            row["id"] for row in report["sinks"]
            if row.get("muteAuthority", "app-local") == "app-local"
        ]
        report["platformStreamSinkIdsAtMute"] = [
            row["id"] for row in report["sinks"]
            if row.get("muteAuthority") == "platform-stream"
        ]
        errors = MODULE.verify(report)
        self.assertTrue(any("missing sink roles" in value for value in errors))

    def test_missing_browser_role_fails_even_when_all_local_sinks_pass(self):
        report = valid_report()
        report["sinks"] = [row for row in report["sinks"]
                           if row["role"] != "browser.webview"]
        report["platformStreamSinkIdsAtMute"] = []
        errors = MODULE.verify(report)
        self.assertTrue(any("browser.webview" in value for value in errors))

    def test_browser_cannot_masquerade_as_controller_owned(self):
        report = valid_report()
        browser = next(row for row in report["sinks"]
                       if row["role"] == "browser.webview")
        browser["muteAuthority"] = "app-local"
        browser["registeredWithController"] = True
        browser["localGainAtMute"] = 0.0
        report["registeredSinkIdsAtMute"].append(browser["id"])
        report["platformStreamSinkIdsAtMute"] = []
        errors = MODULE.verify(report)
        # The report is internally self-consistent, but it no longer satisfies
        # the source-audited platform-stream boundary for Chromium/WebView.
        self.assertTrue(any("browser.webview" in value for value in errors))

    def test_platform_stream_inventory_must_name_browser_exactly(self):
        report = valid_report()
        report["platformStreamSinkIdsAtMute"] = []
        errors = MODULE.verify(report)
        self.assertTrue(any("platformStreamSinkIdsAtMute" in value
                            for value in errors))

    def test_sink_inventories_reject_duplicate_identifiers(self):
        report = valid_report()
        report["registeredSinkIdsAtMute"].append(
            report["registeredSinkIdsAtMute"][0]
        )
        report["platformStreamSinkIdsAtMute"].append("browser.webview")
        errors = MODULE.verify(report)
        self.assertTrue(any("registeredSinkIdsAtMute" in value
                            for value in errors))
        self.assertTrue(any("platformStreamSinkIdsAtMute" in value
                            for value in errors))

    def test_finite_audio_at_mute_fails_even_when_local_log_says_zero(self):
        report = valid_report()
        report["sinks"][0]["mixerLeftDbAtMute"] = -24.0
        errors = MODULE.verify(report)
        self.assertTrue(any("digitally silent" in value for value in errors))

    def test_evidence_is_bound_to_exact_candidate_apk(self):
        report = valid_report()
        self.assertTrue(any("hash" in value.lower() for value in
                            MODULE.verify(report, expected_apk_sha256="b" * 64)))

    def test_soundpool_parser_consumes_per_id_gain_log(self):
        log = """
08-10 10:00:00.000 I/LucentMenuSfx( 4242): SoundPool sink started stream=17 gain=0.5
08-10 10:00:00.021 I/LucentMenuSfx( 4242): SoundPool sink gain stream=17 gain=0.0
08-10 10:00:00.022 I/LucentMenuSfx( 4242): SoundPool active sinks gain=0.0 trackedStreams=1
        """
        self.assertEqual(MODULE.parse_soundpool_sink_transitions(log, 4242), [{
            "soundPoolStreamId": 17,
            "startGain": 0.5,
            "localGainAtMute": 0.0,
            "startToMuteMs": 21.0,
            "perIdGainLogAtMute": True,
        }])
        rows = MODULE.soundpool_sink_rows(
            log, 4242, mixer_before=(-24.0, -24.0),
            mixer_at_mute=("-inf", "-inf"),
            mixer_restored=(-24.0, -24.0),
        )
        self.assertEqual(rows[0]["id"], "soundpool:17")
        self.assertEqual(rows[0]["role"], "menu.soundpool")
        self.assertEqual(rows[0]["localGainAtMute"], 0.0)
        self.assertEqual(rows[0]["mixerLeftDbAtMute"], "-inf")

    def test_soundpool_aggregate_log_cannot_replace_per_id_proof(self):
        log = """
08-10 10:00:00.000 I/LucentMenuSfx(4242): SoundPool sink started stream=17 gain=0.5
08-10 10:00:00.020 I/LucentMenuSfx(4242): SoundPool active sinks gain=0.0 trackedStreams=1
        """
        with self.assertRaisesRegex(ValueError, "per-ID zero-gain"):
            MODULE.parse_soundpool_sink_transitions(log, 4242)

    def test_soundpool_completed_stream_cannot_masquerade_as_active(self):
        log = """
08-10 10:00:00.000 4242 4243 I LucentMenuSfx: SoundPool sink started stream=17 gain=0.5
08-10 10:00:00.120 4242 4243 I LucentMenuSfx: SoundPool sink gain stream=17 gain=0.0
        """
        with self.assertRaisesRegex(ValueError, "active proof"):
            MODULE.parse_soundpool_sink_transitions(log, 4242)

    def test_soundpool_log_is_bound_to_emufusion_pid(self):
        log = """
08-10 10:00:00.000 I/LucentMenuSfx(9999): SoundPool sink started stream=17 gain=0.5
08-10 10:00:00.010 I/LucentMenuSfx(9999): SoundPool sink gain stream=17 gain=0.0
        """
        with self.assertRaisesRegex(ValueError, "no positive-gain"):
            MODULE.parse_soundpool_sink_transitions(log, 4242)

    def test_full_gate_rejects_unbound_soundpool_summary(self):
        report = valid_report()
        sink = next(row for row in report["sinks"]
                    if row["role"] == "menu.soundpool")
        for key in ("soundPoolStreamId", "perIdGainLogAtMute", "startGain",
                    "startToMuteMs"):
            sink.pop(key)
        errors = MODULE.verify(report)
        self.assertTrue(any("concrete SoundPool stream ID" in value
                            for value in errors))
        self.assertTrue(any("per-ID SoundPool" in value for value in errors))
        self.assertTrue(any("positive-gain SoundPool" in value for value in errors))
        self.assertTrue(any("proved active" in value for value in errors))


if __name__ == "__main__":
    unittest.main()
