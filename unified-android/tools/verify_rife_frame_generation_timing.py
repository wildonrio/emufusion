#!/usr/bin/env python3
"""Verify the timing-only component of an integrated RIFE qualification run.

This deliberately cannot qualify visual quality.  It proves that the latest
external health snapshot is bound to one scheduler epoch and exact panel
divisor, that every delivered row came from the submission ledger, and that the
live record+GPU work and physical scanout met their selected slots.  The legacy
backend-owned Vulkan/SurfaceControl path and the current EmuFusion-owned EGL
path deliberately have different evidence contracts; unavailable WSI concepts
must never be fabricated for the app-owned path.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import zlib
from pathlib import Path
from typing import Any, Optional


PREFIX = "App swap cadence"
DRIVER_LEAD_NS = 2_000_000
MIN_PRESENT_TOLERANCE_NS = 150_000
MAX_PRESENT_ERROR_FRACTION = 0.02
MAX_RATE_ERROR_FRACTION = 0.01
MIN_COMPONENT_SPAN_NS = 2_000_000_000
# One component segment must be long enough to expose more than a transient
# clean burst while still fitting Android's finite frame-timestamp history and
# F-Zero's bounded attract races.  Long moving-game certification is a
# separate multi-segment campaign below; it never splices timing inside a
# component segment.
MIN_RUNTIME_SPAN_NS = 11_000_000_000
MIN_CAMPAIGN_SPAN_NS = 60_000_000_000
MIN_CAMPAIGN_SEGMENTS = 3

REQUIRED = {
    "schedulerUnderrun",
    "generator", "role", "displayId", "externalBackend",
    "source", "target", "panel", "panelMeasured", "swap",
    "schedulerEpoch", "physicalAvailable", "physicalBackend", "physical",
    "physicalQualified", "physicalSamples", "physicalPresented",
    "physicalDropped", "physicalUnavailable", "physicalPending",
    "externalSubmitted", "externalFrameTimelineCallbacks",
    "externalFrameTimelineMatched", "externalFrameTimelineUnavailable",
    "externalFrameTimelineCommitted", "externalFrameTimelineErrorMaxNs",
    "externalFrameTimelineNativeCallbackSequence",
    "externalFrameTimelineNativeFrameTimeNs",
    "externalFrameTimelineProbeLive", "externalFrameTimelineProbeNoLive",
    "externalFrameTimelineProbeErrorSignedMinNs",
    "externalFrameTimelineProbeErrorSignedMaxNs",
    "externalFrameTimelineProbeErrorSignedLastNs",
    "externalPhysicalEndpoint",
    "externalPhysicalGenerated", "externalTimingQualified",
    "externalTimingEpoch", "externalTimingWindow",
    "externalTimingDroppedBaseline", "externalTimingUnavailableBaseline",
    "externalTimingSamples", "externalTimingEndpoint",
    "externalTimingGenerated", "externalTimingStartNs", "externalTimingEndNs",
    "externalTimingScans",
    "externalTimingPipelineScans",
    "externalTimingRefreshNs", "externalDeadlineMisses",
    "externalDesiredSlotMisses", "externalEarliestPresentMisses",
    "externalEarlyPresentViolations", "externalEarlySlotMisses",
    "externalLateSlotMisses", "externalPresentMarginMinNs",
    "externalPresentMarginP05Ns", "externalPresentMarginP50Ns",
    "externalPresentMarginP95Ns", "externalPresentMarginMaxNs",
    "externalPresentMarginLastNs", "externalLateSlotMarginMinNs",
    "externalLateSlotMarginMaxNs", "externalEnqueueMaxNs", "externalGpuMaxNs",
    "externalCombinedP95Ns", "externalCombinedMaxNs",
    "externalSlotErrorMaxNs", "externalSlotErrorSignedMinNs",
    "externalSlotErrorSignedMaxNs", "externalSlotErrorSignedLastNs",
    "externalPhysicalClockPeriodNs", "externalPhysicalClockScans",
    "externalPhysicalClockCalibrated",
    "externalPhysicalClockCalibrationPresents",
    "externalAppOwned", "externalBindMaxNs", "externalSwapMaxNs",
    "externalGpuBudgetMisses",
    "externalPhaseMin", "externalPhaseMax",
    "externalContentNumericPassed", "externalContentEpoch",
    "externalContentProofs", "externalContentEndpoints",
    "externalContentGenerated", "externalContentMovingGenerated",
    "externalContentDistinctMovingGenerated", "externalContentSceneCutRisk",
    "externalUnsafePairs",
    "externalContentEndpointFailures", "externalContentEqualsLeft",
    "externalContentEqualsRight", "externalContentAnalysisMaxNs",
    "externalContentEndpointMadMaxPpm", "externalContentHistogramMaxPpm",
    "externalContentOutputLeftMadMaxPpm",
    "externalContentOutputRightMadMaxPpm", "externalContentManualPassed",
}

INTEGER_FIELDS = {
    "schedulerUnderrun",
    "generator", "displayId", "panelMeasured", "schedulerEpoch", "physicalAvailable",
    "physicalQualified", "physicalSamples", "physicalPresented",
    "physicalDropped", "physicalUnavailable", "physicalPending",
    "externalSubmitted", "externalFrameTimelineCallbacks",
    "externalFrameTimelineMatched", "externalFrameTimelineUnavailable",
    "externalFrameTimelineCommitted", "externalFrameTimelineErrorMaxNs",
    "externalFrameTimelineNativeCallbackSequence",
    "externalFrameTimelineNativeFrameTimeNs",
    "externalFrameTimelineProbeLive", "externalFrameTimelineProbeNoLive",
    "externalFrameTimelineProbeErrorSignedMinNs",
    "externalFrameTimelineProbeErrorSignedMaxNs",
    "externalFrameTimelineProbeErrorSignedLastNs",
    "externalPhysicalEndpoint",
    "externalPhysicalGenerated", "externalTimingQualified",
    "externalTimingEpoch", "externalTimingWindow",
    "externalTimingDroppedBaseline", "externalTimingUnavailableBaseline",
    "externalTimingSamples", "externalTimingEndpoint",
    "externalTimingGenerated", "externalTimingStartNs", "externalTimingEndNs",
    "externalTimingScans",
    "externalTimingPipelineScans",
    "externalTimingRefreshNs", "externalDeadlineMisses",
    "externalDesiredSlotMisses", "externalEarliestPresentMisses",
    "externalEarlyPresentViolations", "externalEarlySlotMisses",
    "externalLateSlotMisses", "externalPresentMarginMinNs",
    "externalPresentMarginP05Ns", "externalPresentMarginP50Ns",
    "externalPresentMarginP95Ns", "externalPresentMarginMaxNs",
    "externalPresentMarginLastNs", "externalLateSlotMarginMinNs",
    "externalLateSlotMarginMaxNs", "externalEnqueueMaxNs", "externalGpuMaxNs",
    "externalCombinedP95Ns", "externalCombinedMaxNs",
    "externalSlotErrorMaxNs", "externalSlotErrorSignedMinNs",
    "externalSlotErrorSignedMaxNs", "externalSlotErrorSignedLastNs",
    "externalPhysicalClockPeriodNs", "externalPhysicalClockScans",
    "externalPhysicalClockCalibrated",
    "externalPhysicalClockCalibrationPresents",
    "externalAppOwned", "externalBindMaxNs", "externalSwapMaxNs",
    "externalGpuBudgetMisses",
    "externalContentNumericPassed", "externalContentEpoch",
    "externalContentProofs", "externalContentEndpoints",
    "externalContentGenerated", "externalContentMovingGenerated",
    "externalContentDistinctMovingGenerated", "externalContentSceneCutRisk",
    "externalUnsafePairs",
    "externalContentEndpointFailures", "externalContentEqualsLeft",
    "externalContentEqualsRight", "externalContentAnalysisMaxNs",
    "externalContentEndpointMadMaxPpm", "externalContentHistogramMaxPpm",
    "externalContentOutputLeftMadMaxPpm",
    "externalContentOutputRightMadMaxPpm", "externalContentManualPassed",
}

FLOAT_FIELDS = {
    "source", "target", "panel", "swap", "physical",
    "externalPhaseMin", "externalPhaseMax",
}


class EvidenceError(RuntimeError):
    pass


def _decode(line: str) -> dict[str, Any]:
    tail = line.split(PREFIX, 1)[1]
    pairs = re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", tail)
    values: dict[str, str] = {}
    for key, value in pairs:
        if key in values:
            raise EvidenceError(f"duplicate RIFE timing field: {key}")
        values[key] = value
    missing = sorted(REQUIRED - values.keys())
    if missing:
        raise EvidenceError("RIFE timing line is missing: " + ",".join(missing))
    decoded: dict[str, Any] = {"line": line}
    try:
        for key in INTEGER_FIELDS:
            decoded[key] = int(values[key], 10)
        for key in FLOAT_FIELDS:
            decoded[key] = float(values[key])
    except ValueError as error:
        raise EvidenceError("RIFE timing line has malformed numeric data") from error
    decoded["role"] = values["role"]
    decoded["externalBackend"] = values["externalBackend"]
    decoded["physicalBackend"] = values["physicalBackend"]
    for key in FLOAT_FIELDS:
        if not math.isfinite(decoded[key]):
            raise EvidenceError(f"RIFE timing field is non-finite: {key}")
    return decoded


def snapshot_lines(log_text: str) -> list[str]:
    """Reassemble bounded Android records without accepting partial evidence."""
    result = []
    pending = {}
    completed = set()
    pattern = re.compile(r"CadenceSnapshot id=(\d+:\d+:\d+) part=(\d+)/(\d+) crc=(\d+) data=(.*)$")
    for line in log_text.splitlines():
        if "CadenceSnapshot " not in line:
            if PREFIX in line:
                result.append(line)  # historical single-line format
            continue
        match = pattern.search(line)
        if match is None:
            raise EvidenceError("malformed cadence snapshot part")
        identity, index, count, checksum, payload = match.groups()
        index, count, checksum = int(index), int(count), int(checksum)
        if not 1 <= index <= count <= 100 or identity in completed:
            raise EvidenceError("invalid or duplicated cadence snapshot identity")
        state = pending.setdefault(identity, (count, checksum, []))
        if state[:2] != (count, checksum) or index != len(state[2]) + 1:
            raise EvidenceError("missing, reordered or inconsistent cadence snapshot part")
        state[2].append(payload)
        if index == count:
            snapshot = ''.join(state[2])
            if zlib.crc32(snapshot.encode('utf-8')) != checksum:
                raise EvidenceError("cadence snapshot checksum mismatch")
            if not snapshot.startswith(PREFIX):
                raise EvidenceError("invalid cadence snapshot payload")
            result.append(snapshot)
            del pending[identity]
            completed.add(identity)
    if pending:
        raise EvidenceError("incomplete cadence snapshot")
    return result


def timing_records(log_text: str) -> list[dict[str, Any]]:
    records = []
    for line in snapshot_lines(log_text):
        if PREFIX not in line:
            continue
        decoded = _decode(line)
        if decoded["physicalBackend"] in ("vulkan", "egl-app-owned"):
            records.append(decoded)
    return records


def _all_records(log_text: str) -> list[dict[str, Any]]:
    return [_decode(line) for line in snapshot_lines(log_text)]


def verify_timing(
        log_text: str, *, role: Optional[str] = None,
        display_id: Optional[int] = None,
        actual_present_timestamps: Optional[list[int]] = None,
        minimum_span_ns: int = MIN_COMPONENT_SPAN_NS) -> dict[str, Any]:
    if minimum_span_ns < MIN_COMPONENT_SPAN_NS:
        raise EvidenceError("RIFE minimum timing span is too short")
    all_records = _all_records(log_text)
    if role is not None:
        all_records = [row for row in all_records if row["role"] == role]
    if display_id is not None:
        all_records = [row for row in all_records
                       if row["displayId"] == display_id]
    if not all_records:
        raise EvidenceError("no frame-generation timing records")
    supported_backends = ("vulkan", "egl-app-owned")
    if all_records[-1]["physicalBackend"] not in supported_backends:
        raise EvidenceError("latest frame-generation backend is not RIFE")
    records = [record for record in all_records
               if record["physicalBackend"] in supported_backends]
    if not records:
        raise EvidenceError("no external RIFE timing records")
    row = records[-1]
    app_owned = row["physicalBackend"] == "egl-app-owned"

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise EvidenceError(message)

    generator_records = [record for record in records
                         if record["generator"] == row["generator"] and
                         record["physicalBackend"] == row["physicalBackend"]]
    # Physical timestamps describe submitted buffers only. Missing scheduled
    # outputs must independently fail, even if an older runtime incorrectly
    # labels its submitted-buffer ledger qualified. A later clean window must
    # not erase a loss earlier in the same renderer session.
    require(all(record["schedulerUnderrun"] == 0
                for record in generator_records),
            "scheduler underrun: scheduled outputs were missing or counter invalid")
    require(all(current["externalUnsafePairs"] >=
                previous["externalUnsafePairs"]
                for previous, current in zip(
                    generator_records, generator_records[1:])),
            "handled unsafe-pair counter regressed")
    require(all(current["physicalDropped"] >= previous["physicalDropped"] and
                current["physicalUnavailable"] >=
                        previous["physicalUnavailable"]
                for previous, current in zip(
                    generator_records, generator_records[1:])),
            "physical outcome counter regressed")
    require(all(current["externalTimingWindow"] >=
                previous["externalTimingWindow"]
                for previous, current in zip(
                    generator_records, generator_records[1:])),
            "app-owned timing-window identity regressed")
    require(row["externalUnsafePairs"] >= 0,
            "handled unsafe-pair counter is invalid")
    require(row["externalBackend"] == "RIFE",
            "external timing record is not the RIFE backend")

    scans = row["externalTimingScans"]
    refresh_ns = row["externalTimingRefreshNs"]
    require(scans > 0 and refresh_ns > DRIVER_LEAD_NS,
            "invalid exact panel-divisor identity")
    interval_ns = scans * refresh_ns
    require(interval_ns < 2**63, "output interval overflow")
    target_hz = 1_000_000_000.0 / interval_ns
    panel_hz = 1_000_000_000.0 / refresh_ns
    require(row["panelMeasured"] == 1 and row["physicalAvailable"] == 1,
            "measured physical clock unavailable")
    require(row["externalTimingQualified"] == 1,
            "latest RIFE timing snapshot is not qualified")
    require(row["externalTimingEpoch"] == row["schedulerEpoch"] > 0,
            "RIFE timing evidence belongs to another presentation epoch")
    require(row["externalTimingPipelineScans"] == 0,
            "RIFE timing evidence uses an unqualified presentation pipeline")
    require(row["externalAppOwned"] == (1 if app_owned else 0),
            "RIFE presentation ownership identity is inconsistent")
    require(abs(row["panel"] - panel_hz) <= panel_hz * MAX_RATE_ERROR_FRACTION,
            "reported panel clock disagrees with Vulkan refresh duration")
    require(abs(row["target"] - target_hz) <= target_hz * MAX_RATE_ERROR_FRACTION,
            "target is not the exact physical panel divisor")
    require(row["source"] > 0.0 and row["source"] <= row["target"] * 1.01 and
            row["target"] <= 2.0 * row["source"] * 1.01,
            "source/target violates the maximum-2x contract")
    require(abs(row["physical"] - target_hz) <=
            target_hz * MAX_RATE_ERROR_FRACTION,
            "actual physical cadence misses its target")

    samples = row["externalTimingSamples"]
    endpoints = row["externalTimingEndpoint"]
    generated = row["externalTimingGenerated"]
    # physicalSamples is the bounded PhysicalPresentationCadence observation
    # ring (capacity 256); externalTimingSamples is the complete current-epoch
    # presentation ledger.  Equating them made every healthy long run fail as
    # soon as the rolling ring filled (physical r79: 256 versus 1,226).  Rate
    # and spacing are proved by the nonempty rolling ring/physical Hz above;
    # endpoint/generated kind conservation belongs to the epoch ledger.
    require(row["physicalSamples"] >= 17,
            "physical cadence ring has insufficient samples")
    timing_start_ns = row["externalTimingStartNs"]
    timing_end_ns = row["externalTimingEndNs"]
    timing_span_ns = timing_end_ns - timing_start_ns
    require(timing_start_ns > 0 and timing_end_ns > timing_start_ns and
            timing_span_ns >= minimum_span_ns,
            "RIFE physical timing window is too short")
    expected_span_ns = (samples - 1) * interval_ns
    span_tolerance_ns = max(2 * interval_ns,
                            round(expected_span_ns * 0.02))
    require(samples > 1 and
            abs(timing_span_ns - expected_span_ns) <= span_tolerance_ns,
            "RIFE timing span disagrees with its physical sample ledger")
    require(samples == endpoints + generated,
            "target-window physical kind conservation failed")
    require(generated >= 30 and endpoints > 0,
            "insufficient endpoint/generated timing evidence")
    require(row["externalPhysicalEndpoint"] +
            row["externalPhysicalGenerated"] == row["physicalPresented"],
            "lifetime physical kind conservation failed")
    require(row["externalSubmitted"] ==
            row["physicalPresented"] + row["physicalPending"] +
            row["physicalDropped"] + row["physicalUnavailable"],
            "submission/physical/pending conservation failed")
    frame_timeline_fields = (
        "externalFrameTimelineMatched",
        "externalFrameTimelineUnavailable",
        "externalFrameTimelineCommitted",
        "externalFrameTimelineErrorMaxNs",
        "externalFrameTimelineNativeCallbackSequence",
        "externalFrameTimelineNativeFrameTimeNs",
        "externalFrameTimelineProbeLive",
        "externalFrameTimelineProbeNoLive",
        "externalFrameTimelineProbeErrorSignedMinNs",
        "externalFrameTimelineProbeErrorSignedMaxNs",
        "externalFrameTimelineProbeErrorSignedLastNs",
    )
    if app_owned:
        # Choreographer callback count is transport-independent and remains a
        # truthful display-callback diagnostic on the EGL-owned path. What
        # must stay zero is every SurfaceControl/frame-timeline selection,
        # token, probe and commit field: app-owned EGL never consumes them.
        require(row["externalFrameTimelineCallbacks"] > 0,
                "app-owned RIFE lacks display-callback evidence")
        require(all(row[field] == 0 for field in frame_timeline_fields),
                "app-owned RIFE fabricated a SurfaceControl frame timeline")
    else:
        require(row["externalFrameTimelineCallbacks"] > 0 and
                row["externalFrameTimelineNativeCallbackSequence"] > 0 and
                row["externalFrameTimelineNativeFrameTimeNs"] > 0 and
                row["externalFrameTimelineCallbacks"] >=
                        row["externalFrameTimelineMatched"] +
                        row["externalFrameTimelineUnavailable"] and
                row["externalFrameTimelineMatched"] >=
                        row["externalFrameTimelineCommitted"] and
                row["externalFrameTimelineCommitted"] ==
                        row["externalSubmitted"] and
                0 <= row["externalFrameTimelineErrorMaxNs"] <= 250_000,
                "SurfaceFlinger frame-timeline identity is incomplete")
        require(row["externalFrameTimelineProbeLive"] >= 0 and
                row["externalFrameTimelineProbeNoLive"] >= 0 and
                row["externalFrameTimelineProbeLive"] +
                        row["externalFrameTimelineProbeNoLive"] ==
                        row["externalFrameTimelineUnavailable"],
                "frame-timeline miss diagnostics are incomplete")
        if row["externalFrameTimelineProbeLive"] > 0:
            require(row["externalFrameTimelineProbeErrorSignedMinNs"] <=
                    row["externalFrameTimelineProbeErrorSignedLastNs"] <=
                    row["externalFrameTimelineProbeErrorSignedMaxNs"],
                    "frame-timeline nearest-slot diagnostics are inconsistent")
        else:
            require(row["externalFrameTimelineProbeErrorSignedMinNs"] == 0 and
                    row["externalFrameTimelineProbeErrorSignedMaxNs"] == 0 and
                    row["externalFrameTimelineProbeErrorSignedLastNs"] == 0,
                    "frame-timeline no-live diagnostics contain a false slot")
    require(0 <= row["physicalPending"] <= 16,
            "external physical timing queue is out of bounds")
    # Dropped/unavailable counters are intentionally lifetime-monotonic across
    # safe Direct recovery and presentation-epoch resets.  Qualification must
    # reject an outcome added by the selected generated epoch, but it must not
    # reinterpret a previously failed-closed Direct event as a fresh RIFE
    # failure forever.  Bind the exact baseline to the final record preceding
    # this epoch; when no predecessor exists, the only defensible baseline is
    # zero. Lifetime submission conservation above still accounts for every
    # outcome and the monotonic check prevents a hidden reset.
    if app_owned:
        require(row["externalTimingWindow"] > 0 and
                0 <= row["externalTimingDroppedBaseline"] <=
                        row["physicalDropped"] and
                0 <= row["externalTimingUnavailableBaseline"] <=
                        row["physicalUnavailable"],
                "app-owned timing-window outcome baseline is invalid")
        baseline_dropped = row["externalTimingDroppedBaseline"]
        baseline_unavailable = row["externalTimingUnavailableBaseline"]
    else:
        require(row["externalTimingWindow"] == 0 and
                row["externalTimingDroppedBaseline"] == 0 and
                row["externalTimingUnavailableBaseline"] == 0,
                "legacy timing evidence fabricated an app-owned window")
        first_epoch_index = next(index for index, record in
                                 enumerate(generator_records)
                                 if record["schedulerEpoch"] ==
                                        row["schedulerEpoch"])
        prior_epoch_row = (generator_records[first_epoch_index - 1]
                           if first_epoch_index > 0 else None)
        baseline_dropped = (prior_epoch_row["physicalDropped"]
                            if prior_epoch_row is not None else 0)
        baseline_unavailable = (prior_epoch_row["physicalUnavailable"]
                                if prior_epoch_row is not None else 0)
    require(row["physicalDropped"] == baseline_dropped and
            row["physicalUnavailable"] == baseline_unavailable,
            "selected epoch contains a dropped or unavailable presentation")
    require(row["externalDeadlineMisses"] == 0 and
            row["externalDesiredSlotMisses"] == 0,
            "RIFE missed a work or physical slot deadline")
    require(row["externalEarliestPresentMisses"] == 0 and
            row["externalEarlyPresentViolations"] == 0,
            "RIFE presented before a physical-present lower bound")
    require(row["externalEarlySlotMisses"] >= 0 and
            row["externalLateSlotMisses"] >= 0 and
            row["externalEarlySlotMisses"] +
            row["externalLateSlotMisses"] ==
            row["externalDesiredSlotMisses"],
            "physical slot-miss direction accounting is inconsistent")

    budget_ns = interval_ns if app_owned else interval_ns - DRIVER_LEAD_NS
    if app_owned:
        source_interval_ns = round(1_000_000_000.0 / row["source"])
        require(row["externalGpuBudgetMisses"] == 0,
                "app-owned RIFE exceeded an adjacent-endpoint GPU budget")
        require(0 < row["externalBindMaxNs"] ==
                row["externalEnqueueMaxNs"] <= interval_ns and
                0 < row["externalSwapMaxNs"] and
                max(row["externalBindMaxNs"], row["externalSwapMaxNs"]) <=
                row["externalCombinedMaxNs"] <=
                row["externalBindMaxNs"] + row["externalSwapMaxNs"] and
                0 < row["externalCombinedP95Ns"] <=
                row["externalCombinedMaxNs"],
                "app-owned bind/swap critical path accounting is invalid")
        # EGL swap includes queue backpressure, not just execution. Work may
        # start more than one interval before its immutable deadline. Match
        # AppOwnedExternalPresentationEvidence: duration remains reported as
        # capacity telemetry; completion/scan misses and scheduler underruns
        # independently fail above. Never apply this to backend-owned Vulkan.
        require(0 < row["externalGpuMaxNs"] <= source_interval_ns,
                "app-owned RIFE GPU work exceeds its endpoint span")
    else:
        require(row["externalBindMaxNs"] == 0 and
                row["externalSwapMaxNs"] == 0 and
                row["externalGpuBudgetMisses"] == 0,
                "legacy RIFE contains app-owned-only evidence")
        require(0 < row["externalCombinedP95Ns"] <=
                row["externalCombinedMaxNs"] <= budget_ns,
                "record+GPU work exceeds the early physical cutoff")
        require(0 < row["externalEnqueueMaxNs"] <= budget_ns and
                0 < row["externalGpuMaxNs"] <= interval_ns,
                "RIFE enqueue or GPU duration is invalid")
    tolerance_ns = max(MIN_PRESENT_TOLERANCE_NS,
                       round(interval_ns * MAX_PRESENT_ERROR_FRACTION))
    require(0 <= row["externalSlotErrorMaxNs"] <= tolerance_ns,
            "physical scanout missed the desired slot tolerance")
    signed_min = row["externalSlotErrorSignedMinNs"]
    signed_max = row["externalSlotErrorSignedMaxNs"]
    signed_last = row["externalSlotErrorSignedLastNs"]
    require(signed_min <= signed_last <= signed_max and
            row["externalSlotErrorMaxNs"] ==
            max(abs(signed_min), abs(signed_max)),
            "signed physical slot-error evidence is inconsistent")
    clock_period_ns = row["externalPhysicalClockPeriodNs"]
    require(clock_period_ns > 0 and
            abs(clock_period_ns - refresh_ns) <=
            round(refresh_ns * MAX_RATE_ERROR_FRACTION) and
            row["externalPhysicalClockScans"] >= samples - 1,
            "learned physical scan clock is unavailable or inconsistent")
    require(row["externalPhysicalClockCalibrated"] == 1 and
            row["externalPhysicalClockCalibrationPresents"] > 0,
            "physical scan clock lacks an isolated calibration boundary")
    if app_owned:
        require(row["externalPhysicalClockCalibrationPresents"] == samples,
                "app-owned physical clock is not bound to its timing epoch")
    margin_fields = (
        "externalPresentMarginMinNs", "externalPresentMarginP05Ns",
        "externalPresentMarginP50Ns", "externalPresentMarginP95Ns",
        "externalPresentMarginMaxNs", "externalPresentMarginLastNs",
        "externalLateSlotMarginMinNs", "externalLateSlotMarginMaxNs",
    )
    if app_owned:
        require(all(row[field] == 0 for field in margin_fields),
                "app-owned RIFE fabricated unavailable WSI present margins")
    else:
        margin_min = row["externalPresentMarginMinNs"]
        margin_p05 = row["externalPresentMarginP05Ns"]
        margin_p50 = row["externalPresentMarginP50Ns"]
        margin_p95 = row["externalPresentMarginP95Ns"]
        margin_max = row["externalPresentMarginMaxNs"]
        margin_last = row["externalPresentMarginLastNs"]
        require(0 <= margin_min <= margin_p05 <= margin_p50 <=
                margin_p95 <= margin_max and
                margin_min <= margin_last <= margin_max,
                "present-margin distribution is invalid")
        if row["externalLateSlotMisses"] == 0:
            require(row["externalLateSlotMarginMinNs"] == 0 and
                    row["externalLateSlotMarginMaxNs"] == 0,
                    "late-slot margin exists without a late slot")
        else:
            require(margin_min <= row["externalLateSlotMarginMinNs"] <=
                    row["externalLateSlotMarginMaxNs"] <= margin_max,
                    "late-slot present-margin correlation is invalid")
    require(0.0 < row["externalPhaseMin"] <=
            row["externalPhaseMax"] < 1.0,
            "generated timestamp phases are invalid")

    require(row["externalContentNumericPassed"] == 1 and
            row["externalContentEpoch"] == row["schedulerEpoch"],
            "RIFE numeric content proof is unavailable or stale")
    content_proofs = row["externalContentProofs"]
    content_endpoints = row["externalContentEndpoints"]
    content_generated = row["externalContentGenerated"]
    if app_owned:
        require(content_endpoints == 0 and
                content_proofs == content_generated == generated,
                "app-owned generated/content proof conservation failed")
    else:
        require(content_proofs == content_endpoints + content_generated and
                content_proofs == samples and
                content_endpoints == endpoints and
                content_generated == generated,
                "physical/content proof conservation failed")
    require(row["externalContentMovingGenerated"] >= 10 and
            row["externalContentDistinctMovingGenerated"] ==
            row["externalContentMovingGenerated"],
            "moving generated proof duplicated an endpoint")
    require(row["externalContentSceneCutRisk"] == 0 and
            row["externalContentEndpointFailures"] == 0,
            "content proof contains a scene-cut risk or endpoint mismatch")
    require(0 < row["externalContentAnalysisMaxNs"] <= 1_000_000,
            "content-proof CPU analysis exceeded its nonblocking bound")
    for field in (
            "externalContentEndpointMadMaxPpm",
            "externalContentHistogramMaxPpm",
            "externalContentOutputLeftMadMaxPpm",
            "externalContentOutputRightMadMaxPpm"):
        require(0 <= row[field] <= 1_000_000,
                f"content-proof metric is invalid: {field}")
    # Numeric evidence may reject, but acceptance explicitly requires manual
    # moving-video/high-speed inspection.  Until a certified per-path manifest
    # exists, the runtime must remain visibly unqualified.
    require(row["externalContentManualPassed"] == 0 and
            row["physicalQualified"] == 0,
            "numeric evidence incorrectly claimed final visual qualification")

    raw_overlap = 0
    if actual_present_timestamps is not None:
        require(len(actual_present_timestamps) >= 31 and
                all(value > 0 for value in actual_present_timestamps) and
                all(current > previous for previous, current in zip(
                    actual_present_timestamps,
                    actual_present_timestamps[1:])),
                "SurfaceFlinger actual-present timestamps are invalid")
        raw_overlap = sum(timing_start_ns <= value <= timing_end_ns
                          for value in actual_present_timestamps)
        require(raw_overlap >= max(31,
                    int(len(actual_present_timestamps) * 0.25)),
                "RIFE timing window has insufficient raw SurfaceFlinger overlap")

    return {
        "schemaVersion": 1,
        "kind": ("rife-app-owned-timing-only" if app_owned else
                 "rife-integrated-timing-only"),
        "timingPassed": True,
        "numericContentPassed": True,
        "contentQualityPassed": False,
        "qualified": False,
        "qualificationBlockedBy": "moving-game visual/content proof",
        "generator": row["generator"],
        "presentationEpoch": row["schedulerEpoch"],
        "timingWindow": row["externalTimingWindow"],
        "role": row["role"],
        "displayId": row["displayId"],
        "sourceHz": row["source"],
        "targetHz": row["target"],
        "actualPhysicalHz": row["physical"],
        "panelRefreshDurationNs": refresh_ns,
        "scansPerOutput": scans,
        "physicalSamples": samples,
        "timingStartNs": timing_start_ns,
        "timingEndNs": timing_end_ns,
        "surfaceFlingerRawOverlapFrames": raw_overlap,
        "physicalEndpoints": endpoints,
        "physicalGenerated": generated,
        "contentProofs": content_proofs,
        "movingGeneratedProofs": row["externalContentMovingGenerated"],
        "handledUnsafePairs": row["externalUnsafePairs"],
        "combinedP95Ns": row["externalCombinedP95Ns"],
        "combinedMaxNs": row["externalCombinedMaxNs"],
        "deadlineBudgetNs": budget_ns,
        "appOwnedPresentation": app_owned,
    }


def verify_campaign(
        segment_reports: list[dict[str, Any]], *,
        minimum_segments: int = MIN_CAMPAIGN_SEGMENTS,
        minimum_total_span_ns: int = MIN_CAMPAIGN_SPAN_NS,
) -> dict[str, Any]:
    """Verify a long moving-game campaign without crossing segment epochs.

    Each input must already be a complete result from :func:`verify_timing`,
    including its own physical ledger, numeric content proof, and raw
    SurfaceFlinger overlap.  Summing duration is allowed only after every
    independently valid segment is preserved; timestamps, presentation
    counters, and content samples are never merged into a fictional epoch.
    """
    if minimum_segments < 1 or minimum_total_span_ns < MIN_RUNTIME_SPAN_NS:
        raise EvidenceError("RIFE campaign minimum is invalid")
    if len(segment_reports) < minimum_segments:
        raise EvidenceError("RIFE campaign has too few independent segments")

    session_flags = [bool(value.get("captureSession"))
                     for value in segment_reports]
    if any(session_flags) and not all(session_flags):
        raise EvidenceError(
            "RIFE campaign mixes bound and unbound capture sessions")
    session_bound = all(session_flags)
    # A device reboot resets the monotonic clock, and a new app process resets
    # generator IDs.  Archived campaigns therefore order and de-overlap rows
    # *within* each explicitly bound capture session.  The live single-process
    # path retains its original global monotonic ordering.
    ordered = sorted(
        segment_reports,
        key=(lambda value: (str(value.get("captureSession")),
                            int(value.get("timingStartNs", 0))))
        if session_bound else
        (lambda value: int(value.get("timingStartNs", 0))),
    )
    identities: set[tuple[object, ...]] = set()
    total_span_ns = 0
    prior_end_by_session: dict[str, int] = {}
    reference = ordered[0]
    required_identity = ((reference.get("role"), reference.get("displayId"),
                          reference.get("scansPerOutput"))
                         if session_bound else
                         (reference.get("generator"), reference.get("role"),
                          reference.get("displayId"),
                          reference.get("scansPerOutput")))
    for report in ordered:
        if not report.get("timingPassed") or \
                not report.get("numericContentPassed") or \
                not report.get("appOwnedPresentation"):
            raise EvidenceError("RIFE campaign contains an invalid segment")
        if int(report.get("surfaceFlingerRawOverlapFrames", 0)) < 31:
            raise EvidenceError(
                "RIFE campaign segment lacks raw SurfaceFlinger overlap"
            )
        if int(report.get("contentProofs", 0)) <= 0 or \
                int(report.get("movingGeneratedProofs", 0)) <= 0:
            raise EvidenceError(
                "RIFE campaign segment lacks moving generated proof"
            )
        numeric_identity = (int(report.get("generator", 0)),
                            int(report.get("presentationEpoch", 0)),
                            int(report.get("timingWindow", 0)))
        session = str(report.get("captureSession", ""))
        identity = ((session,) + numeric_identity
                    if session_bound else numeric_identity)
        if min(numeric_identity) <= 0 or identity in identities:
            raise EvidenceError("RIFE campaign reused a timing-window identity")
        identities.add(identity)
        stream_identity = ((report.get("role"), report.get("displayId"),
                            report.get("scansPerOutput"))
                           if session_bound else
                           (report.get("generator"), report.get("role"),
                            report.get("displayId"),
                            report.get("scansPerOutput")))
        if stream_identity != required_identity:
            raise EvidenceError("RIFE campaign stream identity changed")
        for field in ("sourceHz", "targetHz", "actualPhysicalHz"):
            value = float(report.get(field, 0.0))
            expected = float(reference.get(field, 0.0))
            if value <= 0.0 or expected <= 0.0 or \
                    abs(value - expected) > expected * MAX_RATE_ERROR_FRACTION:
                raise EvidenceError("RIFE campaign cadence identity changed")
        start_ns = int(report.get("timingStartNs", 0))
        end_ns = int(report.get("timingEndNs", 0))
        span_ns = end_ns - start_ns
        prior_end_ns = prior_end_by_session.get(session, 0)
        if start_ns <= prior_end_ns or span_ns < MIN_RUNTIME_SPAN_NS:
            raise EvidenceError("RIFE campaign segment overlaps or is too short")
        prior_end_by_session[session] = end_ns
        total_span_ns += span_ns
    if total_span_ns < minimum_total_span_ns:
        raise EvidenceError("RIFE campaign moving-game span is too short")

    return {
        "schemaVersion": 1,
        "kind": "rife-app-owned-long-moving-game-campaign",
        "timingPassed": True,
        "numericContentPassed": True,
        "contentQualityPassed": False,
        "qualified": False,
        "qualificationBlockedBy": "moving-game visual/content proof",
        "generator": int(reference["generator"]),
        "role": reference["role"],
        "displayId": int(reference["displayId"]),
        "sourceHz": float(reference["sourceHz"]),
        "targetHz": float(reference["targetHz"]),
        "scansPerOutput": int(reference["scansPerOutput"]),
        "segmentCount": len(ordered),
        "captureSessionCount": (len(prior_end_by_session)
                                if session_bound else 1),
        "totalMovingSpanNs": total_span_ns,
        "physicalSamples": sum(int(value["physicalSamples"])
                               for value in ordered),
        "physicalEndpoints": sum(int(value["physicalEndpoints"])
                                 for value in ordered),
        "physicalGenerated": sum(int(value["physicalGenerated"])
                                 for value in ordered),
        "contentProofs": sum(int(value["contentProofs"])
                            for value in ordered),
        "movingGeneratedProofs": sum(int(value["movingGeneratedProofs"])
                                    for value in ordered),
        "segments": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify_timing(args.log.read_text(
            encoding="utf-8", errors="replace"))
    except (OSError, EvidenceError) as error:
        print(json.dumps({"timingPassed": False, "error": str(error)},
                         sort_keys=True))
        return 1
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
