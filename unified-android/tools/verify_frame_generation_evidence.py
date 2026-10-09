#!/usr/bin/env python3
"""Fail-closed verifier for real EmuFusion frame-generation evidence.

This deliberately joins two independent sources: application framebuffer
provenance (motion vectors and pixel hashes) and Android SurfaceFlinger latch
timestamps. Neither an FPS badge nor Choreographer callback counts can pass it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


PROOF_CONTRACT = "native-pixel-refined-regional-flow-v22-x2-presented"
PROOF_SCHEMA_VERSION = 22
DENSE_PROOF_CONTRACT = "dense-pyramid-timer-v26-raw-ns-qualification-x2-presented"
DENSE_PROOF_SCHEMA_VERSION = 26
DENSE_V27_PROOF_CONTRACT = "dense-fragment-192x108-v27-qualification-x2-presented"
DENSE_V27_PROOF_SCHEMA_VERSION = 27
DENSE_V28_V32_PROOF_CONTRACT = "dense-fragment-160x90-v32-async-proof-atlas-qualification-x2-presented"
DENSE_V28_V32_PROOF_SCHEMA_VERSION = 32
DENSE_V28_PROOF_CONTRACT = "dense-fragment-160x90-v33-pair-quota-scheduler-qualification-x2-presented"
DENSE_V28_PROOF_SCHEMA_VERSION = 33
DENSE_V34_PROOF_CONTRACT = "dense-fragment-160x90-v34-diagnostic-funnel-qualification-x2-presented"
DENSE_V34_PROOF_SCHEMA_VERSION = 34
DENSE_V35_PROOF_CONTRACT = "dense-fragment-160x90-v35-packed-mask-qualification-x2-presented"
DENSE_V35_PROOF_SCHEMA_VERSION = 35
DENSE_V36_PROOF_CONTRACT = "dense-fragment-160x90-v36-epoch-bound-packed-mask-qualification-x2-presented"
DENSE_V36_PROOF_SCHEMA_VERSION = 36
DENSE_V37_PROOF_CONTRACT = "dense-fragment-128x72-v37-timestamp-resample-qualification-x2-presented"
DENSE_V37_PROOF_SCHEMA_VERSION = 37
DENSE_V38_PROOF_CONTRACT = "dense-fragment-128x72-v38-vector-trajectory-qualification-x2-presented"
DENSE_V38_PROOF_SCHEMA_VERSION = 38
DENSE_V39_PROOF_CONTRACT = "dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented"
DENSE_V39_PROOF_SCHEMA_VERSION = 39
DENSE_V40_PROOF_CONTRACT = "dense-fragment-128x72-v40-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented"
DENSE_V40_PROOF_SCHEMA_VERSION = 40
DENSE_V41_PROOF_CONTRACT = "dense-fragment-128x72-v41-strict-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented"
DENSE_V41_PROOF_SCHEMA_VERSION = 41
DENSE_V42_PROOF_CONTRACT = "dense-fragment-128x72-v42-uniform-timestamp-resample-strict-flow-qualification-max2x-presented"
DENSE_V42_PROOF_SCHEMA_VERSION = 42
DENSE_V43_PROOF_CONTRACT = "dense-fragment-128x72-v43-rational-source-panel-clock-strict-flow-qualification-max2x-presented"
DENSE_V43_PROOF_SCHEMA_VERSION = 43
DENSE_V44_PROOF_CONTRACT = "dense-fragment-128x72-v44-unique-endpoint-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V44_PROOF_SCHEMA_VERSION = 44
DENSE_V45_PROOF_CONTRACT = "dense-fragment-128x72-v45-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V45_PROOF_SCHEMA_VERSION = 45
DENSE_V46_PROOF_CONTRACT = "dense-fragment-128x72-v46-independent-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V46_PROOF_SCHEMA_VERSION = 46
DENSE_V47_PROOF_CONTRACT = "dense-fragment-128x72-v47-stamped-pts-loss-bound-independent-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V47_PROOF_SCHEMA_VERSION = 47
DENSE_V48_PROOF_CONTRACT = "dense-fragment-128x72-v48-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V48_PROOF_SCHEMA_VERSION = 48
DENSE_V49_PROOF_CONTRACT = "dense-fragment-128x72-v49-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V49_PROOF_SCHEMA_VERSION = 49
DENSE_V50_PROOF_CONTRACT = "dense-fragment-128x72-v50-iterated-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V50_PROOF_SCHEMA_VERSION = 50
DENSE_V51_PROOF_CONTRACT = "dense-fragment-128x72-v51-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V51_PROOF_SCHEMA_VERSION = 51
DENSE_V54_PROOF_CONTRACT = "dense-fragment-128x72-v54-cycle-aware-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V54_PROOF_SCHEMA_VERSION = 54
DENSE_V55_PROOF_CONTRACT = "dense-fragment-128x72-v55-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V55_PROOF_SCHEMA_VERSION = 55
DENSE_V56_PROOF_CONTRACT = "dense-fragment-128x72-v56-strong-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow-qualification-max2x-presented"
DENSE_V56_PROOF_SCHEMA_VERSION = 56
DENSE_V57_PROOF_CONTRACT = "dense-v57-joint-cycle-rational-max2x-presented"
DENSE_V57_PROOF_SCHEMA_VERSION = 57
DENSE_V58_PROOF_CONTRACT = "dense-v58-joint-cycle-rational-max2x-presented"
DENSE_V58_PROOF_SCHEMA_VERSION = 58
DENSE_V59_PROOF_CONTRACT = "dense-v59-edge-aware-neighbor-rational-max2x-presented"
DENSE_V59_PROOF_SCHEMA_VERSION = 59
DENSE_V60_PROOF_CONTRACT = "dense-v60-independent-global-seed-rational-max2x-presented"
DENSE_V60_PROOF_SCHEMA_VERSION = 60
DENSE_V61_PROOF_CONTRACT = "dense-v61-parallel-global-seed-rational-max2x-presented"
DENSE_V61_PROOF_SCHEMA_VERSION = 61
# v62: tier protocol 2026-09-01.  Tiers {60, 40, 30, 20} on 120 Hz (50 is
# demoted to 40), {60, 30, 20} on 60 Hz; generation factor is an integer
# and at most 3 (20->60, 40->120 triple; 30->60, 60->120 double).
DENSE_V62_PROOF_CONTRACT = "dense-v62-parallel-global-seed-rational-tiered-max3x-presented"
DENSE_V62_PROOF_SCHEMA_VERSION = 62
MAX_GENERATION_FACTOR_V62 = 3
DENSE_PROOF_CELLS = 48 * 27
REGIONAL_FLOW_CELLS = 96
V37_MAX_RETAINED_ENDPOINTS = 8  # active pair plus six-entry FIFO (2026-09-02)
RESET_COUNTER_FIELDS = (
    "active", "confident", "proof", "synthetic", "distinct", "changing",
    "eligible_pixels", "substantive_pixels", "non_crossfade_pixels",
    "motion_eligible_samples", "correlated_samples", "motion_eligible_pixels",
    "motion_synthesized_pixels",
)
V34_RESET_COUNTER_FIELDS = (
    "dense_diagnostic_cells", "dense_diagnostic_tiles",
    "dense_diagnostic_mask_errors",
    "dense_diagnostic_last_atlas_sequence",
    "dense_diagnostic_last_pair_sequence",
    "dense_diagnostic_last_previous_endpoint",
    "dense_diagnostic_last_current_endpoint",
    "dense_backward_active", "dense_backward_in_bounds",
    "dense_backward_cycle_valid", "dense_backward_photometric_valid",
    "dense_backward_texture_valid", "dense_backward_saturated",
    "dense_backward_out_of_bounds", "dense_backward_covered_tiles",
    "dense_backward_covered_tile_mask",
    "dense_forward_active", "dense_forward_in_bounds",
    "dense_forward_cycle_valid", "dense_forward_photometric_valid",
    "dense_forward_texture_valid", "dense_forward_saturated",
    "dense_forward_out_of_bounds", "dense_forward_covered_tiles",
    "dense_forward_covered_tile_mask",
)
V35_RESET_COUNTER_FIELDS = V34_RESET_COUNTER_FIELDS + (
    "dense_diagnostic_packed_cells",
    "dense_diagnostic_partition_errors",
    "dense_diagnostic_reserved_bit_errors",
)
V36_RESET_COUNTER_FIELDS = V35_RESET_COUNTER_FIELDS + (
    "proof_evidence_enqueued_in_epoch", "proof_evidence_accepted",
    "proof_evidence_excluded", "proof_evidence_last_accepted_atlas_sequence",
)
V37_RESET_COUNTER_FIELDS = V36_RESET_COUNTER_FIELDS + (
    "dense_diagnostic_last_target_source_ns",
)
V38_RESET_COUNTER_FIELDS = V37_RESET_COUNTER_FIELDS
V39_RESET_COUNTER_FIELDS = V38_RESET_COUNTER_FIELDS
V40_RESET_COUNTER_FIELDS = V39_RESET_COUNTER_FIELDS
V41_RESET_COUNTER_FIELDS = V40_RESET_COUNTER_FIELDS
V42_RESET_COUNTER_FIELDS = V41_RESET_COUNTER_FIELDS
V43_RESET_COUNTER_FIELDS = V42_RESET_COUNTER_FIELDS
V44_RESET_COUNTER_FIELDS = V43_RESET_COUNTER_FIELDS
V45_RESET_COUNTER_FIELDS = V44_RESET_COUNTER_FIELDS
V46_RESET_COUNTER_FIELDS = V45_RESET_COUNTER_FIELDS
V47_RESET_COUNTER_FIELDS = V46_RESET_COUNTER_FIELDS
V48_RESET_COUNTER_FIELDS = V47_RESET_COUNTER_FIELDS
V49_RESET_COUNTER_FIELDS = V48_RESET_COUNTER_FIELDS
V50_RESET_COUNTER_FIELDS = V49_RESET_COUNTER_FIELDS
V51_RESET_COUNTER_FIELDS = V50_RESET_COUNTER_FIELDS
V54_RESET_COUNTER_FIELDS = V51_RESET_COUNTER_FIELDS
V55_RESET_COUNTER_FIELDS = V54_RESET_COUNTER_FIELDS
V56_RESET_COUNTER_FIELDS = V55_RESET_COUNTER_FIELDS
V57_RESET_COUNTER_FIELDS = V56_RESET_COUNTER_FIELDS
V58_RESET_COUNTER_FIELDS = V57_RESET_COUNTER_FIELDS
V59_RESET_COUNTER_FIELDS = V58_RESET_COUNTER_FIELDS
V60_RESET_COUNTER_FIELDS = V59_RESET_COUNTER_FIELDS
V61_RESET_COUNTER_FIELDS = V60_RESET_COUNTER_FIELDS
V62_RESET_COUNTER_FIELDS = V61_RESET_COUNTER_FIELDS

HEALTH = re.compile(
    r"Presentation health generator=(?P<generator>\d+) "
    r"role=(?P<role>[a-z0-9_-]+) displayId=(?P<display_id>-?\d+) "
    r"proofContract=(?P<proof_contract>[a-z0-9_-]+) "
    r"proofSchemaVersion=(?P<proof_schema_version>\d+) "
    r"presents=(?P<presents>\d+) generated=(?P<generated>\d+) "
    r"real=(?P<real>\d+) promoted=(?P<promoted>\d+) "
    r"submitted=(?P<submitted>\d+) .*?"
    r"lockedFps=(?P<locked>\d+) outputFps=(?P<output>\d+) "
    r"panelFps=(?P<panel>\d+) "
    r"latticeRegionSamples=(?P<lattice_samples>\d+) "
    r"latticeBackwardCoherentRegions=(?P<lattice_backward_coherent>\d+) "
    r"latticeForwardCoherentRegions=(?P<lattice_forward_coherent>\d+) "
    r"latticeBackwardBoundaryRegions=(?P<lattice_backward_boundary>\d+) "
    r"latticeForwardBoundaryRegions=(?P<lattice_forward_boundary>\d+) "
    r"latticeBackwardCoherentBoundaryRegions=(?P<lattice_backward_coherent_boundary>\d+) "
    r"latticeForwardCoherentBoundaryRegions=(?P<lattice_forward_coherent_boundary>\d+) "
    r"latticeBackwardCoherentRegionCount=(?P<lattice_backward_count>\d+) "
    r"latticeForwardCoherentRegionCount=(?P<lattice_forward_count>\d+) "
    r"latticeBackwardBoundaryRegionCount=(?P<lattice_backward_boundary_count>\d+) "
    r"latticeForwardBoundaryRegionCount=(?P<lattice_forward_boundary_count>\d+) "
    r"latticeBackwardCoherentBoundaryRegionCount=(?P<lattice_backward_coherent_boundary_count>\d+) "
    r"latticeForwardCoherentBoundaryRegionCount=(?P<lattice_forward_coherent_boundary_count>\d+) "
    r"latticeBackwardPeakSupport=(?P<lattice_backward_peak_support>\d+) "
    r"latticeForwardPeakSupport=(?P<lattice_forward_peak_support>\d+) "
    r"regionalFlowRegionSamples=(?P<regional_samples>\d+) "
    r"regionalBackwardSupportedRegions=(?P<regional_backward_supported>\d+) "
    r"regionalForwardSupportedRegions=(?P<regional_forward_supported>\d+) "
    r"regionalBackwardNeighborRegions=(?P<regional_backward_neighbor>\d+) "
    r"regionalForwardNeighborRegions=(?P<regional_forward_neighbor>\d+) "
    r"regionalBackwardConstantNeighborRegions=(?P<regional_backward_constant_neighbor>\d+) "
    r"regionalForwardConstantNeighborRegions=(?P<regional_forward_constant_neighbor>\d+) "
    r"regionalBackwardGradientNeighborRegions=(?P<regional_backward_gradient_neighbor>\d+) "
    r"regionalForwardGradientNeighborRegions=(?P<regional_forward_gradient_neighbor>\d+) "
    r"regionalBackwardAcceptedRegions=(?P<regional_backward_accepted>\d+) "
    r"regionalForwardAcceptedRegions=(?P<regional_forward_accepted>\d+) "
    r"regionalBackwardAcceptedBoundaryRegions=(?P<regional_backward_accepted_boundary>\d+) "
    r"regionalForwardAcceptedBoundaryRegions=(?P<regional_forward_accepted_boundary>\d+) "
    r"regionalBackwardCycleAcceptedRegions=(?P<regional_backward_cycle>\d+) "
    r"regionalForwardCycleAcceptedRegions=(?P<regional_forward_cycle>\d+) "
    r"regionalBackwardAcceptedRegionCount=(?P<regional_backward_count>\d+) "
    r"regionalForwardAcceptedRegionCount=(?P<regional_forward_count>\d+) "
    r"regionalBackwardAcceptedBoundaryRegionCount=(?P<regional_backward_accepted_boundary_count>\d+) "
    r"regionalForwardAcceptedBoundaryRegionCount=(?P<regional_forward_accepted_boundary_count>\d+) "
    r"regionalBackwardCycleAcceptedRegionCount=(?P<regional_backward_cycle_count>\d+) "
    r"regionalForwardCycleAcceptedRegionCount=(?P<regional_forward_cycle_count>\d+) "
    r"regionalBackwardSupportedRegionCount=(?P<regional_backward_supported_count>\d+) "
    r"regionalForwardSupportedRegionCount=(?P<regional_forward_supported_count>\d+) "
    r"regionalBackwardNeighborRegionCount=(?P<regional_backward_neighbor_count>\d+) "
    r"regionalForwardNeighborRegionCount=(?P<regional_forward_neighbor_count>\d+) "
    r"regionalBackwardConstantNeighborRegionCount=(?P<regional_backward_constant_neighbor_count>\d+) "
    r"regionalForwardConstantNeighborRegionCount=(?P<regional_forward_constant_neighbor_count>\d+) "
    r"regionalBackwardGradientNeighborRegionCount=(?P<regional_backward_gradient_neighbor_count>\d+) "
    r"regionalForwardGradientNeighborRegionCount=(?P<regional_forward_gradient_neighbor_count>\d+) "
    r"regionalBackwardPeakSupport=(?P<regional_backward_support>\d+) "
    r"regionalForwardPeakSupport=(?P<regional_forward_support>\d+) "
    r"regionalBackwardPeakConfidence=(?P<regional_backward_confidence>\d+) "
    r"regionalForwardPeakConfidence=(?P<regional_forward_confidence>\d+) "
    r"activeMotionVectors=(?P<active>\d+) "
    r"confidentMotionVectors=(?P<confident>\d+) "
    r"motionVectorCells=(?P<cells>\d+) proofSamples=(?P<proof>\d+) "
    r"syntheticProofSamples=(?P<synthetic>\d+) "
    r"syntheticDistinctFromEndpoints=(?P<distinct>\d+) "
    r"changingProofOutputs=(?P<changing>\d+) "
    r"eligibleSyntheticPixels=(?P<eligible_pixels>\d+) "
    r"substantiveSyntheticPixels=(?P<substantive_pixels>\d+) "
    r"nonCrossfadeSyntheticPixels=(?P<non_crossfade_pixels>\d+) "
    r"motionEligibleProofSamples=(?P<motion_eligible_samples>\d+) "
    r"motionCorrelatedProofSamples=(?P<correlated_samples>\d+) "
    r"v21DirectionallyEligibleSyntheticPixels=(?P<motion_eligible_pixels>\d+) "
    r"v21CorrectVectorPredictedSyntheticPixels=(?P<motion_synthesized_pixels>\d+) "
    r"(?:denseEnabled=(?P<dense_enabled>\d+) "
    r"densePromotions=(?P<dense_promotions>\d+) "
    r"densePasses=(?P<dense_passes>\d+) "
    r"denseCpuSubmitTotalUs=(?P<dense_submit_total_us>\d+) "
    r"denseCpuSubmitMaxUs=(?P<dense_submit_max_us>\d+) "
    r"denseCpuSubmitLastUs=(?P<dense_submit_last_us>\d+) "
    r"denseGpuCompleteTotalUs=(?P<dense_gpu_total_us>\d+) "
    r"denseGpuCompleteMaxUs=(?P<dense_gpu_max_us>\d+) "
    r"denseGpuCompleteLastUs=(?P<dense_gpu_last_us>\d+) "
    r"denseGpuBudgetUs=(?P<dense_gpu_budget_us>\d+) "
    r"denseTimedPairs=(?P<dense_timed_pairs>\d+) "
    r"denseWarpSequence=(?P<dense_warp_sequence>\d+) "
    r"denseWarpMaxCompletedSequence=(?P<dense_warp_completed_sequence>\d+) "
    r"denseTimerPending=(?P<dense_timer_pending>\d+) "
    r"denseTimerDisjoint=(?P<dense_timer_disjoint>\d+) "
    r"denseTimerUnavailable=(?P<dense_timer_unavailable>\d+) "
    r"denseTimerStale=(?P<dense_timer_stale>\d+) "
    r"denseTimerMaxQueueAge=(?P<dense_timer_max_queue_age>\d+) "
    r"densePerformanceRejected=(?P<dense_performance_rejected>\d+) "
    r"denseCalibrationRuns=(?P<dense_calibration_runs>\d+) "
    r"denseCalibrationUs=(?P<dense_calibration_us>\d+) "
    r"(?:denseCombinedPairMaxWarpP95Us=(?P<dense_combined_pair_warp_us>\d+) "
    r"densePromotionWallSamples=(?P<dense_promotion_wall_samples>\d+) "
    r"densePromotionWallTotalUs=(?P<dense_promotion_wall_total_us>\d+) "
    r"densePromotionWallP95Us=(?P<dense_promotion_wall_p95_us>\d+) "
    r"densePromotionWallMaxUs=(?P<dense_promotion_wall_max_us>\d+) "
    r"denseSignatureWallSamples=(?P<dense_signature_wall_samples>\d+) "
    r"denseSignatureWallTotalUs=(?P<dense_signature_wall_total_us>\d+) "
    r"denseSignatureWallP95Us=(?P<dense_signature_wall_p95_us>\d+) "
    r"denseSignatureWallMaxUs=(?P<dense_signature_wall_max_us>\d+) "
    r"denseProofWallSamples=(?P<dense_proof_wall_samples>\d+) "
    r"denseProofWallTotalUs=(?P<dense_proof_wall_total_us>\d+) "
    r"denseProofWallP95Us=(?P<dense_proof_wall_p95_us>\d+) "
    r"denseProofWallMaxUs=(?P<dense_proof_wall_max_us>\d+) )?"
    r"(?:denseSignatureSequence=(?P<dense_signature_sequence>\d+) "
    r"denseSignatureReady=(?P<dense_signature_ready>\d+) "
    r"denseSignatureUnavailable=(?P<dense_signature_unavailable>\d+) "
    r"denseSignatureMaxQueueAge=(?P<dense_signature_max_queue_age>\d+) "
    r"denseSignaturePending=(?P<dense_signature_pending>\d+) )?"
    r"(?:denseSignatureCapability=(?P<dense_signature_capability>\d+) "
    r"denseSignatureRequestedGles=(?P<dense_signature_requested_gles>\d+) "
    r"denseSignatureActualGlesMajor=(?P<dense_signature_actual_gles_major>\d+) "
    r"denseSignatureActualGlesMinor=(?P<dense_signature_actual_gles_minor>\d+) "
    r"denseSignatureSelfTests=(?P<dense_signature_self_tests>\d+) )?"
    r"denseRuntimeCadenceSource=app-present-window "
    r"denseOfflineCadenceSource=surfaceflinger-layer-timestamps "
    r"(?:denseVariant=(?P<dense_variant>[a-z0-9-]+) "
    r"denseAnalysisWidth=(?P<dense_analysis_width>\d+) "
    r"denseAnalysisHeight=(?P<dense_analysis_height>\d+) "
    r"denseSolveTexelsPerPromotion=(?P<dense_solve_texels>\d+) "
    r"denseTotalTexelsPerPromotion=(?P<dense_total_texels>\d+) )?"
    r"denseCopySamples=(?P<dense_copy_samples>\d+) denseCopyTotalUs=(?P<dense_copy_total_us>\d+) denseCopyP95Us=(?P<dense_copy_p95_us>\d+) denseCopyMaxUs=(?P<dense_copy_max_us>\d+) "
    r"densePyramidSamples=(?P<dense_pyramid_samples>\d+) densePyramidTotalUs=(?P<dense_pyramid_total_us>\d+) densePyramidP95Us=(?P<dense_pyramid_p95_us>\d+) densePyramidMaxUs=(?P<dense_pyramid_max_us>\d+) "
    r"denseForwardSamples=(?P<dense_forward_samples>\d+) denseForwardTotalUs=(?P<dense_forward_total_us>\d+) denseForwardP95Us=(?P<dense_forward_p95_us>\d+) denseForwardMaxUs=(?P<dense_forward_max_us>\d+) "
    r"denseReverseSamples=(?P<dense_reverse_samples>\d+) denseReverseTotalUs=(?P<dense_reverse_total_us>\d+) denseReverseP95Us=(?P<dense_reverse_p95_us>\d+) denseReverseMaxUs=(?P<dense_reverse_max_us>\d+) "
    r"denseValidationSamples=(?P<dense_validation_samples>\d+) denseValidationTotalUs=(?P<dense_validation_total_us>\d+) denseValidationP95Us=(?P<dense_validation_p95_us>\d+) denseValidationMaxUs=(?P<dense_validation_max_us>\d+) "
    r"denseWarpSamples=(?P<dense_warp_samples>\d+) denseWarpTotalUs=(?P<dense_warp_total_us>\d+) denseWarpP95Us=(?P<dense_warp_p95_us>\d+) denseWarpMaxUs=(?P<dense_warp_max_us>\d+) "
    r"denseMaxFlowPixels=(?P<dense_max_flow_pixels>\d+) "
    r"denseProofCells=(?P<dense_proof_cells>\d+) "
    r"denseBackwardValidCells=(?P<dense_backward_valid>\d+) "
    r"denseForwardValidCells=(?P<dense_forward_valid>\d+) )?"
    r"windowElapsedMs=(?P<window_ms>\d+) "
    r"windowStartNs=(?P<window_start_ns>\d+) "
    r"windowEndNs=(?P<window_end_ns>\d+) "
    r"windowPresents=(?P<window_presents>\d+) "
    r"windowGenerated=(?P<window_generated>\d+) "
    r"windowPromoted=(?P<window_promoted>\d+)"
)

# Schema 32 transports each logical HEALTH snapshot as two bounded logcat
# records.  The common identity is intentionally repeated so the verifier can
# fail closed on truncation, loss, duplication, reordering, or cross-generator
# joins instead of trusting line adjacency alone.
HEALTH_BASE_V33 = re.compile(
    r"Presentation health base generator=(?P<generator>\d+) "
    r"role=(?P<role>[a-z0-9_-]+) displayId=(?P<display_id>-?\d+) "
    r"proofContract=(?P<proof_contract>[a-z0-9_-]+) "
    r"proofSchemaVersion=(?P<proof_schema_version>33) "
    r"healthSequence=(?P<health_sequence>\d+) presents=(?P<presents>\d+) "
    r"windowStartNs=(?P<window_start_ns>\d+) "
    r"windowEndNs=(?P<window_end_ns>\d+) "
    r"windowElapsedMs=(?P<window_ms>\d+) "
    r"windowPresents=(?P<window_presents>\d+) "
    r"windowGenerated=(?P<window_generated>\d+) "
    r"windowPromoted=(?P<window_promoted>\d+) "
    r"windowDueSelected=(?P<window_due_selected>\d+) "
    r"windowDueNoEndpoint=(?P<window_due_no_endpoint>\d+) "
    r"windowDuePhaseClamped=(?P<window_due_phase_clamped>\d+) "
    r"windowRealPriority=(?P<window_real_priority>\d+) "
    r"windowSyntheticQuotaSkipped=(?P<window_synthetic_quota_skipped>\d+) "
    r"windowPresentationEpoch=(?P<window_presentation_epoch>\d+) "
    r"windowSyntheticQuotaOpening=(?P<window_synthetic_quota_opening>\d+) "
    r"syntheticQuotaPending=(?P<synthetic_quota_pending>\d+) "
    r"windowSyntheticSelected=(?P<window_synthetic_selected>\d+) "
    r"windowSyntheticPairCreated=(?P<window_synthetic_pair_created>\d+) "
    r"windowSyntheticNotReady=(?P<window_synthetic_not_ready>\d+) "
    r"windowDuplicatePairSelection=(?P<window_duplicate_pair_selection>\d+) "
    r"lastSelectedSyntheticPair=(?P<last_selected_synthetic_pair>\d+) "
    r"denseExtensionRequired=(?P<dense_extension_required>1) "
    r"generated=(?P<generated>\d+) real=(?P<real>\d+) "
    r"promoted=(?P<promoted>\d+) submitted=(?P<submitted>\d+) .*?"
    r"lockedFps=(?P<locked>\d+) outputFps=(?P<output>\d+) "
    r"panelFps=(?P<panel>\d+) "
    r"latticeRegionSamples=(?P<lattice_samples>\d+) "
    r"latticeBackwardCoherentRegions=(?P<lattice_backward_coherent>\d+) "
    r"latticeForwardCoherentRegions=(?P<lattice_forward_coherent>\d+) "
    r"latticeBackwardBoundaryRegions=(?P<lattice_backward_boundary>\d+) "
    r"latticeForwardBoundaryRegions=(?P<lattice_forward_boundary>\d+) "
    r"latticeBackwardCoherentBoundaryRegions=(?P<lattice_backward_coherent_boundary>\d+) "
    r"latticeForwardCoherentBoundaryRegions=(?P<lattice_forward_coherent_boundary>\d+) "
    r"latticeBackwardCoherentRegionCount=(?P<lattice_backward_count>\d+) "
    r"latticeForwardCoherentRegionCount=(?P<lattice_forward_count>\d+) "
    r"latticeBackwardBoundaryRegionCount=(?P<lattice_backward_boundary_count>\d+) "
    r"latticeForwardBoundaryRegionCount=(?P<lattice_forward_boundary_count>\d+) "
    r"latticeBackwardCoherentBoundaryRegionCount=(?P<lattice_backward_coherent_boundary_count>\d+) "
    r"latticeForwardCoherentBoundaryRegionCount=(?P<lattice_forward_coherent_boundary_count>\d+) "
    r"latticeBackwardPeakSupport=(?P<lattice_backward_peak_support>\d+) "
    r"latticeForwardPeakSupport=(?P<lattice_forward_peak_support>\d+) "
    r"regionalFlowRegionSamples=(?P<regional_samples>\d+) "
    r"regionalBackwardSupportedRegions=(?P<regional_backward_supported>\d+) "
    r"regionalForwardSupportedRegions=(?P<regional_forward_supported>\d+) "
    r"regionalBackwardNeighborRegions=(?P<regional_backward_neighbor>\d+) "
    r"regionalForwardNeighborRegions=(?P<regional_forward_neighbor>\d+) "
    r"regionalBackwardConstantNeighborRegions=(?P<regional_backward_constant_neighbor>\d+) "
    r"regionalForwardConstantNeighborRegions=(?P<regional_forward_constant_neighbor>\d+) "
    r"regionalBackwardGradientNeighborRegions=(?P<regional_backward_gradient_neighbor>\d+) "
    r"regionalForwardGradientNeighborRegions=(?P<regional_forward_gradient_neighbor>\d+) "
    r"regionalBackwardAcceptedRegions=(?P<regional_backward_accepted>\d+) "
    r"regionalForwardAcceptedRegions=(?P<regional_forward_accepted>\d+) "
    r"regionalBackwardAcceptedBoundaryRegions=(?P<regional_backward_accepted_boundary>\d+) "
    r"regionalForwardAcceptedBoundaryRegions=(?P<regional_forward_accepted_boundary>\d+) "
    r"regionalBackwardCycleAcceptedRegions=(?P<regional_backward_cycle>\d+) "
    r"regionalForwardCycleAcceptedRegions=(?P<regional_forward_cycle>\d+) "
    r"regionalBackwardAcceptedRegionCount=(?P<regional_backward_count>\d+) "
    r"regionalForwardAcceptedRegionCount=(?P<regional_forward_count>\d+) "
    r"regionalBackwardAcceptedBoundaryRegionCount=(?P<regional_backward_accepted_boundary_count>\d+) "
    r"regionalForwardAcceptedBoundaryRegionCount=(?P<regional_forward_accepted_boundary_count>\d+) "
    r"regionalBackwardCycleAcceptedRegionCount=(?P<regional_backward_cycle_count>\d+) "
    r"regionalForwardCycleAcceptedRegionCount=(?P<regional_forward_cycle_count>\d+) "
    r"regionalBackwardSupportedRegionCount=(?P<regional_backward_supported_count>\d+) "
    r"regionalForwardSupportedRegionCount=(?P<regional_forward_supported_count>\d+) "
    r"regionalBackwardNeighborRegionCount=(?P<regional_backward_neighbor_count>\d+) "
    r"regionalForwardNeighborRegionCount=(?P<regional_forward_neighbor_count>\d+) "
    r"regionalBackwardConstantNeighborRegionCount=(?P<regional_backward_constant_neighbor_count>\d+) "
    r"regionalForwardConstantNeighborRegionCount=(?P<regional_forward_constant_neighbor_count>\d+) "
    r"regionalBackwardGradientNeighborRegionCount=(?P<regional_backward_gradient_neighbor_count>\d+) "
    r"regionalForwardGradientNeighborRegionCount=(?P<regional_forward_gradient_neighbor_count>\d+) "
    r"regionalBackwardPeakSupport=(?P<regional_backward_support>\d+) "
    r"regionalForwardPeakSupport=(?P<regional_forward_support>\d+) "
    r"regionalBackwardPeakConfidence=(?P<regional_backward_confidence>\d+) "
    r"regionalForwardPeakConfidence=(?P<regional_forward_confidence>\d+) "
    r"activeMotionVectors=(?P<active>\d+) confidentMotionVectors=(?P<confident>\d+) "
    r"motionVectorCells=(?P<cells>\d+) proofSamples=(?P<proof>\d+) "
    r"syntheticProofSamples=(?P<synthetic>\d+) "
    r"syntheticDistinctFromEndpoints=(?P<distinct>\d+) "
    r"changingProofOutputs=(?P<changing>\d+) "
    r"eligibleSyntheticPixels=(?P<eligible_pixels>\d+) "
    r"substantiveSyntheticPixels=(?P<substantive_pixels>\d+) "
    r"nonCrossfadeSyntheticPixels=(?P<non_crossfade_pixels>\d+) "
    r"motionEligibleProofSamples=(?P<motion_eligible_samples>\d+) "
    r"motionCorrelatedProofSamples=(?P<correlated_samples>\d+) "
    r"v21DirectionallyEligibleSyntheticPixels=(?P<motion_eligible_pixels>\d+) "
    r"v21CorrectVectorPredictedSyntheticPixels=(?P<motion_synthesized_pixels>\d+)"
)

# Preserve schema-32 replay exactly. New scheduler counters are deliberately
# not optional inside schema 33: a producer that claims the new contract but
# omits them cannot fall through as an older record.
HEALTH_BASE = re.compile(
    HEALTH_BASE_V33.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>33) ",
             "proofSchemaVersion=(?P<proof_schema_version>32) ")
    .replace(r"windowDueSelected=(?P<window_due_selected>\d+) ", "")
    .replace(r"windowDueNoEndpoint=(?P<window_due_no_endpoint>\d+) ", "")
    .replace(r"windowDuePhaseClamped=(?P<window_due_phase_clamped>\d+) ", "")
    .replace(r"windowRealPriority=(?P<window_real_priority>\d+) ", "")
    .replace(r"windowSyntheticQuotaSkipped=(?P<window_synthetic_quota_skipped>\d+) ", "")
    .replace(r"windowPresentationEpoch=(?P<window_presentation_epoch>\d+) ", "")
    .replace(r"windowSyntheticQuotaOpening=(?P<window_synthetic_quota_opening>\d+) ", "")
    .replace(r"syntheticQuotaPending=(?P<synthetic_quota_pending>\d+) ", "")
    .replace(r"windowSyntheticSelected=(?P<window_synthetic_selected>\d+) ", "")
    .replace(r"windowSyntheticPairCreated=(?P<window_synthetic_pair_created>\d+) ", "")
    .replace(r"windowSyntheticNotReady=(?P<window_synthetic_not_ready>\d+) ", "")
    .replace(r"windowDuplicatePairSelection=(?P<window_duplicate_pair_selection>\d+) ", "")
    .replace(r"lastSelectedSyntheticPair=(?P<last_selected_synthetic_pair>\d+) ", "")
)

_V34_DIRECTION_DIAGNOSTICS = (
    r" denseBackwardActiveCells=(?P<dense_backward_active>\d+)"
    r" denseBackwardInBoundsCells=(?P<dense_backward_in_bounds>\d+)"
    r" denseBackwardCycleValidCells=(?P<dense_backward_cycle_valid>\d+)"
    r" denseBackwardPhotometricValidCells=(?P<dense_backward_photometric_valid>\d+)"
    r" denseBackwardTextureValidCells=(?P<dense_backward_texture_valid>\d+)"
    r" denseBackwardSaturatedCells=(?P<dense_backward_saturated>\d+)"
    r" denseBackwardOutOfBoundsCells=(?P<dense_backward_out_of_bounds>\d+)"
    r" denseBackwardCoveredTiles=(?P<dense_backward_covered_tiles>\d+)"
    r" denseBackwardCoveredTileMask=(?P<dense_backward_covered_tile_mask>\d+)"
    r" denseForwardActiveCells=(?P<dense_forward_active>\d+)"
    r" denseForwardInBoundsCells=(?P<dense_forward_in_bounds>\d+)"
    r" denseForwardCycleValidCells=(?P<dense_forward_cycle_valid>\d+)"
    r" denseForwardPhotometricValidCells=(?P<dense_forward_photometric_valid>\d+)"
    r" denseForwardTextureValidCells=(?P<dense_forward_texture_valid>\d+)"
    r" denseForwardSaturatedCells=(?P<dense_forward_saturated>\d+)"
    r" denseForwardOutOfBoundsCells=(?P<dense_forward_out_of_bounds>\d+)"
    r" denseForwardCoveredTiles=(?P<dense_forward_covered_tiles>\d+)"
    r" denseForwardCoveredTileMask=(?P<dense_forward_covered_tile_mask>\d+)"
)

# Schema 34 is deliberately a separate grammar.  Do not make its diagnostic
# fields optional in the schema-32/33 expression: that would let a truncated
# v34 record masquerade as immutable older evidence.
HEALTH_BASE_V34 = re.compile(
    HEALTH_BASE_V33.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>33) ",
             "proofSchemaVersion=(?P<proof_schema_version>34) ")
    .replace(r"windowPresents=(?P<window_presents>\d+) ",
             r"windowPresents=(?P<window_presents>\d+) "
             r"windowPresentationCallbacks=(?P<window_presentation_callbacks>\d+) ")
    + _V34_DIRECTION_DIAGNOSTICS
)

_HEALTH_DENSE_COMMON = (
    r"generator=(?P<generator>\d+) role=(?P<role>[a-z0-9_-]+) "
    r"displayId=(?P<display_id>-?\d+) "
    r"proofContract=(?P<proof_contract>[a-z0-9_-]+) "
    r"proofSchemaVersion=(?P<proof_schema_version>3[23]) "
    r"healthSequence=(?P<health_sequence>\d+) presents=(?P<presents>\d+) "
    r"windowStartNs=(?P<window_start_ns>\d+) "
    r"windowEndNs=(?P<window_end_ns>\d+) "
)
HEALTH_DENSE_EXTENSION = re.compile(
    r"Presentation health dense-extension " + _HEALTH_DENSE_COMMON +
    r"denseEnabled=(?P<dense_enabled>\d+) "
    r"densePromotions=(?P<dense_promotions>\d+) "
    r"densePasses=(?P<dense_passes>\d+) "
    r"denseCpuSubmitTotalUs=(?P<dense_submit_total_us>\d+) "
    r"denseCpuSubmitMaxUs=(?P<dense_submit_max_us>\d+) "
    r"denseCpuSubmitLastUs=(?P<dense_submit_last_us>\d+) "
    r"denseGpuCompleteTotalUs=(?P<dense_gpu_total_us>\d+) "
    r"denseGpuCompleteMaxUs=(?P<dense_gpu_max_us>\d+) "
    r"denseGpuCompleteLastUs=(?P<dense_gpu_last_us>\d+) "
    r"denseGpuBudgetUs=(?P<dense_gpu_budget_us>\d+) "
    r"denseTimedPairs=(?P<dense_timed_pairs>\d+) "
    r"denseWarpSequence=(?P<dense_warp_sequence>\d+) "
    r"denseWarpMaxCompletedSequence=(?P<dense_warp_completed_sequence>\d+) "
    r"denseTimerPending=(?P<dense_timer_pending>\d+) "
    r"denseTimerDisjoint=(?P<dense_timer_disjoint>\d+) "
    r"denseTimerUnavailable=(?P<dense_timer_unavailable>\d+) "
    r"denseTimerStale=(?P<dense_timer_stale>\d+) "
    r"denseTimerMaxQueueAge=(?P<dense_timer_max_queue_age>\d+) "
    r"densePerformanceRejected=(?P<dense_performance_rejected>\d+) "
    r"denseCalibrationRuns=(?P<dense_calibration_runs>\d+) "
    r"denseCalibrationUs=(?P<dense_calibration_us>\d+) "
    r"denseCombinedPairMaxWarpP95Us=(?P<dense_combined_pair_warp_us>\d+) "
    r"densePromotionWallSamples=(?P<dense_promotion_wall_samples>\d+) "
    r"densePromotionWallTotalUs=(?P<dense_promotion_wall_total_us>\d+) "
    r"densePromotionWallP95Us=(?P<dense_promotion_wall_p95_us>\d+) "
    r"densePromotionWallMaxUs=(?P<dense_promotion_wall_max_us>\d+) "
    r"denseSignatureWallSamples=(?P<dense_signature_wall_samples>\d+) "
    r"denseSignatureWallTotalUs=(?P<dense_signature_wall_total_us>\d+) "
    r"denseSignatureWallP95Us=(?P<dense_signature_wall_p95_us>\d+) "
    r"denseSignatureWallMaxUs=(?P<dense_signature_wall_max_us>\d+) "
    r"denseProofWallSamples=(?P<dense_proof_wall_samples>\d+) "
    r"denseProofWallTotalUs=(?P<dense_proof_wall_total_us>\d+) "
    r"denseProofWallP95Us=(?P<dense_proof_wall_p95_us>\d+) "
    r"denseProofWallMaxUs=(?P<dense_proof_wall_max_us>\d+) "
    r"denseSignatureSequence=(?P<dense_signature_sequence>\d+) "
    r"denseSignatureReady=(?P<dense_signature_ready>\d+) "
    r"denseSignatureUnavailable=(?P<dense_signature_unavailable>\d+) "
    r"denseSignatureMaxQueueAge=(?P<dense_signature_max_queue_age>\d+) "
    r"denseSignaturePending=(?P<dense_signature_pending>\d+) "
    r"denseSignatureCapability=(?P<dense_signature_capability>\d+) "
    r"denseSignatureRequestedGles=(?P<dense_signature_requested_gles>\d+) "
    r"denseSignatureActualGlesMajor=(?P<dense_signature_actual_gles_major>\d+) "
    r"denseSignatureActualGlesMinor=(?P<dense_signature_actual_gles_minor>\d+) "
    r"denseSignatureSelfTests=(?P<dense_signature_self_tests>\d+) "
    r"denseRuntimeCadenceSource=app-present-window "
    r"denseOfflineCadenceSource=surfaceflinger-layer-timestamps "
    r"denseVariant=(?P<dense_variant>[a-z0-9-]+) "
    r"denseAnalysisWidth=(?P<dense_analysis_width>\d+) "
    r"denseAnalysisHeight=(?P<dense_analysis_height>\d+) "
    r"denseSolveTexelsPerPromotion=(?P<dense_solve_texels>\d+) "
    r"denseTotalTexelsPerPromotion=(?P<dense_total_texels>\d+) "
    r"denseMaxFlowPixels=(?P<dense_max_flow_pixels>\d+) "
    r"denseProofCells=(?P<dense_proof_cells>\d+) "
    r"denseBackwardValidCells=(?P<dense_backward_valid>\d+) "
    r"denseForwardValidCells=(?P<dense_forward_valid>\d+)"
    r" denseCopySamples=(?P<dense_copy_samples>\d+) denseCopyTotalUs=(?P<dense_copy_total_us>\d+) denseCopyP95Us=(?P<dense_copy_p95_us>\d+) denseCopyMaxUs=(?P<dense_copy_max_us>\d+)"
    r" densePyramidSamples=(?P<dense_pyramid_samples>\d+) densePyramidTotalUs=(?P<dense_pyramid_total_us>\d+) densePyramidP95Us=(?P<dense_pyramid_p95_us>\d+) densePyramidMaxUs=(?P<dense_pyramid_max_us>\d+)"
    r" denseForwardSamples=(?P<dense_forward_samples>\d+) denseForwardTotalUs=(?P<dense_forward_total_us>\d+) denseForwardP95Us=(?P<dense_forward_p95_us>\d+) denseForwardMaxUs=(?P<dense_forward_max_us>\d+)"
    r" denseReverseSamples=(?P<dense_reverse_samples>\d+) denseReverseTotalUs=(?P<dense_reverse_total_us>\d+) denseReverseP95Us=(?P<dense_reverse_p95_us>\d+) denseReverseMaxUs=(?P<dense_reverse_max_us>\d+)"
    r" denseValidationSamples=(?P<dense_validation_samples>\d+) denseValidationTotalUs=(?P<dense_validation_total_us>\d+) denseValidationP95Us=(?P<dense_validation_p95_us>\d+) denseValidationMaxUs=(?P<dense_validation_max_us>\d+)"
    r" denseWarpSamples=(?P<dense_warp_samples>\d+) denseWarpTotalUs=(?P<dense_warp_total_us>\d+) denseWarpP95Us=(?P<dense_warp_p95_us>\d+) denseWarpMaxUs=(?P<dense_warp_max_us>\d+)"
    r" denseProofAtlasCapability=(?P<dense_proof_atlas_capability>\d+)"
    r" denseProofAtlasLayout=(?P<dense_proof_atlas_layout>\d+)"
    r" denseProofAtlasEnqueued=(?P<dense_proof_atlas_enqueued>\d+)"
    r" denseProofAtlasCompleted=(?P<dense_proof_atlas_completed>\d+)"
    r" denseProofAtlasPending=(?P<dense_proof_atlas_pending>\d+)"
    r" denseProofAtlasMaxQueueAge=(?P<dense_proof_atlas_max_queue_age>\d+)"
    r" denseProofAtlasTimeoutPolls=(?P<dense_proof_atlas_timeout_polls>\d+)"
    r" denseProofAtlasRingFull=(?P<dense_proof_atlas_ring_full>\d+)"
    r" denseProofAtlasErrors=(?P<dense_proof_atlas_errors>\d+)"
    r" denseProofAtlasTagErrors=(?P<dense_proof_atlas_tag_errors>\d+)"
    r" denseProofAtlasDiscarded=(?P<dense_proof_atlas_discarded>\d+)"
    r" denseProofAtlasSyncFallback=(?P<dense_proof_atlas_sync_fallback>\d+)"
    r" denseCallbackDeltaSamples=(?P<dense_callback_delta_samples>\d+)"
    r" denseCallbackDeltaTotalUs=(?P<dense_callback_delta_total_us>\d+)"
    r" denseCallbackDeltaMaxUs=(?P<dense_callback_delta_max_us>\d+)"
    r" denseCallbackLateCount=(?P<dense_callback_late_count>\d+)"
    r" densePresentWallSamples=(?P<dense_present_wall_samples>\d+) densePresentWallTotalUs=(?P<dense_present_wall_total_us>\d+) densePresentWallP95Us=(?P<dense_present_wall_p95_us>\d+) densePresentWallMaxUs=(?P<dense_present_wall_max_us>\d+)"
    r" denseSwapWallSamples=(?P<dense_swap_wall_samples>\d+) denseSwapWallTotalUs=(?P<dense_swap_wall_total_us>\d+) denseSwapWallP95Us=(?P<dense_swap_wall_p95_us>\d+) denseSwapWallMaxUs=(?P<dense_swap_wall_max_us>\d+)"
    r" denseProofEnqueueWallSamples=(?P<dense_proof_enqueue_wall_samples>\d+) denseProofEnqueueWallTotalUs=(?P<dense_proof_enqueue_wall_total_us>\d+) denseProofEnqueueWallP95Us=(?P<dense_proof_enqueue_wall_p95_us>\d+) denseProofEnqueueWallMaxUs=(?P<dense_proof_enqueue_wall_max_us>\d+)"
    r" denseProofPollWallSamples=(?P<dense_proof_poll_wall_samples>\d+) denseProofPollWallTotalUs=(?P<dense_proof_poll_wall_total_us>\d+) denseProofPollWallP95Us=(?P<dense_proof_poll_wall_p95_us>\d+) denseProofPollWallMaxUs=(?P<dense_proof_poll_wall_max_us>\d+)"
)

_V34_EXTENSION_DIAGNOSTICS = (
    r" denseDiagnosticCells=(?P<dense_diagnostic_cells>\d+)"
    r" denseDiagnosticTiles=(?P<dense_diagnostic_tiles>\d+)"
    r" denseDiagnosticMaskErrors=(?P<dense_diagnostic_mask_errors>\d+)"
    r" denseDiagnosticLastAtlasSequence=(?P<dense_diagnostic_last_atlas_sequence>\d+)"
    r" denseDiagnosticLastPairSequence=(?P<dense_diagnostic_last_pair_sequence>\d+)"
    r" denseDiagnosticLastPreviousEndpoint=(?P<dense_diagnostic_last_previous_endpoint>\d+)"
    r" denseDiagnosticLastCurrentEndpoint=(?P<dense_diagnostic_last_current_endpoint>\d+)"
)

HEALTH_DENSE_EXTENSION_V34 = re.compile(
    HEALTH_DENSE_EXTENSION.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>3[23]) ",
             "proofSchemaVersion=(?P<proof_schema_version>34) ")
    .replace(
        r" denseForwardValidCells=(?P<dense_forward_valid>\d+)",
        r" denseForwardValidCells=(?P<dense_forward_valid>\d+)" +
        _V34_EXTENSION_DIAGNOSTICS,
    )
)

# Schema 35 preserves the v34 linear RG/B proof tiles but transports the two
# diagnostic alpha masks through a separate nearest-sampled packed tile.
HEALTH_BASE_V35 = re.compile(
    HEALTH_BASE_V34.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>34) ",
        "proofSchemaVersion=(?P<proof_schema_version>35) ")
)

HEALTH_DENSE_EXTENSION_V35 = re.compile(
    HEALTH_DENSE_EXTENSION_V34.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>34) ",
             "proofSchemaVersion=(?P<proof_schema_version>35) ")
    .replace(
        r" denseDiagnosticMaskErrors=(?P<dense_diagnostic_mask_errors>\d+)",
        r" denseDiagnosticPackedCells=(?P<dense_diagnostic_packed_cells>\d+)"
        r" denseDiagnosticMaskLayout=(?P<dense_diagnostic_mask_layout>packed-nearest-bf-v1)"
        r" denseDiagnosticPartitionErrors=(?P<dense_diagnostic_partition_errors>\d+)"
        r" denseDiagnosticReservedBitErrors=(?P<dense_diagnostic_reserved_bit_errors>\d+)"
        r" denseDiagnosticMaskErrors=(?P<dense_diagnostic_mask_errors>\d+)",
    )
)

# Schema 36 keeps every schema-35 image-quality predicate immutable and adds
# an independently bound presentation-evidence epoch. The enqueue budget is
# per presentation epoch; accepted/excluded counters remain monotonic for the
# whole qualification enable so an old asynchronous PBO can never be silently
# relabelled as evidence for the new tier.
HEALTH_BASE_V36 = re.compile(
    HEALTH_BASE_V35.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>35) ",
             "proofSchemaVersion=(?P<proof_schema_version>36) ")
    .replace(
        r"windowPresentationEpoch=(?P<window_presentation_epoch>\d+) ",
        r"windowPresentationEpoch=(?P<window_presentation_epoch>\d+) "
        r"proofEvidencePresentationEpoch=(?P<proof_evidence_presentation_epoch>\d+) "
        r"proofEvidenceEnqueuedInEpoch=(?P<proof_evidence_enqueued_in_epoch>\d+) ",
    )
)

HEALTH_DENSE_EXTENSION_V36 = re.compile(
    HEALTH_DENSE_EXTENSION_V35.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>35) ",
             "proofSchemaVersion=(?P<proof_schema_version>36) ")
    .replace(
        r"windowEndNs=(?P<window_end_ns>\d+) ",
        r"windowEndNs=(?P<window_end_ns>\d+) "
        r"proofEvidencePresentationEpoch=(?P<proof_evidence_presentation_epoch>\d+) ",
    )
    .replace(
        r" denseProofAtlasCompleted=(?P<dense_proof_atlas_completed>\d+)",
        r" denseProofAtlasCompleted=(?P<dense_proof_atlas_completed>\d+)"
        r" proofEvidenceAccepted=(?P<proof_evidence_accepted>\d+)"
        r" proofEvidenceExcluded=(?P<proof_evidence_excluded>\d+)"
        r" proofEvidenceLastAcceptedAtlasSequence=(?P<proof_evidence_last_accepted_atlas_sequence>\d+)",
    )
)

# Schema 37 keeps the epoch-bound proof transport but replaces nominal-tier
# pair quotas with a timestamp-resampled source timeline. The three added
# fields make FIFO loss/timestamp repair and the exact sampled source position
# visible to the verifier without weakening any schema-36 evidence rule.
HEALTH_BASE_V37 = re.compile(
    HEALTH_BASE_V36.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>36) ",
             "proofSchemaVersion=(?P<proof_schema_version>37) ")
    .replace(r"windowDueSelected=(?P<window_due_selected>\d+) ", "")
    .replace(r"windowDueNoEndpoint=(?P<window_due_no_endpoint>\d+) ", "")
    .replace(r"windowDuePhaseClamped=(?P<window_due_phase_clamped>\d+) ", "")
    .replace(r"windowSyntheticQuotaSkipped=(?P<window_synthetic_quota_skipped>\d+) ", "")
    .replace(r"windowSyntheticQuotaOpening=(?P<window_synthetic_quota_opening>\d+) ", "")
    .replace(r"syntheticQuotaPending=(?P<synthetic_quota_pending>\d+) ", "")
    .replace(r"windowSyntheticPairCreated=(?P<window_synthetic_pair_created>\d+) ", "")
    .replace(r"windowSyntheticNotReady=(?P<window_synthetic_not_ready>\d+) ", "")
    .replace(r"lastSelectedSyntheticPair=(?P<last_selected_synthetic_pair>\d+) ", "")
    .replace(
        r"windowPresentationCallbacks=(?P<window_presentation_callbacks>\d+) ",
        r"windowPresentationCallbacks=(?P<window_presentation_callbacks>\d+) "
        r"windowDueNoEndpoint=(?P<window_due_no_endpoint>\d+) ",
    )
    .replace(
        r"proofEvidenceEnqueuedInEpoch=(?P<proof_evidence_enqueued_in_epoch>\d+) ",
        r"proofEvidenceEnqueuedInEpoch=(?P<proof_evidence_enqueued_in_epoch>\d+) "
        r"endpointFifoCoalesced=(?P<endpoint_fifo_coalesced>\d+) "
        r"endpointTimestampCorrections=(?P<endpoint_timestamp_corrections>\d+) "
        r"denseDiagnosticLastTargetSourceNs=(?P<dense_diagnostic_last_target_source_ns>\d+) ",
    )
)

HEALTH_DENSE_EXTENSION_V37 = re.compile(
    HEALTH_DENSE_EXTENSION_V36.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>36) ",
             "proofSchemaVersion=(?P<proof_schema_version>37) ")
)

# Schema 38 preserves the exact timestamp/FIFO/atlas transport of schema 37.
# Its incompatible contract changes only the meaning of a correlated proof
# sample: the output must follow the independent vector trajectory and beat
# the inverted-vector negative control, rather than also requiring a hard edge
# to become an intermediate RGB value at a fixed screen coordinate.
HEALTH_BASE_V38 = re.compile(
    HEALTH_BASE_V37.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>37) ",
        "proofSchemaVersion=(?P<proof_schema_version>38) ",
    )
)
HEALTH_DENSE_EXTENSION_V38 = re.compile(
    HEALTH_DENSE_EXTENSION_V37.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>37) ",
        "proofSchemaVersion=(?P<proof_schema_version>38) ",
    )
)

# Schema 39 preserves every schema-38 image, endpoint, and proof predicate.
# It makes Android presentation pacing and durable cadence attribution part of
# the immutable evidence contract instead of silently changing schema 38.
HEALTH_BASE_V39 = re.compile(
    HEALTH_BASE_V38.pattern
    .replace("proofSchemaVersion=(?P<proof_schema_version>38) ",
             "proofSchemaVersion=(?P<proof_schema_version>39) ")
    .replace(
        r"windowPresentationCallbacks=(?P<window_presentation_callbacks>\d+) ",
        r"windowPresentationCallbacks=(?P<window_presentation_callbacks>\d+) "
        r"presentationTimingMode=(?P<presentation_timing_mode>egl-android-next-vsync) "
        r"cadenceRejectConsecutiveWindows=(?P<cadence_reject_consecutive_windows>3) ",
    )
)
HEALTH_DENSE_EXTENSION_V39 = re.compile(
    HEALTH_DENSE_EXTENSION_V38.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>38) ",
        "proofSchemaVersion=(?P<proof_schema_version>39) ",
    )
)

# Schema 40 preserves every schema-39 presentation, endpoint, proof, and
# quality predicate. Its incompatible identity means the dense solver may use
# the preceding pair's independently validated field as a current-cost-checked
# proposal; schema-39 evidence can never qualify that temporal estimator.
HEALTH_BASE_V40 = re.compile(
    HEALTH_BASE_V39.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>39) ",
        "proofSchemaVersion=(?P<proof_schema_version>40) ",
    )
)
HEALTH_DENSE_EXTENSION_V40 = re.compile(
    HEALTH_DENSE_EXTENSION_V39.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>39) ",
        "proofSchemaVersion=(?P<proof_schema_version>40) ",
    )
)

# Schema 41 makes temporal admission strict: a previous-pair proposal must
# materially improve the current pair's image cost.  Schema-40's tie allowance
# produced visible stale-flow doubling on the physical F-Zero r22 capture.
HEALTH_BASE_V41 = re.compile(
    HEALTH_BASE_V40.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>40) ",
        "proofSchemaVersion=(?P<proof_schema_version>41) ",
    )
)
HEALTH_DENSE_EXTENSION_V41 = re.compile(
    HEALTH_DENSE_EXTENSION_V40.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>40) ",
        "proofSchemaVersion=(?P<proof_schema_version>41) ",
    )
)

# Schema 42 changes presentation semantics without weakening the v41 flow
# estimator: only uniform panel divisors are selected and every fractional
# output uses the timestamp phase of its exact adjacent retained endpoints.
HEALTH_BASE_V42 = re.compile(
    HEALTH_BASE_V41.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>41) ",
        "proofSchemaVersion=(?P<proof_schema_version>42) ",
    )
)
HEALTH_DENSE_EXTENSION_V42 = re.compile(
    HEALTH_DENSE_EXTENSION_V41.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>41) ",
        "proofSchemaVersion=(?P<proof_schema_version>42) ",
    )
)

# Schema 43 binds the exact timestamp-normalized source and measured panel
# clocks to the selected integer-scan divisor. Integer tier labels remain only
# backward-compatible diagnostics and can no longer authorize rounding a
# 29.97/59.94 or unstable57-59 stream upward.
HEALTH_BASE_V43 = re.compile(
    HEALTH_BASE_V42.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>42) ",
        "proofSchemaVersion=(?P<proof_schema_version>43) ",
    )
)
HEALTH_DENSE_EXTENSION_V43 = re.compile(
    HEALTH_DENSE_EXTENSION_V42.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>42) ",
        "proofSchemaVersion=(?P<proof_schema_version>43) ",
    )
)
HEALTH_RATIONAL_CLOCK_V43 = re.compile(
    r"Presentation health rational-clock generator=(?P<generator>\d+) "
    r"role=(?P<role>[a-z0-9_-]+) displayId=(?P<display_id>-?\d+) "
    r"proofContract=(?P<proof_contract>[a-z0-9_-]+) "
    r"proofSchemaVersion=(?P<proof_schema_version>43) "
    r"healthSequence=(?P<health_sequence>\d+) presents=(?P<presents>\d+) "
    r"windowStartNs=(?P<window_start_ns>\d+) "
    r"windowEndNs=(?P<window_end_ns>\d+) "
    r"proofEvidencePresentationEpoch="
    r"(?P<proof_evidence_presentation_epoch>\d+) "
    r"rClock=(?P<source_millihz>\d+)/(?P<target_millihz>\d+)/"
    r"(?P<panel_millihz>\d+)/(?P<panel_scans_per_output>\d+)/"
    r"(?P<uniform_output_qualified>[01])/(?P<window_swap_millihz>\d+)/"
    r"(?P<source_clock_kind>auth|pts)$"
)
HEALTH_BASE_V44 = re.compile(
    HEALTH_BASE_V43.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>43) ",
        "proofSchemaVersion=(?P<proof_schema_version>44) ",
    )
)
HEALTH_DENSE_EXTENSION_V44 = re.compile(
    HEALTH_DENSE_EXTENSION_V43.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>43) ",
        "proofSchemaVersion=(?P<proof_schema_version>44) ",
    )
)
HEALTH_RATIONAL_CLOCK_V44 = re.compile(
    HEALTH_RATIONAL_CLOCK_V43.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>43) ",
        "proofSchemaVersion=(?P<proof_schema_version>44) ",
    )
)
HEALTH_BASE_V45 = re.compile(
    HEALTH_BASE_V44.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>44) ",
        "proofSchemaVersion=(?P<proof_schema_version>45) ",
    )
)
HEALTH_DENSE_EXTENSION_V45 = re.compile(
    HEALTH_DENSE_EXTENSION_V44.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>44) ",
        "proofSchemaVersion=(?P<proof_schema_version>45) ",
    )
)
HEALTH_RATIONAL_CLOCK_V45 = re.compile(
    HEALTH_RATIONAL_CLOCK_V44.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>44) ",
        "proofSchemaVersion=(?P<proof_schema_version>45) ",
    )
)
HEALTH_BASE_V46 = re.compile(
    HEALTH_BASE_V45.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>45) ",
        "proofSchemaVersion=(?P<proof_schema_version>46) ",
    )
)
HEALTH_DENSE_EXTENSION_V46 = re.compile(
    HEALTH_DENSE_EXTENSION_V45.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>45) ",
        "proofSchemaVersion=(?P<proof_schema_version>46) ",
    )
)
HEALTH_RATIONAL_CLOCK_V46 = re.compile(
    HEALTH_RATIONAL_CLOCK_V45.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>45) ",
        "proofSchemaVersion=(?P<proof_schema_version>46) ",
    )
)
HEALTH_BASE_V47 = re.compile(
    HEALTH_BASE_V46.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>46) ",
        "proofSchemaVersion=(?P<proof_schema_version>47) ",
    )
)
HEALTH_DENSE_EXTENSION_V47 = re.compile(
    HEALTH_DENSE_EXTENSION_V46.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>46) ",
        "proofSchemaVersion=(?P<proof_schema_version>47) ",
    )
)
HEALTH_RATIONAL_CLOCK_V47 = re.compile(
    HEALTH_RATIONAL_CLOCK_V46.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>46) ",
        "proofSchemaVersion=(?P<proof_schema_version>47) ",
    )
)
HEALTH_BASE_V48 = re.compile(
    HEALTH_BASE_V47.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>47) ",
        "proofSchemaVersion=(?P<proof_schema_version>48) ",
    )
)
HEALTH_DENSE_EXTENSION_V48 = re.compile(
    HEALTH_DENSE_EXTENSION_V47.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>47) ",
        "proofSchemaVersion=(?P<proof_schema_version>48) ",
    )
)
HEALTH_RATIONAL_CLOCK_V48 = re.compile(
    HEALTH_RATIONAL_CLOCK_V47.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>47) ",
        "proofSchemaVersion=(?P<proof_schema_version>48) ",
    )
)
HEALTH_BASE_V49 = re.compile(
    HEALTH_BASE_V48.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>48) ",
        "proofSchemaVersion=(?P<proof_schema_version>49) ",
    )
)
HEALTH_DENSE_EXTENSION_V49 = re.compile(
    HEALTH_DENSE_EXTENSION_V48.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>48) ",
        "proofSchemaVersion=(?P<proof_schema_version>49) ",
    )
)
HEALTH_RATIONAL_CLOCK_V49 = re.compile(
    HEALTH_RATIONAL_CLOCK_V48.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>48) ",
        "proofSchemaVersion=(?P<proof_schema_version>49) ",
    )
)
HEALTH_BASE_V50 = re.compile(
    HEALTH_BASE_V49.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>49) ",
        "proofSchemaVersion=(?P<proof_schema_version>50) ",
    )
)
HEALTH_DENSE_EXTENSION_V50 = re.compile(
    HEALTH_DENSE_EXTENSION_V49.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>49) ",
        "proofSchemaVersion=(?P<proof_schema_version>50) ",
    )
)
HEALTH_RATIONAL_CLOCK_V50 = re.compile(
    HEALTH_RATIONAL_CLOCK_V49.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>49) ",
        "proofSchemaVersion=(?P<proof_schema_version>50) ",
    )
)
HEALTH_BASE_V51 = re.compile(
    HEALTH_BASE_V50.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>50) ",
        "proofSchemaVersion=(?P<proof_schema_version>51) ",
    )
)
HEALTH_DENSE_EXTENSION_V51 = re.compile(
    HEALTH_DENSE_EXTENSION_V50.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>50) ",
        "proofSchemaVersion=(?P<proof_schema_version>51) ",
    )
)
HEALTH_RATIONAL_CLOCK_V51 = re.compile(
    HEALTH_RATIONAL_CLOCK_V50.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>50) ",
        "proofSchemaVersion=(?P<proof_schema_version>51) ",
    )
)
HEALTH_BASE_V54 = re.compile(
    HEALTH_BASE_V51.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>51) ",
        "proofSchemaVersion=(?P<proof_schema_version>54) ",
    )
)
HEALTH_DENSE_EXTENSION_V54 = re.compile(
    HEALTH_DENSE_EXTENSION_V51.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>51) ",
        "proofSchemaVersion=(?P<proof_schema_version>54) ",
    )
)
HEALTH_RATIONAL_CLOCK_V54 = re.compile(
    HEALTH_RATIONAL_CLOCK_V51.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>51) ",
        "proofSchemaVersion=(?P<proof_schema_version>54) ",
    )
)
HEALTH_BASE_V55 = re.compile(
    HEALTH_BASE_V54.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>54) ",
        "proofSchemaVersion=(?P<proof_schema_version>55) ",
    )
)
HEALTH_DENSE_EXTENSION_V55 = re.compile(
    HEALTH_DENSE_EXTENSION_V54.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>54) ",
        "proofSchemaVersion=(?P<proof_schema_version>55) ",
    )
)
HEALTH_RATIONAL_CLOCK_V55 = re.compile(
    HEALTH_RATIONAL_CLOCK_V54.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>54) ",
        "proofSchemaVersion=(?P<proof_schema_version>55) ",
    )
)
HEALTH_BASE_V56 = re.compile(
    HEALTH_BASE_V55.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>55) ",
        "proofSchemaVersion=(?P<proof_schema_version>56) ",
    )
)
HEALTH_DENSE_EXTENSION_V56 = re.compile(
    HEALTH_DENSE_EXTENSION_V55.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>55) ",
        "proofSchemaVersion=(?P<proof_schema_version>56) ",
    )
)
HEALTH_RATIONAL_CLOCK_V56 = re.compile(
    HEALTH_RATIONAL_CLOCK_V55.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>55) ",
        "proofSchemaVersion=(?P<proof_schema_version>56) ",
    )
)
HEALTH_BASE_V57 = re.compile(
    HEALTH_BASE_V56.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>56) ",
        "proofSchemaVersion=(?P<proof_schema_version>57) ",
    )
)
HEALTH_DENSE_EXTENSION_V57 = re.compile(
    HEALTH_DENSE_EXTENSION_V56.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>56) ",
        "proofSchemaVersion=(?P<proof_schema_version>57) ",
    )
)
HEALTH_RATIONAL_CLOCK_V57 = re.compile(
    HEALTH_RATIONAL_CLOCK_V56.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>56) ",
        "proofSchemaVersion=(?P<proof_schema_version>57) ",
    )
)
HEALTH_BASE_V58 = re.compile(
    HEALTH_BASE_V57.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>57) ",
        "proofSchemaVersion=(?P<proof_schema_version>58) ",
    )
)
HEALTH_DENSE_EXTENSION_V58 = re.compile(
    HEALTH_DENSE_EXTENSION_V57.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>57) ",
        "proofSchemaVersion=(?P<proof_schema_version>58) ",
    )
)
HEALTH_RATIONAL_CLOCK_V58 = re.compile(
    HEALTH_RATIONAL_CLOCK_V57.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>57) ",
        "proofSchemaVersion=(?P<proof_schema_version>58) ",
    )
)
HEALTH_BASE_V59 = re.compile(
    HEALTH_BASE_V58.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>58) ",
        "proofSchemaVersion=(?P<proof_schema_version>59) ",
    )
)
HEALTH_DENSE_EXTENSION_V59 = re.compile(
    HEALTH_DENSE_EXTENSION_V58.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>58) ",
        "proofSchemaVersion=(?P<proof_schema_version>59) ",
    )
)
HEALTH_RATIONAL_CLOCK_V59 = re.compile(
    HEALTH_RATIONAL_CLOCK_V58.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>58) ",
        "proofSchemaVersion=(?P<proof_schema_version>59) ",
    )
)
HEALTH_BASE_V60 = re.compile(
    HEALTH_BASE_V59.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>59) ",
        "proofSchemaVersion=(?P<proof_schema_version>60) ",
    )
)
HEALTH_DENSE_EXTENSION_V60 = re.compile(
    HEALTH_DENSE_EXTENSION_V59.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>59) ",
        "proofSchemaVersion=(?P<proof_schema_version>60) ",
    )
)
HEALTH_RATIONAL_CLOCK_V60 = re.compile(
    HEALTH_RATIONAL_CLOCK_V59.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>59) ",
        "proofSchemaVersion=(?P<proof_schema_version>60) ",
    )
)
HEALTH_BASE_V61 = re.compile(
    HEALTH_BASE_V60.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>60) ",
        "proofSchemaVersion=(?P<proof_schema_version>61) ",
    )
)
HEALTH_DENSE_EXTENSION_V61 = re.compile(
    HEALTH_DENSE_EXTENSION_V60.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>60) ",
        "proofSchemaVersion=(?P<proof_schema_version>61) ",
    )
)
HEALTH_RATIONAL_CLOCK_V61 = re.compile(
    HEALTH_RATIONAL_CLOCK_V60.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>60) ",
        "proofSchemaVersion=(?P<proof_schema_version>61) ",
    )
)
HEALTH_BASE_V62 = re.compile(
    HEALTH_BASE_V61.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>61) ",
        "proofSchemaVersion=(?P<proof_schema_version>62) ",
    )
)
HEALTH_DENSE_EXTENSION_V62 = re.compile(
    HEALTH_DENSE_EXTENSION_V61.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>61) ",
        "proofSchemaVersion=(?P<proof_schema_version>62) ",
    )
)
HEALTH_RATIONAL_CLOCK_V62 = re.compile(
    HEALTH_RATIONAL_CLOCK_V61.pattern.replace(
        "proofSchemaVersion=(?P<proof_schema_version>61) ",
        "proofSchemaVersion=(?P<proof_schema_version>62) ",
    )
)

FORBIDDEN = (
    "frame generator initialization failed",
    "display-vsync presentation failed",
    "shader compile failed",
    "shader link failed",
    "fatal signal",
    "renderer stopped",
)

BRIEF_PID = re.compile(
    r"^\s*[VDIWEF]/EmuFusionFrameGen\(\s*(\d+)\s*\)\s*:"
)
THREADTIME_PID = re.compile(
    r"^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3,6}\s+"
    r"(\d+)\s+\d+\s+[VDIWEF]\s+EmuFusionFrameGen\s*:"
)


def framegen_line_pid(line: str) -> int | None:
    """Extract identity only from the two exact supported logcat formats."""
    brief = BRIEF_PID.match(line)
    threadtime = THREADTIME_PID.match(line)
    if brief is not None and threadtime is not None:
        raise ValueError("ambiguous frame-generation process identity")
    match = brief or threadtime
    if match is None:
        return None
    pid = int(match.group(1))
    return pid if pid > 0 else None


def _java_round_positive(value: float) -> int:
    return int(math.floor(value + 0.5))


def _v27_workload_identity_valid(values: dict, input_width: int,
                                  input_height: int) -> bool:
    """Bind v27 to its 192x108 cap while preserving the source aspect."""
    width = values.get("dense_analysis_width", 0)
    height = values.get("dense_analysis_height", 0)
    if (not isinstance(input_width, int) or not isinstance(input_height, int) or
            input_width < 1 or input_height < 1 or
            values.get("dense_variant") != "fragment-192x108-v27" or
            not isinstance(width, int) or not isinstance(height, int) or
            width < 4 or height < 4 or width > 192 or height > 108):
        return False
    scale = min(1.0, 192.0 / input_width, 108.0 / input_height)
    expected_width = max(4, _java_round_positive(input_width * scale))
    expected_height = max(4, _java_round_positive(input_height * scale))
    if width != expected_width or height != expected_height:
        return False
    widths = (width, width // 2, width // 4)
    heights = (height, height // 2, height // 4)
    solve = 2 * sum(w * h * iterations for w, h, iterations in
                    zip(widths, heights, (4, 4, 8)))
    pyramid = 2 * (widths[1] * heights[1] + widths[2] * heights[2])
    validation = 2 * width * height
    return (values.get("dense_solve_texels") == solve and
            values.get("dense_total_texels") == solve + pyramid + validation)


def _v28_workload_identity_valid(values: dict, input_width: int,
                                  input_height: int) -> bool:
    """Bind v28 to its 160x90 cap and exact integer pyramid rounding."""
    width = values.get("dense_analysis_width", 0)
    height = values.get("dense_analysis_height", 0)
    schema = values.get("proof_schema_version")
    expected_variant = (
        "fragment-v62-parallel-global-seed" if schema == 62 else
        "fragment-v61-parallel-global-seed" if schema == 61 else
        "fragment-v60-independent-global-seed" if schema == 60 else
        "fragment-v59-edge-aware-neighbor" if schema == 59 else
        "fragment-v58-joint-cycle" if schema == 58 else
        "fragment-v57-joint-cycle" if schema == 57 else
        "fragment-128x72-v56-strong-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow" if schema == 56 else
        "fragment-128x72-v55-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow" if schema == 55 else
        "fragment-128x72-v54-cycle-aware-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow" if schema == 54 else
        "fragment-128x72-v51-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow" if schema == 51 else
        "fragment-128x72-v50-iterated-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow" if schema == 50 else
        "fragment-128x72-v49-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow" if schema == 49 else
        "fragment-128x72-v48-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow" if schema == 48 else
        "fragment-128x72-v47-stamped-pts-loss-bound-independent-bidirectional-spatial-consensus-rational-clock-strict-flow" if schema == 47 else
        "fragment-128x72-v46-independent-bidirectional-spatial-consensus-rational-clock-strict-flow" if schema == 46 else
        "fragment-128x72-v45-spatial-consensus-rational-clock-strict-flow" if schema == 45 else
        "fragment-128x72-v44-unique-endpoint-rational-clock-strict-flow" if schema == 44 else
        "fragment-128x72-v43-rational-source-panel-clock-strict-flow" if schema == 43 else
        "fragment-128x72-v42-uniform-timestamp-resample-strict-flow" if schema == 42 else
        "fragment-128x72-v41-strict-temporal-flow-guidance-present-timed-vector-trajectory" if schema == 41 else
        "fragment-128x72-v40-temporal-flow-guidance-present-timed-vector-trajectory" if schema == 40 else
        "fragment-128x72-v39-present-timed-vector-trajectory" if schema == 39 else
        "fragment-128x72-v38-vector-trajectory" if schema == 38 else
        "fragment-128x72-v37-timestamp-resample" if schema == 37 else
        "fragment-160x90-v36-epoch-bound-packed-mask" if schema == 36 else
        "fragment-160x90-v35-packed-mask" if schema == 35 else
        "fragment-160x90-v34-diagnostic" if schema == 34 else
        "fragment-160x90-v28")
    max_width = 128 if schema in (37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 54, 55, 56, 57, 58, 59, 60, 61, 62) else 160
    max_height = 72 if schema in (37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 54, 55, 56, 57, 58, 59, 60, 61, 62) else 90
    if (not isinstance(input_width, int) or not isinstance(input_height, int) or
            input_width < 1 or input_height < 1 or
            values.get("dense_variant") != expected_variant or
            not isinstance(width, int) or not isinstance(height, int) or
            width < 4 or height < 4 or
            width > max_width or height > max_height):
        return False
    scale = min(1.0, max_width / input_width, max_height / input_height)
    expected_width = max(4, _java_round_positive(input_width * scale))
    expected_height = max(4, _java_round_positive(input_height * scale))
    if width != expected_width or height != expected_height:
        return False
    widths = (width, width // 2, width // 4)
    heights = (height, height // 2, height // 4)
    solve = 2 * sum(w * h * iterations for w, h, iterations in
                    zip(widths, heights, (4, 4, 8)))
    if schema in (51, 54, 55, 56, 57, 58, 59, 60, 61, 62):
        solve += 2 * width * height
    pyramid = 2 * (widths[1] * heights[1] + widths[2] * heights[2])
    validation = 2 * width * height
    global_seed = 216 if schema in (61, 62) else 2 if schema == 60 else 0
    return (values.get("dense_solve_texels") == solve and
            values.get("dense_total_texels") ==
            solve + pyramid + validation + global_seed)


def _v31_signature_identity_valid(values: dict) -> bool:
    """Bind schema31 to an executed GLES3 core-query/RGBA8 capability."""
    return (values.get("dense_signature_capability") == 63 and
            values.get("dense_signature_requested_gles") == 3 and
            isinstance(values.get("dense_signature_actual_gles_major"), int) and
            values["dense_signature_actual_gles_major"] >= 3 and
            isinstance(values.get("dense_signature_actual_gles_minor"), int) and
            values["dense_signature_actual_gles_minor"] >= 0 and
            values.get("dense_signature_self_tests") == 1)


def _dense_v28_wall_telemetry_valid(values: dict,
                                    timestamp_resampled: bool) -> bool:
    """Validate wall series without inventing REAL swaps for resampling."""
    promotion = timestamp_resampled or (
        values.get("dense_promotion_wall_samples", 0) >= 120 and
        values.get("dense_promotion_wall_total_us", 0) >=
            values.get("dense_promotion_wall_max_us", 0) >=
            values.get("dense_promotion_wall_p95_us", 0) > 0 and
        values.get("dense_promotion_wall_p95_us", 0) <=
            values.get("dense_gpu_budget_us", 0)
    )
    return (
        promotion and
        values.get("dense_signature_wall_samples", 0) >= 120 and
        values.get("dense_signature_wall_total_us", 0) >=
            values.get("dense_signature_wall_max_us", 0) >=
            values.get("dense_signature_wall_p95_us", 0) > 0 and
        values.get("dense_proof_wall_samples", -1) == 0 and
        values.get("dense_proof_wall_total_us", -1) == 0 and
        values.get("dense_proof_wall_p95_us", -1) == 0 and
        values.get("dense_proof_wall_max_us", -1) == 0
    )
ATTACHED = re.compile(
    r"Frame generator attached generator=(\d+) role=([a-z0-9_-]+) "
    r"displayId=(-?\d+) proofContract=([a-z0-9_-]+) "
    r"proofSchemaVersion=(\d+)(?: .*?input=(\d+)x(\d+))?"
)
# Engines report their true frame size after the initial attach (a DS
# stream attaches at panel size and resizes to native 256x192), so the
# workload identity must bind to the LATEST resized dimensions.
RESIZED = re.compile(
    r"Frame generator resized generator=(\d+) role=([a-z0-9_-]+) "
    r"displayId=(-?\d+) input=(\d+)x(\d+)"
)
# The allocation identity is authoritative for the workload check: it names
# the exact history dimensions the analysis grid derived from, surviving
# post-attach surface resizes (DS lower screen).
DENSE_ALLOCATED = re.compile(
    r"Frame generator dense-allocated generator=(\d+) role=([a-z0-9_-]+) "
    r"displayId=(-?\d+) history=(\d+)x(\d+) analysis=(\d+)x(\d+)"
)
PROOF_STATE = re.compile(
    r"Qualification proof generator=(\d+) enabled=(true|false) "
    r"proofContract=([a-z0-9_-]+) proofSchemaVersion=(\d+)"
)
PROOF_ENABLED = re.compile(
    r"Qualification proof generator=(\d+) enabled=true "
    r"proofContract=([a-z0-9_-]+) proofSchemaVersion=(\d+)"
)
ROUTE_EVENT = re.compile(
    r"In-window route accepted engine=([^ ]+) system=([^\s]+)"
)
ROUTE_BRIEF_PID = re.compile(
    r"^\s*[VDIWEF]/(?:InWindowGameHost|LucentInWindow)\(\s*(\d+)\s*\)\s*:"
)
ROUTE_THREADTIME_PID = re.compile(
    r"^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3,6}\s+"
    r"(\d+)\s+\d+\s+[VDIWEF]\s+(?:InWindowGameHost|LucentInWindow)\s*:"
)
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class _JoinedHealth:
    def __init__(self, *parts):
        self.values = {}
        for part in parts:
            for key, value in part.groupdict().items():
                if key in self.values and self.values[key] != value:
                    raise ValueError(
                        f"split health common key mismatch for {key}")
                self.values[key] = value

    def group(self, key):
        return self.values[key]

    def groupdict(self):
        return dict(self.values)


def _parse_health_records(log: str):
    # Split base/extension pairing is PER GENERATOR STREAM, exactly like the
    # runner's transport parser: two live generators (the dual-screen
    # GamePad pair) emit adjacently on their own handler threads but
    # interleave in the shared logcat, so another stream's records between
    # one stream's base and extension are physical concurrency, not
    # splicing. Keyed by (pid, generator id); all anti-splicing checks stay
    # per stream. (Physically hit in run 2026-08-17-wiiu6.)
    parsed = []
    pending = {}
    for line_index, line in enumerate(log.splitlines()):
        pid = framegen_line_pid(line)
        base = (HEALTH_BASE_V62.search(line) or HEALTH_BASE_V61.search(line) or HEALTH_BASE_V60.search(line) or HEALTH_BASE_V59.search(line) or HEALTH_BASE_V58.search(line) or HEALTH_BASE_V57.search(line) or HEALTH_BASE_V56.search(line) or HEALTH_BASE_V55.search(line) or HEALTH_BASE_V54.search(line) or HEALTH_BASE_V51.search(line) or HEALTH_BASE_V50.search(line) or HEALTH_BASE_V49.search(line) or HEALTH_BASE_V48.search(line) or HEALTH_BASE_V47.search(line) or HEALTH_BASE_V46.search(line) or HEALTH_BASE_V45.search(line) or HEALTH_BASE_V44.search(line) or HEALTH_BASE_V43.search(line) or
                HEALTH_BASE_V42.search(line) or
                HEALTH_BASE_V41.search(line) or
                HEALTH_BASE_V40.search(line) or
                HEALTH_BASE_V39.search(line) or
                HEALTH_BASE_V38.search(line) or
                HEALTH_BASE_V37.search(line) or
                HEALTH_BASE_V36.search(line) or HEALTH_BASE_V35.search(line) or
                HEALTH_BASE_V34.search(line) or
                HEALTH_BASE_V33.search(line) or HEALTH_BASE.search(line))
        extension = (HEALTH_DENSE_EXTENSION_V62.search(line) or HEALTH_DENSE_EXTENSION_V61.search(line) or
                     HEALTH_DENSE_EXTENSION_V60.search(line) or
                     HEALTH_DENSE_EXTENSION_V59.search(line) or
                     HEALTH_DENSE_EXTENSION_V58.search(line) or
                     HEALTH_DENSE_EXTENSION_V57.search(line) or
                     HEALTH_DENSE_EXTENSION_V56.search(line) or
                     HEALTH_DENSE_EXTENSION_V55.search(line) or
                     HEALTH_DENSE_EXTENSION_V54.search(line) or
                     HEALTH_DENSE_EXTENSION_V51.search(line) or
                     HEALTH_DENSE_EXTENSION_V50.search(line) or
                     HEALTH_DENSE_EXTENSION_V49.search(line) or
                     HEALTH_DENSE_EXTENSION_V48.search(line) or
                     HEALTH_DENSE_EXTENSION_V47.search(line) or
                     HEALTH_DENSE_EXTENSION_V46.search(line) or
                     HEALTH_DENSE_EXTENSION_V45.search(line) or
                     HEALTH_DENSE_EXTENSION_V44.search(line) or
                     HEALTH_DENSE_EXTENSION_V43.search(line) or
                     HEALTH_DENSE_EXTENSION_V42.search(line) or
                     HEALTH_DENSE_EXTENSION_V41.search(line) or
                     HEALTH_DENSE_EXTENSION_V40.search(line) or
                     HEALTH_DENSE_EXTENSION_V39.search(line) or
                     HEALTH_DENSE_EXTENSION_V38.search(line) or
                     HEALTH_DENSE_EXTENSION_V37.search(line) or
                     HEALTH_DENSE_EXTENSION_V36.search(line) or
                     HEALTH_DENSE_EXTENSION_V35.search(line) or
                     HEALTH_DENSE_EXTENSION_V34.search(line) or
                     HEALTH_DENSE_EXTENSION.search(line))
        rational_clock = (HEALTH_RATIONAL_CLOCK_V62.search(line) or HEALTH_RATIONAL_CLOCK_V61.search(line) or
                          HEALTH_RATIONAL_CLOCK_V60.search(line) or
                          HEALTH_RATIONAL_CLOCK_V59.search(line) or
                          HEALTH_RATIONAL_CLOCK_V58.search(line) or
                          HEALTH_RATIONAL_CLOCK_V57.search(line) or
                          HEALTH_RATIONAL_CLOCK_V56.search(line) or
                          HEALTH_RATIONAL_CLOCK_V55.search(line) or
                          HEALTH_RATIONAL_CLOCK_V54.search(line) or
                          HEALTH_RATIONAL_CLOCK_V51.search(line) or
                          HEALTH_RATIONAL_CLOCK_V50.search(line) or
                          HEALTH_RATIONAL_CLOCK_V49.search(line) or
                          HEALTH_RATIONAL_CLOCK_V48.search(line) or
                          HEALTH_RATIONAL_CLOCK_V47.search(line) or
                          HEALTH_RATIONAL_CLOCK_V46.search(line) or
                          HEALTH_RATIONAL_CLOCK_V45.search(line) or
                          HEALTH_RATIONAL_CLOCK_V44.search(line) or
                          HEALTH_RATIONAL_CLOCK_V43.search(line))
        health = HEALTH.search(line)
        if "Presentation health base" in line and base is None:
            raise ValueError("malformed or truncated split health base record")
        if "Presentation health dense-extension" in line and extension is None:
            raise ValueError("malformed or truncated split health extension record")
        if "Presentation health rational-clock" in line and rational_clock is None:
            raise ValueError("malformed or truncated rational-clock health record")
        if sum(value is not None for value in (
                base, extension, rational_clock, health)) > 1:
            raise ValueError("ambiguous frame-generation health transport record")
        if base:
            if pid is None:
                raise ValueError("frame-generation health record has no process identity")
            stream = (pid, base.group("generator"))
            if stream in pending:
                raise ValueError("split health base is missing its extension")
            pending[stream] = (base, pid, line_index, None)
        elif extension:
            if pid is None:
                raise ValueError("frame-generation health record has no process identity")
            stream = (pid, extension.group("generator"))
            if stream not in pending:
                raise ValueError("orphan split health extension record")
            pending_base = pending[stream]
            if pending_base[3] is not None:
                raise ValueError("duplicate split health extension record")
            if int(extension.group("proof_schema_version")) in (43, 44, 45, 46, 47, 48, 49, 50, 51, 54, 55, 56, 57, 58, 59, 60, 61, 62):
                pending[stream] = (pending_base[0], pending_base[1],
                                   pending_base[2], extension)
            else:
                pending.pop(stream)
                parsed.append((_JoinedHealth(pending_base[0], extension), pid,
                               line_index))
        elif rational_clock:
            if pid is None:
                raise ValueError("frame-generation health record has no process identity")
            stream = (pid, rational_clock.group("generator"))
            if stream not in pending or pending[stream][3] is None:
                raise ValueError("orphan rational-clock health record")
            pending_base = pending.pop(stream)
            parsed.append((_JoinedHealth(pending_base[0], pending_base[3],
                                         rational_clock), pid, line_index))
        elif health:
            stream = (pid, health.group("generator")) if pid is not None else None
            if stream in pending:
                raise ValueError("legacy health record interrupts split health pair")
            if pid is None:
                raise ValueError("frame-generation health record has no process identity")
            if int(health.group("proof_schema_version")) >= 32:
                raise ValueError("schema 32+ requires split health transport")
            parsed.append((health, pid, line_index))
        elif pending and ("Frame generator attached" in line or
                          "Qualification proof generator=" in line or
                          "Presentation health" in line):
            # Lifecycle records carry their own generator id; only the
            # MATCHING stream's pending base is interrupted by one.
            lifecycle = re.search(r"generator=(\d+)", line)
            if (lifecycle is not None and pid is not None and
                    (pid, lifecycle.group(1)) in pending):
                raise ValueError(
                    "frame-generation state record interrupts split health pair")
    if pending:
        if any(value[3] is None for value in pending.values()):
            raise ValueError("split health base is missing its extension")
        raise ValueError("split health record is missing its rational-clock completion")
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def framegen_proof_state_events(log: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line_index, line in enumerate(log.splitlines()):
        state = PROOF_STATE.search(line)
        if state is None:
            continue
        pid = framegen_line_pid(line)
        if pid is None:
            raise ValueError("qualification proof marker has no process identity")
        events.append({
            "lineIndex": line_index,
            "pid": pid,
            "generator": int(state.group(1)),
            "enabled": state.group(2) == "true",
            "proofContract": state.group(3),
            "proofSchemaVersion": int(state.group(4)),
        })
    return events


def _load_qualification(path: Path | None, segment_id: str | None) -> tuple[dict, dict]:
    if path is None:
        raise ValueError("explicit frame-generation qualification manifest is required")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as failure:
        raise ValueError(f"invalid frame-generation qualification manifest: {failure}") from failure
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise ValueError("unsupported frame-generation qualification manifest")
    identity = document.get("identity")
    evidence = document.get("evidence")
    segments = document.get("segments")
    if (not isinstance(identity, dict) or not isinstance(evidence, dict) or
            not isinstance(segments, list) or not segments):
        raise ValueError("qualification manifest has no identity, evidence, or segments")
    for key in ("logSha256", "latencySha256"):
        if not isinstance(evidence.get(key), str) or not SHA256.fullmatch(evidence[key]):
            raise ValueError(f"qualification evidence has invalid {key}")
    if segment_id is None or not SAFE_ID.fullmatch(segment_id):
        raise ValueError("an explicit safe frame-generation segment id is required")
    matching = [value for value in segments
                if isinstance(value, dict) and value.get("segmentId") == segment_id]
    if len(matching) != 1:
        raise ValueError("qualification segment id is absent or duplicated")
    return document, matching[0]


def _validate_identity(identity: dict, log: str, *, pid: int, generator: int,
                       role: str, display_id: int) -> None:
    required_ids = ("sessionId", "systemId", "gameId", "coreId", "packageName")
    if any(not isinstance(identity.get(key), str) or
           not SAFE_ID.fullmatch(identity[key]) for key in required_ids):
        raise ValueError("qualification identity contains an absent or unsafe id")
    for key in ("romSha256", "coreSha256", "apkSha256"):
        value = identity.get(key)
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise ValueError(f"qualification identity has invalid {key}")
    exact = {
        "pid": pid,
        "generator": generator,
        "role": role,
        "displayId": display_id,
    }
    if any(identity.get(key) != value for key, value in exact.items()):
        raise ValueError("qualification identity does not match the selected generator")
    routes = []
    for line in log.splitlines():
        event = ROUTE_EVENT.search(line)
        if event is None:
            continue
        pid_match = ROUTE_BRIEF_PID.match(line) or ROUTE_THREADTIME_PID.match(line)
        if pid_match is None:
            raise ValueError("game route record has no process identity")
        routes.append((int(pid_match.group(1)), event.group(1), event.group(2)))
    expected_route = (pid, identity["coreId"], identity["systemId"])
    if routes.count(expected_route) != 1 or any(route != expected_route for route in routes):
        raise ValueError("qualification identity is not bound to exactly one matching game route")


def _record_at(records: list[dict], end_ns: int, label: str) -> dict:
    matching = [record for record in records if record["window_end_ns"] == end_ns]
    if len(matching) != 1:
        raise ValueError(f"qualification {label} does not identify exactly one health record")
    return matching[0]


def _validate_proof_reset(reset: object, events: list[dict[str, object]],
                          records: list[dict], baseline: dict, end: dict,
                          *, pid: int, generator: int,
                          proof_contract: str = PROOF_CONTRACT,
                          proof_schema_version: int = PROOF_SCHEMA_VERSION) -> dict[str, object]:
    if not isinstance(reset, dict) or set(reset) != {
            "pid", "generator", "disabledLineIndex", "enabledLineIndex",
            "baselineWindowEndNs"}:
        raise ValueError("qualification proof reset has an unexpected schema")
    if (reset.get("pid") != pid or reset.get("generator") != generator or
            reset.get("baselineWindowEndNs") != baseline["window_end_ns"]):
        raise ValueError("qualification proof reset identity/baseline mismatch")
    disabled_index = reset.get("disabledLineIndex")
    enabled_index = reset.get("enabledLineIndex")
    if (not isinstance(disabled_index, int) or
            not isinstance(enabled_index, int) or
            disabled_index < 0 or enabled_index <= disabled_index or
            enabled_index >= baseline["line_index"]):
        raise ValueError("qualification proof reset chronology is invalid")
    relevant = [event for event in events
                if event["pid"] == pid and event["generator"] == generator and
                disabled_index <= int(event["lineIndex"]) <= end["line_index"]]
    if (len(relevant) != 2 or
            int(relevant[0]["lineIndex"]) != disabled_index or
            relevant[0]["enabled"] is not False or
            int(relevant[1]["lineIndex"]) != enabled_index or
            relevant[1]["enabled"] is not True):
        raise ValueError(
            "qualification proof reset is missing, reordered, duplicated, or reused"
        )
    if any(event["proofContract"] != proof_contract or
           event["proofSchemaVersion"] != proof_schema_version
           for event in relevant):
        raise ValueError("qualification proof reset uses the wrong proof contract")
    if any(int(baseline[key]) != 0 for key in RESET_COUNTER_FIELDS):
        raise ValueError("qualification proof reset baseline counters are nonzero")
    if (proof_schema_version == DENSE_V34_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V34_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v34 diagnostic counters are nonzero")
    if (proof_schema_version == DENSE_V35_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V35_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v35 diagnostic counters are nonzero")
    if (proof_schema_version == DENSE_V36_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V36_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v36 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V37_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V37_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v37 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V38_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V38_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v38 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V39_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V39_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v39 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V40_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V40_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v40 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V41_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V41_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v41 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V42_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V42_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v42 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V43_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V43_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v43 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V44_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V44_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v44 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V45_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V45_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v45 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V46_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V46_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v46 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V47_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V47_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v47 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V48_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V48_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v48 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V49_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V49_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v49 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V50_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V50_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v50 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V51_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V51_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v51 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V54_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V54_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v54 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V55_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V55_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v55 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V56_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V56_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v56 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V57_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V57_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v57 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V58_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V58_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v58 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V59_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V59_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v59 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V60_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V60_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v60 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V61_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V61_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v61 evidence counters are nonzero")
    if (proof_schema_version == DENSE_V62_PROOF_SCHEMA_VERSION and
            any(int(baseline.get(key, -1)) != 0
                for key in V62_RESET_COUNTER_FIELDS)):
        raise ValueError(
            "qualification proof reset v62 evidence counters are nonzero")
    between = [record for record in records
               if enabled_index < record["line_index"] <= baseline["line_index"]]
    if between != [baseline]:
        raise ValueError(
            "qualification proof reset does not bind the first following HEALTH record"
        )
    return dict(reset)


def _validate_segment(
        segment: dict, records: list[dict]
) -> tuple[dict, dict, dict, list[dict], list[dict], dict]:
    kind = segment.get("kind")
    if kind not in ("steady", "transition"):
        raise ValueError("qualification segment kind must be steady or transition")
    for key in ("startWindowEndNs", "proofBaselineWindowEndNs", "endWindowEndNs"):
        if not isinstance(segment.get(key), int) or segment[key] <= 0:
            raise ValueError(f"qualification segment has invalid {key}")
    start = _record_at(records, segment["startWindowEndNs"], "start")
    proof_baseline = _record_at(
        records, segment["proofBaselineWindowEndNs"], "proof baseline")
    end = _record_at(records, segment["endWindowEndNs"], "end")
    if not (start["window_end_ns"] <= proof_baseline["window_end_ns"] <
            end["window_end_ns"]):
        raise ValueError("qualification segment health chronology is invalid")
    segment_records = [record for record in records
                       if start["window_end_ns"] <= record["window_end_ns"] <=
                       end["window_end_ns"]]
    proof_records = [record for record in records
                     if proof_baseline["window_end_ns"] < record["window_end_ns"] <=
                     end["window_end_ns"]]
    if len(proof_records) < 2:
        raise ValueError("qualification segment has too few post-baseline health records")
    max_fallback = segment.get("maxFallbackPresents")
    if not isinstance(max_fallback, int) or max_fallback < 0:
        raise ValueError("qualification segment has invalid fallback allowance")

    if end.get("proof_schema_version") in (
            DENSE_V36_PROOF_SCHEMA_VERSION, DENSE_V37_PROOF_SCHEMA_VERSION,
            DENSE_V38_PROOF_SCHEMA_VERSION, DENSE_V39_PROOF_SCHEMA_VERSION,
            DENSE_V40_PROOF_SCHEMA_VERSION, DENSE_V41_PROOF_SCHEMA_VERSION,
            DENSE_V42_PROOF_SCHEMA_VERSION, DENSE_V43_PROOF_SCHEMA_VERSION,
            DENSE_V44_PROOF_SCHEMA_VERSION, DENSE_V45_PROOF_SCHEMA_VERSION,
            DENSE_V46_PROOF_SCHEMA_VERSION, DENSE_V47_PROOF_SCHEMA_VERSION,
            DENSE_V48_PROOF_SCHEMA_VERSION, DENSE_V49_PROOF_SCHEMA_VERSION,
            DENSE_V50_PROOF_SCHEMA_VERSION, DENSE_V51_PROOF_SCHEMA_VERSION,
            DENSE_V54_PROOF_SCHEMA_VERSION, DENSE_V55_PROOF_SCHEMA_VERSION,
            DENSE_V56_PROOF_SCHEMA_VERSION, DENSE_V57_PROOF_SCHEMA_VERSION,
            DENSE_V58_PROOF_SCHEMA_VERSION, DENSE_V59_PROOF_SCHEMA_VERSION,
            DENSE_V60_PROOF_SCHEMA_VERSION, DENSE_V61_PROOF_SCHEMA_VERSION,
            DENSE_V62_PROOF_SCHEMA_VERSION):
        expected_epoch = segment.get("expectedPresentationEpoch")
        if not isinstance(expected_epoch, int) or expected_epoch <= 0:
            raise ValueError(
                "epoch-bound segment has no expected presentation epoch")
        epoch_records = (segment_records if kind == "steady" else
                         [proof_baseline] + proof_records)
        if any(record.get("window_presentation_epoch") != expected_epoch or
               record.get("proof_evidence_presentation_epoch") != expected_epoch
               for record in epoch_records):
            raise ValueError(
                "epoch-bound segment mixes presentation evidence epochs")
    if end.get("proof_schema_version") in (
            DENSE_V43_PROOF_SCHEMA_VERSION, DENSE_V44_PROOF_SCHEMA_VERSION,
            DENSE_V45_PROOF_SCHEMA_VERSION, DENSE_V46_PROOF_SCHEMA_VERSION,
            DENSE_V47_PROOF_SCHEMA_VERSION, DENSE_V48_PROOF_SCHEMA_VERSION,
            DENSE_V49_PROOF_SCHEMA_VERSION, DENSE_V50_PROOF_SCHEMA_VERSION,
            DENSE_V51_PROOF_SCHEMA_VERSION, DENSE_V54_PROOF_SCHEMA_VERSION,
            DENSE_V55_PROOF_SCHEMA_VERSION, DENSE_V56_PROOF_SCHEMA_VERSION,
            DENSE_V57_PROOF_SCHEMA_VERSION, DENSE_V58_PROOF_SCHEMA_VERSION,
            DENSE_V59_PROOF_SCHEMA_VERSION, DENSE_V60_PROOF_SCHEMA_VERSION,
            DENSE_V61_PROOF_SCHEMA_VERSION,
            DENSE_V62_PROOF_SCHEMA_VERSION):
        clock_failures = _v43_segment_clock_hierarchy(segment_records)
        if clock_failures:
            raise ValueError("; ".join(clock_failures))

    if kind == "steady":
        tier = segment.get("expectedLockedFps")
        if tier not in (20, 30, 40, 50, 60):
            raise ValueError("steady segment has invalid expected tier")
        if any(record["locked"] != tier for record in segment_records):
            raise ValueError("steady segment mixes source tiers")
        transition = {"kind": kind, "expectedLockedFps": tier}
    else:
        from_tier = segment.get("expectedFromFps")
        to_tier = segment.get("expectedToFps")
        maximum_ms = segment.get("maxTransitionMs")
        if from_tier not in (20, 30, 40, 50, 60) or to_tier not in (20, 30, 40, 50, 60) or \
                from_tier == to_tier or not isinstance(maximum_ms, int) or maximum_ms <= 0:
            raise ValueError("transition segment has invalid tier contract")
        if start["locked"] != from_tier or proof_baseline["locked"] != to_tier:
            raise ValueError("transition segment endpoints do not match declared tiers")
        target_records = [record for record in segment_records if record["locked"] == to_tier]
        if (not target_records or
                (segment.get("proofReset") is None and
                 target_records[0]["window_end_ns"] !=
                 proof_baseline["window_end_ns"])):
            raise ValueError("transition proof baseline is not the first target-tier window")
        before_target = [record for record in segment_records
                         if record["window_end_ns"] < proof_baseline["window_end_ns"]]
        direction = 1 if to_tier > from_tier else -1
        ordered = [record["locked"] for record in before_target] + [to_tier]
        if any(value not in (20, 30, 40, 50, 60) for value in ordered) or any(
                (right - left) * direction < 0 for left, right in zip(ordered, ordered[1:])):
            raise ValueError("transition tier sequence reverses or leaves supported tiers")
        if any(record["locked"] != to_tier for record in proof_records):
            raise ValueError("transition segment did not remain settled at its target tier")
        elapsed_ms = (proof_baseline["window_end_ns"] - start["window_end_ns"]) / 1_000_000.0
        if elapsed_ms > maximum_ms:
            raise ValueError("transition exceeded its declared settling bound")
        transition = {
            "kind": kind,
            "expectedFromFps": from_tier,
            "expectedToFps": to_tier,
            "settlingMs": elapsed_ms,
            "maxTransitionMs": maximum_ms,
        }
    return start, proof_baseline, end, segment_records, proof_records, transition


def parse_latency(path: Path) -> dict:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if len(lines) < 32:
        raise ValueError("SurfaceFlinger evidence has fewer than 31 frames")
    refresh_ns = int(lines[0])
    # FrameTracker::dumpStats writes, in order:
    #   desiredPresentTime actualPresentTime frameReadyTime
    # Only actualPresentTime proves when the buffer became visible.  Desired
    # timestamps are an application/SF scheduling request and can advance at
    # 120 Hz even when presentation is missing frames.
    #
    # A pending present fence is represented by INT64_MAX and is not evidence.
    maximum_timestamp = (1 << 63) - 1
    rows = [line.split() for line in lines[1:]]
    timestamps = [int(columns[1]) for columns in rows
                  if len(columns) >= 3 and
                  0 < int(columns[1]) < maximum_timestamp]
    if len(timestamps) < 31:
        raise ValueError("SurfaceFlinger evidence has fewer than 31 valid timestamps")
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    if not deltas:
        raise ValueError("SurfaceFlinger timestamps did not advance")
    if any(delta <= 0 for delta in deltas):
        raise ValueError("SurfaceFlinger actual-present timestamps are not monotonic")
    mean_ns = sum(deltas) / len(deltas)
    target_hz = 1_000_000_000.0 / refresh_ns
    measured_hz = 1_000_000_000.0 / mean_ns
    on_time = sum(refresh_ns * 0.5 <= delta <= refresh_ns * 1.5
                  for delta in deltas)
    return {
        "frames": len(timestamps),
        "targetHz": target_hz,
        "measuredHz": measured_hz,
        "meanDeltaMs": mean_ns / 1_000_000.0,
        "onTimeFraction": on_time / len(deltas),
        "firstActualPresentNs": timestamps[0],
        "lastActualPresentNs": timestamps[-1],
        "actualPresentTimestamps": timestamps,
    }


def _panel_quantized_latch_cadence(timestamps: list[int], panel_fps: int,
                                   output_fps: int) -> dict:
    """Validate fractional output as a balanced subset of physical vsyncs.

    A 100-FPS producer on a fixed 120-Hz panel cannot latch every 10 ms. Its
    honest cadence is four one-vsync intervals and one two-vsync interval per
    five presents. Likewise, 80 on 120 alternates one and two vsyncs. Checking
    each delta against an ideal output period either rejects those valid
    schedules or becomes loose enough to accept genuine misses. Instead, bind
    every latch to a physical-vsync quantum and require the floor/ceil choices
    to remain a balanced accumulator (at most one tick of phase excursion).
    """
    if len(timestamps) < 2 or panel_fps <= 0 or output_fps <= 0:
        return {"valid": False, "quantizedFraction": 0.0,
                "phaseExcursionTicks": float("inf"), "intervalTicks": []}
    panel_period_ns = 1_000_000_000.0 / panel_fps
    ratio = panel_fps / output_fps
    lower = max(1, int(math.floor(ratio + 1e-9)))
    upper = max(lower, int(math.ceil(ratio - 1e-9)))
    ticks = []
    quantized = 0
    for left, right in zip(timestamps, timestamps[1:]):
        measured = (right - left) / panel_period_ns
        nearest = max(1, int(round(measured)))
        ticks.append(nearest)
        if abs(measured - nearest) <= 0.20 and nearest in (lower, upper):
            quantized += 1
    residual = 0.0
    residuals = [0.0]
    for tick in ticks:
        residual += tick - ratio
        residuals.append(residual)
    excursion = max(residuals) - min(residuals)
    fraction = quantized / len(ticks) if ticks else 0.0
    return {
        "valid": fraction == 1.0 and excursion <= 1.05,
        "quantizedFraction": fraction,
        "phaseExcursionTicks": excursion,
        "intervalTicks": ticks,
    }


def _max_generation_factor(record: dict) -> int:
    """Integer generation ceiling for a record's evidence contract.

    v62 (tier protocol 2026-09-01) triples the 20 and 40 tiers onto the exact
    60/120 scan lattices; every earlier contract kept the strict x2 ceiling.
    """
    schema = record.get("proof_schema_version")
    contract = record.get("proof_contract")
    if (isinstance(schema, int) and schema >= DENSE_V62_PROOF_SCHEMA_VERSION) \
            or contract == DENSE_V62_PROOF_CONTRACT:
        return MAX_GENERATION_FACTOR_V62
    return 2


def _schema36_output_fps(panel_fps: int, source_fps: int) -> int:
    """Mirror the controller's fixed-panel rational output policy."""
    doubled = min(panel_fps, source_fps * 2)
    if panel_fps == 120 and 30 <= source_fps < 60:
        return 60
    return doubled


def _schema37_output_fps(panel_fps: int, source_fps: int) -> int:
    """Timestamped adaptive generation uses the exact panel-capped x2 target.

    The goal's map: on 120 Hz, 20/30/40/50/60 → 40/60/80/100/120; on 60 Hz
    nothing exceeds 60. Restored by the 2026-08-17 audit — an uncommitted
    change had narrowed generation to panel-native 60/120 only, silently
    denying 20/40/50-tier games any generated frames, contradicting the
    goal text and the physical passes (nds13 20→40, n3ds4 40→80, wiiu15
    50→100 lattice)."""
    return min(panel_fps, source_fps * 2)


def _schema42_output_fps(panel_fps: int, source_fps: int) -> int:
    """Highest max-2x output with an integer number of panel scans."""
    maximum = min(panel_fps, source_fps * 2)
    for candidate in range(maximum, source_fps - 1, -1):
        if panel_fps % candidate == 0:
            return candidate
    return min(panel_fps, source_fps)


def _v43_rational_clock_hierarchy(record: dict) -> list[str]:
    """Bind exact millihertz clocks to one integer panel-scan divisor."""
    failures: list[str] = []
    source = record.get("source_millihz", 0)
    target = record.get("target_millihz", 0)
    panel = record.get("panel_millihz", 0)
    scans = record.get("panel_scans_per_output", 0)
    if min(source, target, panel) <= 0 or scans < 0:
        failures.append("schema43 rational clock identity is absent")
        return failures
    # Acquisition/fallback records are deliberately truthful rather than
    # inventing an integer divisor for an unqualified direct source clock.
    # They must remain parseable so a later same-session qualified segment can
    # be selected, but the final qualification gate below still requires the
    # exact positive divisor/qualified form.
    if record.get("uniform_output_qualified") == 0:
        if scans != 0 or target != source:
            failures.append(
                "schema43 unqualified direct clock is internally inconsistent")
        # The integer label and the millihertz clock are rounded separately
        # (a 37.4999-Hz direct source labels 37 while its clock rounds to
        # 37500); allow that one-unit boundary residue on unqualified records
        # so a loading-screen window cannot poison the whole log (gc-b23).
        if abs(record.get("output", 0) -
               int(math.floor(target / 1000.0 + 0.5))) > 1:
            failures.append(
                "schema43 unqualified output label disagrees with its source")
        if record.get("panel") != int(math.floor(panel / 1000.0 + 0.5)):
            failures.append(
                "schema43 integer panel label disagrees with exact panel")
        elapsed_ms = record.get("window_ms", 0)
        expected_swap = (0 if elapsed_ms <= 0 else int(math.floor(
            record.get("window_presents", 0) * 1_000_000.0 /
            elapsed_ms + 0.5)))
        if record.get("window_swap_millihz") != expected_swap:
            failures.append(
                "schema43 realized swap clock disagrees with its window")
        if record.get("source_clock_kind") not in ("auth", "pts"):
            failures.append("schema43 source clock authority is absent")
        return failures
    if scans <= 0:
        failures.append("schema43 qualified panel-scan divisor is absent")
        return failures
    # Each logged clock was independently rounded to one millihertz. Permit
    # only the aggregate rounding residue, never a cadence-policy tolerance.
    if abs(target * scans - panel) > scans + 1:
        failures.append("schema43 target is not an integer panel-scan divisor")
    if target + 1 < source:
        failures.append("schema43 target is below its measured source")
    factor = _max_generation_factor(record)
    if target > min(panel, source * factor) + 2:
        failures.append(
            f"schema43 target exceeds panel or strict max{factor}x")
    if record.get("uniform_output_qualified") != 1:
        failures.append("schema43 uniform output is not qualified")
    if record.get("output") != int(math.floor(target / 1000.0 + 0.5)):
        failures.append("schema43 integer output label disagrees with exact target")
    if record.get("panel") != int(math.floor(panel / 1000.0 + 0.5)):
        failures.append("schema43 integer panel label disagrees with exact panel")
    elapsed_ms = record.get("window_ms", 0)
    expected_swap = (0 if elapsed_ms <= 0 else int(math.floor(
        record.get("window_presents", 0) * 1_000_000.0 / elapsed_ms + 0.5)))
    if record.get("window_swap_millihz") != expected_swap:
        failures.append("schema43 realized swap clock disagrees with its window")
    if record.get("source_clock_kind") not in ("auth", "pts"):
        failures.append("schema43 source clock authority is absent")
    return failures


def _v43_segment_clock_hierarchy(records: list[dict]) -> list[str]:
    """Require one stable rational clock identity across a proof segment."""
    if not records:
        return ["schema43 rational clock segment is empty"]
    identity = {
        (record.get("target_millihz"), record.get("panel_millihz"),
         record.get("panel_scans_per_output"),
         record.get("source_clock_kind"))
        for record in records
    }
    failures: list[str] = []
    if len(identity) != 1:
        failures.append("schema43 proof segment mixes rational clock identities")
    sources = [record.get("source_millihz", 0) for record in records]
    if any(source <= 0 for source in sources):
        failures.append("schema43 proof segment lacks source-clock evidence")
    else:
        # A stable measured clock naturally moves by a few millihertz as the
        # complete timestamp window slides.  Half a percent admits that
        # measurement residue while rejecting a 57-59-Hz stream whose mean
        # happens to sit near a nominal60 label.
        allowed_spread = max(50, int(round(sum(sources) / len(sources) * .005)))
        if max(sources) - min(sources) > allowed_spread:
            failures.append("schema43 source clock is not stable across the proof segment")
    return failures


def _motion_content_failures(values: dict[str, int], *,
                             vector_trajectory_contract: bool) -> list[str]:
    """Validate motion proof without conflating translation with color mixing.

    Schema 38's independent vector oracle proves that the synthesized pixel
    followed the selected motion vector.  A correctly translated opaque edge
    may still equal one endpoint at its fixed screen coordinate, so the older
    fixed-coordinate ``substantive`` predicate is diagnostic only for v38.
    Non-crossfade and vector-trajectory evidence remain mandatory.
    """
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    require(values["eligible_pixels"] >= 500,
            "too few genuinely changing pixels were sampled")
    if not vector_trajectory_contract:
        require(values["substantive_pixels"] >=
                values["eligible_pixels"] * 0.50,
                "synthetic pixels do not materially depart from both endpoints")
    require(values["non_crossfade_pixels"] >=
            values["eligible_pixels"] * 0.50,
            "most synthetic output is indistinguishable from fixed-pixel crossfade")
    require(values["motion_eligible_samples"] >= 10,
            "too few synthesized samples contain measurable selected motion")
    require(values["correlated_samples"] >= max(
            10, values["motion_eligible_samples"] * 0.35),
            ("independent vector trajectory and non-crossfade output are not correlated"
             if vector_trajectory_contract else
             "motion field and non-crossfade synthetic output are not correlated"))
    require(values["motion_eligible_pixels"] >= 500,
            "too few changing pixels have a confident selected motion vector")
    require(values["motion_synthesized_pixels"] >=
            values["motion_eligible_pixels"] * 0.55,
            "motion-compensated pixels do not spatially follow their selected vectors")
    return failures


def _schema36_rational_rates(source_fps: int, output_fps: int) -> tuple[int, int]:
    """Return exact-real and synthetic rates on one reduced output lattice."""
    exact_real_fps = math.gcd(source_fps, output_fps)
    return exact_real_fps, output_fps - exact_real_fps


def _rational_visible_accounting(
        proof_records: list[dict], values: dict) -> tuple[int, int, int]:
    """Classify successful rational/timestamped swaps without source double-counting."""
    window_classified = (values["window_generated"] +
                         values["window_real_priority"])
    segment_fallback = sum(
        record["window_presents"] - record["window_generated"] -
        record["window_real_priority"] for record in proof_records
    )
    return window_classified, segment_fallback, values["presents"] - segment_fallback


def _window_completed_output_meets_cadence(record: dict[str, object]) -> bool:
    """True when successful swaps meet the unchanged 96% output floor."""
    elapsed_ns = (int(record["window_end_ns"]) -
                  int(record["window_start_ns"]))
    output = int(record["output"])
    presents = int(record["window_presents"])
    return (elapsed_ns > 0 and output > 0 and
            presents * 1_000_000_000 * 100 >=
            output * elapsed_ns * 96)


def _segment_endpoint_backlogs_valid(
        baseline: dict, end: dict, segment: dict) -> bool:
    """Conserve accepted/uploaded endpoints across a rebased segment.

    A settled-tier baseline may already retain an accepted endpoint awaiting a
    later REAL slot, or an uploaded candidate awaiting unique classification.
    Consequently a segment can legitimately promote one more endpoint than it
    accepts (or accept one more than it uploads) while both lifetime snapshots
    remain ordered.  Model those opening and closing backlogs explicitly rather
    than incorrectly treating rebased cumulative counters as same-window
    subsets.
    """
    opening_unpromoted = baseline["real"] - baseline["promoted"]
    closing_unpromoted = end["real"] - end["promoted"]
    opening_unclassified = baseline["submitted"] - baseline["real"]
    closing_unclassified = end["submitted"] - end["real"]
    if min(opening_unpromoted, closing_unpromoted,
           opening_unclassified, closing_unclassified) < 0:
        return False
    return (
        opening_unpromoted + segment["real"] ==
            segment["promoted"] + closing_unpromoted and
        opening_unclassified + segment["submitted"] ==
            segment["real"] + closing_unclassified
    )


def _v36_output_accounting_hierarchy(record: dict) -> list[str]:
    """Validate schema36 output decisions without treating inputs as swaps."""
    failures: list[str] = []
    expected_output = _schema36_output_fps(record["panel"], record["locked"])
    if record["output"] != expected_output:
        failures.append("v36 output does not match the rational panel policy")
    if (record["window_presents"] !=
            record["window_real_priority"] + record["window_generated"]):
        failures.append("v36 successful output accounting is impossible")
    if record["window_generated"] != record["window_synthetic_selected"]:
        failures.append("v36 generated/synthetic-selected accounting differs")
    if record["window_generated"] > record["window_promoted"]:
        failures.append("v36 generated output exceeds promoted input")
    if (record["window_synthetic_quota_opening"] +
            record["window_synthetic_pair_created"] !=
            record["window_synthetic_selected"] +
            record["window_synthetic_quota_skipped"] +
            record["synthetic_quota_pending"]):
        failures.append("v36 pair conservation is impossible")
    return failures


def _v37_output_accounting_hierarchy(record: dict) -> list[str]:
    """Validate successful swaps from a timestamp-resampled source timeline."""
    failures: list[str] = []
    # Direct helper tests and decoded pre-v42 records predate the schema key.
    # Absence therefore means the v37-v41 policy; only an explicit v42 token
    # may select the uniform-divisor mapping.
    expected_output = (int(math.floor(
        record.get("target_millihz", 0) / 1000.0 + 0.5))
        if record.get("proof_schema_version") in (
            DENSE_V43_PROOF_SCHEMA_VERSION, DENSE_V44_PROOF_SCHEMA_VERSION,
            DENSE_V45_PROOF_SCHEMA_VERSION, DENSE_V46_PROOF_SCHEMA_VERSION,
            DENSE_V47_PROOF_SCHEMA_VERSION, DENSE_V48_PROOF_SCHEMA_VERSION,
            DENSE_V49_PROOF_SCHEMA_VERSION, DENSE_V50_PROOF_SCHEMA_VERSION,
            DENSE_V51_PROOF_SCHEMA_VERSION, DENSE_V54_PROOF_SCHEMA_VERSION,
            DENSE_V55_PROOF_SCHEMA_VERSION, DENSE_V56_PROOF_SCHEMA_VERSION,
            DENSE_V57_PROOF_SCHEMA_VERSION, DENSE_V58_PROOF_SCHEMA_VERSION,
            DENSE_V59_PROOF_SCHEMA_VERSION, DENSE_V60_PROOF_SCHEMA_VERSION,
            DENSE_V61_PROOF_SCHEMA_VERSION,
            DENSE_V62_PROOF_SCHEMA_VERSION)
        else _schema42_output_fps(record["panel"], record["locked"])
        if record.get("proof_schema_version") == DENSE_V42_PROOF_SCHEMA_VERSION
        else _schema37_output_fps(record["panel"], record["locked"]))
    # The engine has exactly two truthful policy states: the panel-capped x2
    # target under sustainable generation, and panel-capped 1x passthrough
    # while generation is unavailable or the tier is still acquiring
    # (melonDS armed proof mid-acquisition with lockedFps=51 outputFps=51,
    # run nds1 2026-08-17 — a legitimate 1x window, not impossible HEALTH).
    # Any other value remains impossible. The steady-segment validation
    # separately requires the strict x2 form with an audited tier lock, so a
    # 1x window can never qualify as generation evidence.
    passthrough_output = min(record["panel"], record["locked"])
    # Unqualified direct windows carry the separately rounded integer label
    # of a fractional measured clock; allow the one-unit boundary residue.
    if (record["output"] not in (expected_output, passthrough_output) and
            not (record.get("uniform_output_qualified") == 0 and
                 abs(record["output"] - expected_output) <= 1)):
        failures.append("timestamp-resampled output does not match its panel policy")
    if (record["window_presents"] !=
            record["window_real_priority"] + record["window_generated"]):
        failures.append("v37 successful output accounting is impossible")
    if record["window_generated"] != record["window_synthetic_selected"]:
        failures.append("v37 generated/synthetic-selected accounting differs")
    # HEALTH windows are cut on successful-present boundaries, independently
    # of the producer FIFO.  A window can therefore open with the active pair
    # and all four queued endpoints accepted before its baseline.  Bound that
    # carry by the renderer's exact finite ownership capacity here; the
    # selected >=11-second segment below applies the same allowance only once,
    # so repeated windows cannot manufacture a sustained rate above 2x.
    # (2026-09-02) Slot-lattice producers bridge dropped guest frames by
    # interpolation, so a window can present more than factor x consumed
    # endpoints while never exceeding the OUTPUT LATTICE itself: bound such
    # windows by the lattice (output x elapsed) plus the retained allowance
    # instead.  The lattice bound still forbids any sustained rate above the
    # contract factor of the locked source tier.
    lattice_window_cap = None
    try:
        elapsed_ns = int(record["window_end_ns"]) - int(record["window_start_ns"])
        if elapsed_ns > 0 and record.get("output"):
            lattice_window_cap = (int(record["output"]) * elapsed_ns /
                                  1_000_000_000.0 * 1.02 +
                                  V37_MAX_RETAINED_ENDPOINTS)
    except (KeyError, TypeError, ValueError):
        lattice_window_cap = None
    if record["window_presents"] > _max_generation_factor(record) * (
            record["window_promoted"] + V37_MAX_RETAINED_ENDPOINTS) and (
            lattice_window_cap is None or
            record["window_presents"] > lattice_window_cap):
        failures.append(
            "v37 output exceeds its contract factor of consumed source evidence")
    if record["window_duplicate_pair_selection"] != 0:
        failures.append("v37 repeated a producer-clock sample")
    # A missed lookahead slot is a recoverable epoch boundary, not malformed
    # telemetry. Qualification below still requires every post-baseline record
    # in the selected steady epoch to contain zero such slots.
    return failures


def _v37_segment_source_evidence_valid(values: dict) -> bool:
    """Bound output by consumed endpoints plus the renderer's retained FIFO."""
    return values["presents"] <= _max_generation_factor(values) * (
        values["promoted"] + V37_MAX_RETAINED_ENDPOINTS)


def _segment_dense_timer_pairs_valid(baseline: dict, end: dict,
                                     segment: dict) -> bool:
    """Conserve estimator pairs that straddle the segment boundary.

    ``dense_promotions - dense_timed_pairs`` is the number of submitted
    endpoint estimators whose five stage queries have not all completed yet.
    A healthy asynchronous timer commonly has one such pair at a HEALTH
    boundary.  Subtracting lifetime counters can therefore yield one more
    completion than new promotion when that opening pair completes inside the
    selected segment.  Bind that carry exactly instead of weakening the pair
    count with an arbitrary allowance.
    """
    opening = baseline["dense_promotions"] - baseline["dense_timed_pairs"]
    closing = end["dense_promotions"] - end["dense_timed_pairs"]
    return (
        0 <= opening <= baseline["dense_timer_pending"] and
        0 <= closing <= end["dense_timer_pending"] and
        segment["dense_timed_pairs"] + closing ==
            segment["dense_promotions"] + opening
    )


def _segment_async_atlas_completion_valid(values: dict) -> bool:
    """Accept completed proof while retaining bounded next-sample work.

    Qualification starts only from a baseline with an empty atlas ring.  At
    the end HEALTH callback, however, the producer may already have enqueued
    the next proof sample.  That request has not contributed to any decoded
    proof/quality counter, so requiring the nonblocking ring to be empty is a
    race.  Completed samples must still equal analyzed proof exactly and every
    additional enqueue must be represented by a bounded pending slot.
    """
    return (
        values["dense_proof_atlas_completed"] == values["proof"] and
        0 <= values["dense_proof_atlas_pending"] <= 4 and
        values["dense_proof_atlas_enqueued"] ==
            values["dense_proof_atlas_completed"] +
            values["dense_proof_atlas_pending"]
    )


def _segment_relative_counters(end: dict, baseline: dict,
                               cumulative_keys: tuple[str, ...], *,
                               asynchronous_atlas: bool) -> tuple[dict, dict, list[str]]:
    """Rebase one segment without mutating its absolute end telemetry."""
    values = dict(end)
    absolute_values = dict(end)
    failures: list[str] = []
    if asynchronous_atlas and baseline["dense_proof_atlas_pending"] != 0:
        failures.append(
            "proof baseline has pending asynchronous proof-atlas work"
        )
    for key in cumulative_keys:
        values[key] -= baseline[key]
        if values[key] < 0:
            failures.append(f"segment-relative counter is negative: {key}")
    if (asynchronous_atlas and
            values["dense_proof_atlas_enqueued"] !=
            values["dense_proof_atlas_completed"] +
            values["dense_proof_atlas_pending"]):
        failures.append(
            "segment-relative proof-atlas conservation is impossible"
        )
    return values, absolute_values, failures


def _diagnostic_empty_reset_snapshot(record: dict, *, v35: bool) -> bool:
    """True only for the exact zero-work HEALTH emitted on proof reset."""
    zero_fields = [
        "window_presents", "proof", "dense_proof_cells",
        "dense_diagnostic_cells", "dense_diagnostic_tiles",
        "dense_proof_atlas_enqueued", "dense_proof_atlas_completed",
        "dense_proof_atlas_pending", "dense_promotions",
        "dense_diagnostic_mask_errors",
        "dense_diagnostic_last_atlas_sequence",
        "dense_diagnostic_last_pair_sequence",
        "dense_diagnostic_last_previous_endpoint",
        "dense_diagnostic_last_current_endpoint",
    ]
    for direction in ("backward", "forward"):
        zero_fields.extend(f"dense_{direction}_{suffix}" for suffix in (
            "valid", "active", "in_bounds", "cycle_valid",
            "photometric_valid", "texture_valid", "saturated",
            "out_of_bounds", "covered_tiles", "covered_tile_mask"))
    if v35:
        zero_fields.extend((
            "dense_diagnostic_packed_cells",
            "dense_diagnostic_partition_errors",
            "dense_diagnostic_reserved_bit_errors",
        ))
    return all(record.get(key) == 0 for key in zero_fields)


def _v34_diagnostic_hierarchy(record: dict, *,
                              segment_relative: bool = False) -> list[str]:
    """Validate the immutable per-atlas funnel and binding contract."""
    diagnostic_failures: list[str] = []
    cells = record["dense_diagnostic_cells"]
    tiles = record["dense_diagnostic_tiles"]
    expected_proof = record["proof"]
    if record["dense_proof_atlas_layout"] != 2:
        diagnostic_failures.append("v34 diagnostic atlas layout is not version 2")
    callbacks = record["window_presentation_callbacks"]
    if (callbacks < record["window_presents"] or
            (callbacks == 0 and not _diagnostic_empty_reset_snapshot(
                record, v35=False))):
        diagnostic_failures.append(
            "v34 presentation callback window is absent or impossible")
    if cells != expected_proof * DENSE_PROOF_CELLS:
        diagnostic_failures.append(
            "v34 diagnostic cells do not cover every proof sample")
    if tiles != expected_proof * 18:
        diagnostic_failures.append(
            "v34 diagnostic tiles do not cover every proof sample")
    if record["dense_proof_cells"] != cells:
        diagnostic_failures.append(
            "v34 diagnostic and validated-flow cell populations differ")
    if record["dense_diagnostic_mask_errors"] != 0:
        diagnostic_failures.append("v34 diagnostic mask reserved bit is set")
    for direction in ("backward", "forward"):
        counts = [record[f"dense_{direction}_{suffix}"] for suffix in (
            "active", "in_bounds", "cycle_valid", "photometric_valid",
            "texture_valid", "saturated", "out_of_bounds")]
        if any(count < 0 or count > cells for count in counts):
            diagnostic_failures.append(
                f"v34 {direction} diagnostic count exceeds its population")
        if (record[f"dense_{direction}_in_bounds"] +
                record[f"dense_{direction}_out_of_bounds"] != cells):
            diagnostic_failures.append(
                f"v34 {direction} in-bounds/OOB partition is impossible")
        valid = record[f"dense_{direction}_valid"]
        # Alpha factor bits use the conservative UNORM code-47 floor. They
        # are necessary prerequisites for an actual returned B byte >=48,
        # not independent copies of final validity; only this one-way subset
        # relationship is guaranteed across the half-LSB conversion boundary.
        if any(valid > record[f"dense_{direction}_{suffix}"] for suffix in (
                "active", "in_bounds", "cycle_valid",
                "photometric_valid", "texture_valid")):
            diagnostic_failures.append(
                f"v34 {direction} valid cells exceed a prerequisite funnel")
        covered = record[f"dense_{direction}_covered_tiles"]
        mask = record[f"dense_{direction}_covered_tile_mask"]
        if covered < 0 or covered > tiles:
            diagnostic_failures.append(
                f"v34 {direction} covered-tile count is impossible")
        if mask < 0 or mask >= (1 << 18):
            diagnostic_failures.append(
                f"v34 {direction} covered-tile mask exceeds 18 tiles")
        elif (not segment_relative and
              bin(mask).count("1") > min(18, covered)):
            diagnostic_failures.append(
                f"v34 {direction} covered-tile mask exceeds its count")
    # Last IDs are absolute gauges, not segment-relative counters. They are
    # checked only against absolute records, never after baseline subtraction.
    if not segment_relative:
        if expected_proof == 0:
            last_values = (
                record["dense_diagnostic_last_atlas_sequence"],
                record["dense_diagnostic_last_pair_sequence"],
                record["dense_diagnostic_last_previous_endpoint"],
                record["dense_diagnostic_last_current_endpoint"],
            )
            if any(last_values):
                diagnostic_failures.append(
                    "v34 diagnostic binding survives an empty/reset proof epoch")
        else:
            previous_endpoint = record[
                "dense_diagnostic_last_previous_endpoint"]
            current_endpoint = record[
                "dense_diagnostic_last_current_endpoint"]
            if (record["dense_diagnostic_last_atlas_sequence"] !=
                    record["dense_proof_atlas_completed"]):
                diagnostic_failures.append(
                    "v34 diagnostic atlas binding does not match completion")
            if not (0 < record["dense_diagnostic_last_pair_sequence"] <=
                    record["dense_promotions"]):
                diagnostic_failures.append(
                    "v34 diagnostic pair binding is impossible")
            if not (0 < previous_endpoint < current_endpoint <=
                    record["promoted"] and
                    current_endpoint == previous_endpoint + 1):
                diagnostic_failures.append(
                    "v34 diagnostic endpoint binding is impossible")
    return diagnostic_failures


def _v35_diagnostic_hierarchy(record: dict, *,
                              segment_relative: bool = False) -> list[str]:
    """Validate layout-3's nearest mask independently from linear B."""
    failures: list[str] = []
    cells = record["dense_diagnostic_cells"]
    tiles = record["dense_diagnostic_tiles"]
    expected_proof = record["proof"]
    if record["dense_proof_atlas_layout"] != 3:
        failures.append("v35 diagnostic atlas layout is not version 3")
    if record.get("dense_diagnostic_mask_layout") != "packed-nearest-bf-v1":
        failures.append("v35 diagnostic mask transport is not packed nearest")
    callbacks = record["window_presentation_callbacks"]
    if (callbacks < record["window_presents"] or
            (callbacks == 0 and not _diagnostic_empty_reset_snapshot(
                record, v35=True))):
        failures.append(
            "v35 presentation callback window is absent or impossible")
    if cells != expected_proof * DENSE_PROOF_CELLS:
        failures.append(
            "v35 diagnostic cells do not cover every proof sample")
    if record["dense_diagnostic_packed_cells"] != cells:
        failures.append(
            "v35 packed-mask cells do not match the diagnostic population")
    if tiles != expected_proof * 18:
        failures.append(
            "v35 diagnostic tiles do not cover every proof sample")
    if record["dense_proof_cells"] != cells:
        failures.append(
            "v35 diagnostic and linear validated-flow populations differ")
    if (record["dense_diagnostic_partition_errors"] != 0 or
            record["dense_diagnostic_reserved_bit_errors"] != 0 or
            record["dense_diagnostic_mask_errors"] != 0):
        failures.append("v35 packed diagnostic mask is malformed")
    for direction in ("backward", "forward"):
        counts = [record[f"dense_{direction}_{suffix}"] for suffix in (
            "active", "in_bounds", "cycle_valid", "photometric_valid",
            "texture_valid", "saturated", "out_of_bounds")]
        if any(count < 0 or count > cells for count in counts):
            failures.append(
                f"v35 {direction} diagnostic count exceeds its population")
        if (record[f"dense_{direction}_in_bounds"] +
                record[f"dense_{direction}_out_of_bounds"] != cells):
            failures.append(
                f"v35 {direction} in-bounds/OOB partition is impossible")
        # Final validity is the unchanged LINEAR B byte and is intentionally
        # not compared to the separately NEAREST factor bits. The exact 50%
        # B-content gate remains below; cross-sampling subset claims are not
        # mathematically valid.
        valid = record[f"dense_{direction}_valid"]
        if valid < 0 or valid > cells:
            failures.append(
                f"v35 {direction} linear valid count exceeds its population")
        covered = record[f"dense_{direction}_covered_tiles"]
        mask = record[f"dense_{direction}_covered_tile_mask"]
        if covered < 0 or covered > tiles:
            failures.append(
                f"v35 {direction} covered-tile count is impossible")
        if mask < 0 or mask >= (1 << 18):
            failures.append(
                f"v35 {direction} covered-tile mask exceeds 18 tiles")
        elif (not segment_relative and
              bin(mask).count("1") > min(18, covered)):
            failures.append(
                f"v35 {direction} covered-tile mask exceeds its count")
    if not segment_relative:
        if expected_proof == 0:
            last_values = (
                record["dense_diagnostic_last_atlas_sequence"],
                record["dense_diagnostic_last_pair_sequence"],
                record["dense_diagnostic_last_previous_endpoint"],
                record["dense_diagnostic_last_current_endpoint"],
            )
            if any(last_values):
                failures.append(
                    "v35 diagnostic binding survives an empty/reset proof epoch")
        else:
            previous_endpoint = record[
                "dense_diagnostic_last_previous_endpoint"]
            current_endpoint = record[
                "dense_diagnostic_last_current_endpoint"]
            if (record["dense_diagnostic_last_atlas_sequence"] !=
                    record["dense_proof_atlas_completed"]):
                failures.append(
                    "v35 diagnostic atlas binding does not match completion")
            if not (0 < record["dense_diagnostic_last_pair_sequence"] <=
                    record["dense_promotions"]):
                failures.append(
                    "v35 diagnostic pair binding is impossible")
            if not (0 < previous_endpoint < current_endpoint <=
                    record["promoted"] and
                    current_endpoint == previous_endpoint + 1):
                failures.append(
                    "v35 diagnostic endpoint binding is impossible")
    return failures


def _v36_diagnostic_hierarchy(record: dict, *,
                              segment_relative: bool = False) -> list[str]:
    """Validate schema36's epoch-bound acceptance over immutable v35 pixels."""
    normalized = dict(record)
    normalized["dense_proof_atlas_layout"] = 3
    # v35 binds the last analyzed atlas to every completed transport. Schema36
    # intentionally permits a completed atlas from an older presentation epoch
    # to be excluded, so bind the diagnostic gauges to the last accepted atlas
    # instead while retaining every v35 image-quality invariant.
    normalized["dense_proof_atlas_completed"] = record[
        "proof_evidence_last_accepted_atlas_sequence"]
    # Schema36 endpoint tags are accepted endpointSequence ordinals. FIFO
    # coalescing may keep visible promotions behind that lifetime ordinal, but
    # realFrameCount is the exact accepted-endpoint population and therefore
    # remains the fail-closed upper bound. Schema35 retains promoted binding.
    normalized["promoted"] = record["real"]
    failures = _v35_diagnostic_hierarchy(
        normalized, segment_relative=segment_relative)
    if record["dense_proof_atlas_layout"] != 4:
        failures.append("v36 diagnostic atlas layout is not version 4")
    if segment_relative:
        if record["proof_evidence_accepted"] != record["proof"]:
            failures.append(
                "v36 segment accepted evidence does not match proof samples")
        if record["proof_evidence_excluded"] != 0:
            failures.append("v36 segment contains cross-epoch proof evidence")
        return failures
    accepted = record["proof_evidence_accepted"]
    excluded = record["proof_evidence_excluded"]
    completed = record["dense_proof_atlas_completed"]
    last_accepted = record["proof_evidence_last_accepted_atlas_sequence"]
    if record["proof_evidence_presentation_epoch"] != record[
            "window_presentation_epoch"]:
        failures.append("v36 proof evidence epoch does not match presentation")
    if not 0 <= record["proof_evidence_enqueued_in_epoch"] <= 120:
        failures.append("v36 per-epoch proof enqueue budget is impossible")
    if accepted != record["proof"] or completed != accepted + excluded:
        failures.append("v36 accepted/excluded proof conservation is impossible")
    if accepted == 0:
        if last_accepted != 0:
            failures.append("v36 last accepted atlas survives empty evidence")
    elif not (0 < last_accepted <= completed and
              record["dense_diagnostic_last_atlas_sequence"] == last_accepted):
        failures.append("v36 accepted proof binding is impossible")
    return failures


def _v37_diagnostic_hierarchy(record: dict, *,
                              segment_relative: bool = False) -> list[str]:
    """Extend v36 proof binding with the timestamp-resampled target."""
    normalized = dict(record)
    normalized["dense_proof_atlas_layout"] = 4
    failures = _v36_diagnostic_hierarchy(
        normalized, segment_relative=segment_relative)
    if record["dense_proof_atlas_layout"] != 5:
        failures.append("v37 diagnostic atlas layout is not version 5")
    if record["dense_diagnostic_last_target_source_ns"] < 0:
        failures.append("v37 target source timestamp is invalid")
    if record["proof"] == 0:
        if record["dense_diagnostic_last_target_source_ns"] != 0:
            failures.append("v37 target timestamp survives empty evidence")
    elif record["dense_diagnostic_last_target_source_ns"] <= 0:
        failures.append("v37 accepted evidence has no target timestamp")
    return failures


def verify(log_path: Path, latency_path: Path, *, role: str = "primary",
           display_id: int = 0, qualification_path: Path | None = None,
           segment_id: str | None = None) -> dict:
    qualification, segment = _load_qualification(qualification_path, segment_id)
    if (qualification["evidence"]["logSha256"] != _sha256(log_path) or
            qualification["evidence"]["latencySha256"] != _sha256(latency_path)):
        raise ValueError("qualification manifest does not bind the exact evidence files")
    log = log_path.read_text(encoding="utf-8", errors="replace")
    lowered = log.lower()
    failures = [f"forbidden runtime marker: {marker}" for marker in FORBIDDEN
                if marker in lowered]
    parsed = _parse_health_records(log)
    attachments = []
    resizes = []
    dense_allocations = []
    proof_events = framegen_proof_state_events(log)
    for line_index, line in enumerate(log.splitlines()):
        pid = framegen_line_pid(line)
        attached = ATTACHED.search(line)
        if attached and pid is not None:
            attachments.append((pid, int(attached.group(1)), attached.group(2),
                                int(attached.group(3)), attached.group(4),
                                int(attached.group(5)),
                                0 if attached.group(6) is None else int(attached.group(6)),
                                0 if attached.group(7) is None else int(attached.group(7))))
        resized = RESIZED.search(line)
        if resized and pid is not None:
            resizes.append((pid, int(resized.group(1)), resized.group(2),
                            int(resized.group(3)), int(resized.group(4)),
                            int(resized.group(5))))
        allocated = DENSE_ALLOCATED.search(line)
        if allocated and pid is not None:
            dense_allocations.append(
                (pid, int(allocated.group(1)), allocated.group(2),
                 int(allocated.group(3)), int(allocated.group(4)),
                 int(allocated.group(5)), int(allocated.group(6)),
                 int(allocated.group(7))))
    selected = [(match, pid, line_index) for match, pid, line_index in parsed
                if match.group("role") == role and
                int(match.group("display_id")) == display_id]
    identity = f"{role}/display-{display_id}"
    if not selected:
        raise ValueError(
            f"no complete {identity} frame-generation health record"
        )
    generators = {int(match.group("generator"))
                  for match, _pid, _line_index in selected}
    if len(generators) != 1:
        raise ValueError(f"evidence contains multiple {identity} generators")
    pids = {pid for _match, pid, _line_index in selected}
    if len(pids) != 1:
        raise ValueError(f"evidence contains multiple {role} generator processes")
    generator = next(iter(generators))
    pid = next(iter(pids))
    qualification_identity = qualification["identity"]
    _validate_identity(qualification_identity, log, pid=pid, generator=generator,
                       role=role, display_id=display_id)
    # Qualification may enable the dense arm after the generator's immutable
    # v22 attach record. Bind the selected segment to its final contract; the
    # per-record checks below reject any contract mixing inside that segment.
    proof_contract = selected[-1][0].group("proof_contract")
    proof_schema_version = int(selected[-1][0].group("proof_schema_version"))
    supported_contracts = {
        (PROOF_CONTRACT, PROOF_SCHEMA_VERSION),
        (DENSE_PROOF_CONTRACT, DENSE_PROOF_SCHEMA_VERSION),
        (DENSE_V27_PROOF_CONTRACT, DENSE_V27_PROOF_SCHEMA_VERSION),
        (DENSE_V28_V32_PROOF_CONTRACT, DENSE_V28_V32_PROOF_SCHEMA_VERSION),
        (DENSE_V28_PROOF_CONTRACT, DENSE_V28_PROOF_SCHEMA_VERSION),
        (DENSE_V34_PROOF_CONTRACT, DENSE_V34_PROOF_SCHEMA_VERSION),
        (DENSE_V35_PROOF_CONTRACT, DENSE_V35_PROOF_SCHEMA_VERSION),
        (DENSE_V36_PROOF_CONTRACT, DENSE_V36_PROOF_SCHEMA_VERSION),
        (DENSE_V37_PROOF_CONTRACT, DENSE_V37_PROOF_SCHEMA_VERSION),
        (DENSE_V38_PROOF_CONTRACT, DENSE_V38_PROOF_SCHEMA_VERSION),
        (DENSE_V39_PROOF_CONTRACT, DENSE_V39_PROOF_SCHEMA_VERSION),
        (DENSE_V40_PROOF_CONTRACT, DENSE_V40_PROOF_SCHEMA_VERSION),
        (DENSE_V41_PROOF_CONTRACT, DENSE_V41_PROOF_SCHEMA_VERSION),
        (DENSE_V42_PROOF_CONTRACT, DENSE_V42_PROOF_SCHEMA_VERSION),
        (DENSE_V43_PROOF_CONTRACT, DENSE_V43_PROOF_SCHEMA_VERSION),
        (DENSE_V44_PROOF_CONTRACT, DENSE_V44_PROOF_SCHEMA_VERSION),
        (DENSE_V45_PROOF_CONTRACT, DENSE_V45_PROOF_SCHEMA_VERSION),
        (DENSE_V46_PROOF_CONTRACT, DENSE_V46_PROOF_SCHEMA_VERSION),
        (DENSE_V47_PROOF_CONTRACT, DENSE_V47_PROOF_SCHEMA_VERSION),
        (DENSE_V48_PROOF_CONTRACT, DENSE_V48_PROOF_SCHEMA_VERSION),
        (DENSE_V49_PROOF_CONTRACT, DENSE_V49_PROOF_SCHEMA_VERSION),
        (DENSE_V50_PROOF_CONTRACT, DENSE_V50_PROOF_SCHEMA_VERSION),
        (DENSE_V51_PROOF_CONTRACT, DENSE_V51_PROOF_SCHEMA_VERSION),
        (DENSE_V54_PROOF_CONTRACT, DENSE_V54_PROOF_SCHEMA_VERSION),
        (DENSE_V55_PROOF_CONTRACT, DENSE_V55_PROOF_SCHEMA_VERSION),
        (DENSE_V56_PROOF_CONTRACT, DENSE_V56_PROOF_SCHEMA_VERSION),
        (DENSE_V57_PROOF_CONTRACT, DENSE_V57_PROOF_SCHEMA_VERSION),
        (DENSE_V58_PROOF_CONTRACT, DENSE_V58_PROOF_SCHEMA_VERSION),
        (DENSE_V59_PROOF_CONTRACT, DENSE_V59_PROOF_SCHEMA_VERSION),
        (DENSE_V60_PROOF_CONTRACT, DENSE_V60_PROOF_SCHEMA_VERSION),
        (DENSE_V61_PROOF_CONTRACT, DENSE_V61_PROOF_SCHEMA_VERSION),
        (DENSE_V62_PROOF_CONTRACT, DENSE_V62_PROOF_SCHEMA_VERSION),
    }
    if (proof_contract, proof_schema_version) not in supported_contracts:
        raise ValueError("unsupported frame-generation proof contract")
    matching_attachments = [item for item in attachments if
                            item[:6] == (pid, generator, role, display_id,
                                         PROOF_CONTRACT, PROOF_SCHEMA_VERSION)]
    if len(matching_attachments) != 1:
        raise ValueError(
            f"{identity} generator is not bound to exactly one attach record"
        )
    input_width, input_height = matching_attachments[0][6:8]
    matching_resizes = [item for item in resizes if
                        item[:4] == (pid, generator, role, display_id)]
    if matching_resizes:
        # The stream's true dimensions are the latest reported resize; the
        # attach record only carries the initial surface size (a DS stream
        # attaches at panel size then resizes to native 256x192).
        input_width, input_height = matching_resizes[-1][4:6]
    matching_allocations = [item for item in dense_allocations if
                            item[:4] == (pid, generator, role, display_id)]
    if matching_allocations:
        # The allocation record is authoritative: it names the exact history
        # dimensions the analysis grid derived from, and the workload check
        # below still requires the grid to be the exact capped fit of them.
        input_width, input_height = matching_allocations[-1][4:6]
    reset_contract = segment.get("proofReset")
    if reset_contract is None:
        proof_enables = [event for event in proof_events
                         if event["pid"] == pid and
                         event["generator"] == generator and
                         event["enabled"] is True and
                         event["proofContract"] == proof_contract and
                         event["proofSchemaVersion"] == proof_schema_version]
        # (2026-09-02) The tier protocol's downgrade probe re-arms the proof by
        # design (60 first, then 40 after pacing: GameCube run gc-b54).  The
        # proof that matters is the LAST arm before the selected segment; any
        # arm inside the segment would still be a mid-segment restart.
        if not proof_enables:
            raise ValueError(f"{identity} generator proof was never enabled")
        pending_proof_enable_check = proof_enables
    else:
        pending_proof_enable_check = None

    def decoded(match, record_pid, line_index):
        result = {key: (value if key in (
                           "role", "proof_contract", "dense_variant",
                           "dense_diagnostic_mask_layout",
                           "presentation_timing_mode", "source_clock_kind") else
                       (0 if value is None else int(value)))
                  for key, value in match.groupdict().items()}
        result["pid"] = record_pid
        result["line_index"] = line_index
        return result

    records = [decoded(match, record_pid, line_index)
               for match, record_pid, line_index in selected]
    if pending_proof_enable_check is not None:
        # (2026-09-02) The tier protocol's downgrade probe re-arms the proof
        # by design (60 first, then 40 after pacing: GameCube run gc-b54).
        # The arm that matters is the last one before the selected segment;
        # an arm inside the segment is still a mid-segment restart.
        segment_records = [record for record in records
                           if int(segment["startWindowEndNs"]) <=
                           int(record["window_end_ns"]) <=
                           int(segment["endWindowEndNs"])]
        if segment_records and "line_index" in segment_records[0]:
            # Every arm must precede the selected segment: the downgrade
            # probe legitimately arms 60 and then 40 before the segment, but
            # an arm inside or after it would join a later session's
            # evidence to this segment.
            first_line = int(segment_records[0]["line_index"])
            late = [event for event in pending_proof_enable_check
                    if int(event["lineIndex"]) >= first_line]
            if late:
                raise ValueError(
                    f"{identity} generator proof was not enabled exactly once")
        elif len(pending_proof_enable_check) != 1:
            raise ValueError(
                f"{identity} generator proof was not enabled exactly once")
    records.sort(key=lambda record: record["window_end_ns"])
    segment_start, proof_baseline, segment_end, segment_records, proof_records, transition = \
        _validate_segment(segment, records)
    validated_reset = None
    if reset_contract is not None:
        validated_reset = _validate_proof_reset(
            reset_contract, proof_events, records, proof_baseline, segment_end,
            pid=pid, generator=generator, proof_contract=proof_contract,
            proof_schema_version=proof_schema_version,
        )
    session_start = qualification_identity.get("sessionStartNs")
    session_end = qualification_identity.get("sessionEndNs")
    if (not isinstance(session_start, int) or not isinstance(session_end, int) or
            session_start <= 0 or session_start >= session_end):
        raise ValueError("qualification identity has invalid session bounds")
    if (segment_start["window_start_ns"] < session_start or
            segment_end["window_end_ns"] > session_end):
        raise ValueError("qualification segment is outside its bound session")
    latency = parse_latency(latency_path)
    values = dict(segment_end)
    selected_index = records.index(segment_end)
    if (values["proof_contract"], values["proof_schema_version"]) not in supported_contracts:
        raise ValueError("unsupported frame-generation proof contract")
    dense_contract = values["proof_contract"] in (
        DENSE_PROOF_CONTRACT, DENSE_V27_PROOF_CONTRACT,
        DENSE_V28_V32_PROOF_CONTRACT, DENSE_V28_PROOF_CONTRACT,
        DENSE_V34_PROOF_CONTRACT, DENSE_V35_PROOF_CONTRACT,
        DENSE_V36_PROOF_CONTRACT, DENSE_V37_PROOF_CONTRACT,
        DENSE_V38_PROOF_CONTRACT, DENSE_V39_PROOF_CONTRACT,
        DENSE_V40_PROOF_CONTRACT, DENSE_V41_PROOF_CONTRACT,
        DENSE_V42_PROOF_CONTRACT, DENSE_V43_PROOF_CONTRACT,
        DENSE_V44_PROOF_CONTRACT, DENSE_V45_PROOF_CONTRACT,
        DENSE_V46_PROOF_CONTRACT, DENSE_V47_PROOF_CONTRACT,
        DENSE_V48_PROOF_CONTRACT, DENSE_V49_PROOF_CONTRACT,
        DENSE_V50_PROOF_CONTRACT, DENSE_V51_PROOF_CONTRACT,
        DENSE_V54_PROOF_CONTRACT, DENSE_V55_PROOF_CONTRACT,
        DENSE_V56_PROOF_CONTRACT, DENSE_V57_PROOF_CONTRACT,
        DENSE_V58_PROOF_CONTRACT, DENSE_V59_PROOF_CONTRACT,
        DENSE_V60_PROOF_CONTRACT, DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT)
    dense_v27_contract = values["proof_contract"] == DENSE_V27_PROOF_CONTRACT
    dense_v28_contract = values["proof_contract"] in (
        DENSE_V28_V32_PROOF_CONTRACT, DENSE_V28_PROOF_CONTRACT,
        DENSE_V34_PROOF_CONTRACT, DENSE_V35_PROOF_CONTRACT,
        DENSE_V36_PROOF_CONTRACT, DENSE_V37_PROOF_CONTRACT,
        DENSE_V38_PROOF_CONTRACT, DENSE_V39_PROOF_CONTRACT,
        DENSE_V40_PROOF_CONTRACT, DENSE_V41_PROOF_CONTRACT,
        DENSE_V42_PROOF_CONTRACT, DENSE_V43_PROOF_CONTRACT,
        DENSE_V44_PROOF_CONTRACT, DENSE_V45_PROOF_CONTRACT,
        DENSE_V46_PROOF_CONTRACT, DENSE_V47_PROOF_CONTRACT,
        DENSE_V48_PROOF_CONTRACT, DENSE_V49_PROOF_CONTRACT,
        DENSE_V50_PROOF_CONTRACT, DENSE_V51_PROOF_CONTRACT,
        DENSE_V54_PROOF_CONTRACT, DENSE_V55_PROOF_CONTRACT,
        DENSE_V56_PROOF_CONTRACT, DENSE_V57_PROOF_CONTRACT,
        DENSE_V58_PROOF_CONTRACT, DENSE_V59_PROOF_CONTRACT,
        DENSE_V60_PROOF_CONTRACT, DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT)
    pair_quota_contract = values["proof_contract"] in (
        DENSE_V28_PROOF_CONTRACT, DENSE_V34_PROOF_CONTRACT,
        DENSE_V35_PROOF_CONTRACT, DENSE_V36_PROOF_CONTRACT)
    diagnostic_contract = values["proof_contract"] in (
        DENSE_V34_PROOF_CONTRACT, DENSE_V35_PROOF_CONTRACT,
        DENSE_V36_PROOF_CONTRACT, DENSE_V37_PROOF_CONTRACT,
        DENSE_V38_PROOF_CONTRACT, DENSE_V39_PROOF_CONTRACT,
        DENSE_V40_PROOF_CONTRACT, DENSE_V41_PROOF_CONTRACT,
        DENSE_V42_PROOF_CONTRACT, DENSE_V43_PROOF_CONTRACT,
        DENSE_V44_PROOF_CONTRACT, DENSE_V45_PROOF_CONTRACT,
        DENSE_V46_PROOF_CONTRACT, DENSE_V47_PROOF_CONTRACT,
        DENSE_V48_PROOF_CONTRACT, DENSE_V49_PROOF_CONTRACT,
        DENSE_V50_PROOF_CONTRACT, DENSE_V51_PROOF_CONTRACT,
        DENSE_V54_PROOF_CONTRACT, DENSE_V55_PROOF_CONTRACT,
        DENSE_V56_PROOF_CONTRACT, DENSE_V57_PROOF_CONTRACT,
        DENSE_V58_PROOF_CONTRACT, DENSE_V59_PROOF_CONTRACT,
        DENSE_V60_PROOF_CONTRACT, DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT)
    v35_diagnostic_contract = (
        values["proof_contract"] in (
            DENSE_V35_PROOF_CONTRACT, DENSE_V36_PROOF_CONTRACT,
            DENSE_V37_PROOF_CONTRACT, DENSE_V38_PROOF_CONTRACT,
            DENSE_V39_PROOF_CONTRACT, DENSE_V40_PROOF_CONTRACT,
            DENSE_V41_PROOF_CONTRACT, DENSE_V42_PROOF_CONTRACT,
            DENSE_V43_PROOF_CONTRACT, DENSE_V44_PROOF_CONTRACT,
            DENSE_V45_PROOF_CONTRACT, DENSE_V46_PROOF_CONTRACT,
            DENSE_V47_PROOF_CONTRACT, DENSE_V48_PROOF_CONTRACT,
            DENSE_V49_PROOF_CONTRACT, DENSE_V50_PROOF_CONTRACT,
            DENSE_V51_PROOF_CONTRACT, DENSE_V54_PROOF_CONTRACT,
            DENSE_V55_PROOF_CONTRACT, DENSE_V56_PROOF_CONTRACT,
            DENSE_V57_PROOF_CONTRACT, DENSE_V58_PROOF_CONTRACT,
            DENSE_V59_PROOF_CONTRACT, DENSE_V60_PROOF_CONTRACT,
            DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT))
    v36_evidence_contract = (
        values["proof_contract"] in (
            DENSE_V36_PROOF_CONTRACT, DENSE_V37_PROOF_CONTRACT,
            DENSE_V38_PROOF_CONTRACT, DENSE_V39_PROOF_CONTRACT,
            DENSE_V40_PROOF_CONTRACT, DENSE_V41_PROOF_CONTRACT,
            DENSE_V42_PROOF_CONTRACT, DENSE_V43_PROOF_CONTRACT,
            DENSE_V44_PROOF_CONTRACT, DENSE_V45_PROOF_CONTRACT,
            DENSE_V46_PROOF_CONTRACT, DENSE_V47_PROOF_CONTRACT,
            DENSE_V48_PROOF_CONTRACT, DENSE_V49_PROOF_CONTRACT,
            DENSE_V50_PROOF_CONTRACT, DENSE_V51_PROOF_CONTRACT,
            DENSE_V54_PROOF_CONTRACT, DENSE_V55_PROOF_CONTRACT,
            DENSE_V56_PROOF_CONTRACT, DENSE_V57_PROOF_CONTRACT,
            DENSE_V58_PROOF_CONTRACT, DENSE_V59_PROOF_CONTRACT,
            DENSE_V60_PROOF_CONTRACT, DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT))
    v38_vector_trajectory_contract = (
        values["proof_contract"] in (
            DENSE_V38_PROOF_CONTRACT, DENSE_V39_PROOF_CONTRACT,
            DENSE_V40_PROOF_CONTRACT, DENSE_V41_PROOF_CONTRACT,
            DENSE_V42_PROOF_CONTRACT, DENSE_V43_PROOF_CONTRACT,
            DENSE_V44_PROOF_CONTRACT, DENSE_V45_PROOF_CONTRACT,
            DENSE_V46_PROOF_CONTRACT, DENSE_V47_PROOF_CONTRACT,
            DENSE_V48_PROOF_CONTRACT, DENSE_V49_PROOF_CONTRACT,
            DENSE_V50_PROOF_CONTRACT, DENSE_V51_PROOF_CONTRACT,
            DENSE_V54_PROOF_CONTRACT, DENSE_V55_PROOF_CONTRACT,
            DENSE_V56_PROOF_CONTRACT, DENSE_V57_PROOF_CONTRACT,
            DENSE_V58_PROOF_CONTRACT, DENSE_V59_PROOF_CONTRACT,
            DENSE_V60_PROOF_CONTRACT, DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT))
    v37_timestamp_contract = values["proof_contract"] in (
        DENSE_V37_PROOF_CONTRACT, DENSE_V38_PROOF_CONTRACT,
        DENSE_V39_PROOF_CONTRACT, DENSE_V40_PROOF_CONTRACT,
        DENSE_V41_PROOF_CONTRACT, DENSE_V42_PROOF_CONTRACT,
        DENSE_V43_PROOF_CONTRACT, DENSE_V44_PROOF_CONTRACT,
        DENSE_V45_PROOF_CONTRACT, DENSE_V46_PROOF_CONTRACT,
        DENSE_V47_PROOF_CONTRACT, DENSE_V48_PROOF_CONTRACT,
        DENSE_V49_PROOF_CONTRACT, DENSE_V50_PROOF_CONTRACT,
        DENSE_V51_PROOF_CONTRACT, DENSE_V54_PROOF_CONTRACT,
        DENSE_V55_PROOF_CONTRACT, DENSE_V56_PROOF_CONTRACT,
        DENSE_V57_PROOF_CONTRACT, DENSE_V58_PROOF_CONTRACT,
        DENSE_V59_PROOF_CONTRACT, DENSE_V60_PROOF_CONTRACT,
        DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT)
    v42_uniform_contract = (
        values["proof_contract"] == DENSE_V42_PROOF_CONTRACT)
    v43_rational_contract = values["proof_contract"] in (
        DENSE_V43_PROOF_CONTRACT, DENSE_V44_PROOF_CONTRACT,
        DENSE_V45_PROOF_CONTRACT, DENSE_V46_PROOF_CONTRACT,
        DENSE_V47_PROOF_CONTRACT, DENSE_V48_PROOF_CONTRACT,
        DENSE_V49_PROOF_CONTRACT, DENSE_V50_PROOF_CONTRACT,
        DENSE_V51_PROOF_CONTRACT, DENSE_V54_PROOF_CONTRACT,
        DENSE_V55_PROOF_CONTRACT, DENSE_V56_PROOF_CONTRACT,
        DENSE_V57_PROOF_CONTRACT, DENSE_V58_PROOF_CONTRACT,
        DENSE_V59_PROOF_CONTRACT, DENSE_V60_PROOF_CONTRACT,
        DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT)
    v39_present_timed_contract = values["proof_contract"] in (
        DENSE_V39_PROOF_CONTRACT, DENSE_V40_PROOF_CONTRACT,
        DENSE_V41_PROOF_CONTRACT, DENSE_V42_PROOF_CONTRACT,
        DENSE_V43_PROOF_CONTRACT, DENSE_V44_PROOF_CONTRACT,
        DENSE_V45_PROOF_CONTRACT, DENSE_V46_PROOF_CONTRACT,
        DENSE_V47_PROOF_CONTRACT, DENSE_V48_PROOF_CONTRACT,
        DENSE_V49_PROOF_CONTRACT, DENSE_V50_PROOF_CONTRACT,
        DENSE_V51_PROOF_CONTRACT, DENSE_V54_PROOF_CONTRACT,
        DENSE_V55_PROOF_CONTRACT, DENSE_V56_PROOF_CONTRACT,
        DENSE_V57_PROOF_CONTRACT, DENSE_V58_PROOF_CONTRACT,
        DENSE_V59_PROOF_CONTRACT, DENSE_V60_PROOF_CONTRACT,
        DENSE_V61_PROOF_CONTRACT,
        DENSE_V62_PROOF_CONTRACT)
    evidence_records = [proof_baseline] + proof_records
    proof_keys = (
        "proof", "synthetic", "distinct", "changing", "eligible_pixels",
        "substantive_pixels", "non_crossfade_pixels", "motion_eligible_samples",
        "correlated_samples",
        "motion_eligible_pixels", "motion_synthesized_pixels",
    )
    lifetime_cumulative_keys = (
        "presents", "generated", "real", "promoted", "submitted",
        "lattice_samples", "lattice_backward_coherent",
        "lattice_forward_coherent", "lattice_backward_boundary",
        "lattice_forward_boundary", "lattice_backward_coherent_boundary",
        "lattice_forward_coherent_boundary",
        "regional_samples", "regional_backward_supported",
        "regional_forward_supported", "regional_backward_neighbor",
        "regional_forward_neighbor", "regional_backward_constant_neighbor",
        "regional_forward_constant_neighbor", "regional_backward_gradient_neighbor",
        "regional_forward_gradient_neighbor", "regional_backward_accepted",
        "regional_forward_accepted", "regional_backward_accepted_boundary",
        "regional_forward_accepted_boundary", "regional_backward_cycle",
        "regional_forward_cycle",
        "dense_promotions", "dense_passes", "dense_submit_total_us",
        "dense_gpu_total_us", "dense_timed_pairs",
        "dense_copy_samples", "dense_copy_total_us",
        "dense_pyramid_samples", "dense_pyramid_total_us",
        "dense_forward_samples", "dense_forward_total_us",
        "dense_reverse_samples", "dense_reverse_total_us",
        "dense_validation_samples", "dense_validation_total_us",
        "dense_warp_samples", "dense_warp_total_us",
        "dense_promotion_wall_samples", "dense_promotion_wall_total_us",
        "dense_signature_wall_samples", "dense_signature_wall_total_us",
        "dense_signature_sequence", "dense_signature_ready",
        "dense_proof_wall_samples", "dense_proof_wall_total_us",
        "dense_proof_cells", "dense_backward_valid", "dense_forward_valid",
    )
    asynchronous_cumulative_keys = (
        "dense_proof_atlas_enqueued", "dense_proof_atlas_completed",
        "dense_callback_delta_samples", "dense_callback_delta_total_us",
        "dense_present_wall_samples", "dense_present_wall_total_us",
        "dense_swap_wall_samples", "dense_swap_wall_total_us",
        "dense_proof_enqueue_wall_samples",
        "dense_proof_enqueue_wall_total_us",
        "dense_proof_poll_wall_samples", "dense_proof_poll_wall_total_us",
    )
    v36_evidence_cumulative_keys = (
        "proof_evidence_accepted", "proof_evidence_excluded",
    )
    v37_timestamp_cumulative_keys = (
        "endpoint_fifo_coalesced", "endpoint_timestamp_corrections",
    )
    diagnostic_cumulative_keys = (
        "dense_diagnostic_cells", "dense_diagnostic_tiles",
        "dense_diagnostic_mask_errors",
        "dense_backward_active", "dense_backward_in_bounds",
        "dense_backward_cycle_valid", "dense_backward_photometric_valid",
        "dense_backward_texture_valid", "dense_backward_saturated",
        "dense_backward_out_of_bounds", "dense_backward_covered_tiles",
        "dense_forward_active", "dense_forward_in_bounds",
        "dense_forward_cycle_valid", "dense_forward_photometric_valid",
        "dense_forward_texture_valid", "dense_forward_saturated",
        "dense_forward_out_of_bounds", "dense_forward_covered_tiles",
    )
    v35_diagnostic_cumulative_keys = (
        "dense_diagnostic_packed_cells",
        "dense_diagnostic_partition_errors",
        "dense_diagnostic_reserved_bit_errors",
    )
    all_diagnostic_cumulative_keys = (
        diagnostic_cumulative_keys +
        (v35_diagnostic_cumulative_keys if v35_diagnostic_contract else ()))
    monotonic_cumulative_keys = lifetime_cumulative_keys + (
        asynchronous_cumulative_keys if dense_v28_contract else ()
    ) + (
        v36_evidence_cumulative_keys if v36_evidence_contract else ()
    ) + (
        all_diagnostic_cumulative_keys if diagnostic_contract else ()
    ) + (
        v37_timestamp_cumulative_keys if v37_timestamp_contract else ()
    )
    cumulative_keys = monotonic_cumulative_keys + proof_keys

    # Reject internally impossible telemetry before using ratios derived from
    # it. These are QA-evidence invariants, not adjustable quality thresholds:
    # every counter is emitted by one generator instance and must remain
    # cumulative, while each threshold count must fit inside the population
    # from which it is actually derived. Bidirectional reliability combines a
    # low-confidence texel with a displaced, linearly sampled reverse peer, so
    # it is not a subset of either same-cell directional threshold count.
    for record in segment_records:
        if (record["proof_contract"] != proof_contract or
                record["proof_schema_version"] != proof_schema_version):
            failures.append("generator health records mix proof contracts")
        if v37_timestamp_contract:
            failures.extend(_v37_diagnostic_hierarchy(record))
            failures.extend(_v37_output_accounting_hierarchy(record))
            if v43_rational_contract:
                failures.extend(_v43_rational_clock_hierarchy(record))
        elif v36_evidence_contract:
            failures.extend(_v36_diagnostic_hierarchy(record))
            failures.extend(_v36_output_accounting_hierarchy(record))
        elif v35_diagnostic_contract:
            failures.extend(_v35_diagnostic_hierarchy(record))
        elif diagnostic_contract:
            failures.extend(_v34_diagnostic_hierarchy(record))
        hierarchy = (
            (record["promoted"] <= record["real"] <= record["submitted"],
             "promoted/real/submitted counters are impossible"),
            (record["generated"] <= record["presents"],
             "generated presents exceed total presents"),
            (v36_evidence_contract or
             record["generated"] + record["promoted"] <= record["presents"],
             "classified cumulative presents exceed total presents"),
            (v36_evidence_contract or
             record["window_generated"] + record["window_promoted"] <=
                 record["window_presents"],
             "classified window presents exceed total window presents"),
            (record["window_ms"] > 0 and
             record["window_start_ns"] < record["window_end_ns"],
             "health cadence window is invalid"),
            (record["proof"] <= record["presents"],
             "proof samples exceed total presents"),
            (validated_reset is not None or record["lattice_samples"] ==
             record["proof"] * REGIONAL_FLOW_CELLS,
             "candidate lattice telemetry does not cover every proof region"),
            (record["lattice_backward_coherent"] <=
             record["lattice_samples"] and
             record["lattice_forward_coherent"] <= record["lattice_samples"],
             "coherent candidate cumulative counters are impossible"),
            (record["lattice_backward_boundary"] <= record["lattice_samples"] and
             record["lattice_forward_boundary"] <= record["lattice_samples"],
             "candidate lattice boundary counters are impossible"),
            (record["lattice_backward_coherent_boundary"] <=
             min(record["lattice_backward_coherent"],
                 record["lattice_backward_boundary"]) and
             record["lattice_forward_coherent_boundary"] <=
             min(record["lattice_forward_coherent"],
                 record["lattice_forward_boundary"]),
             "coherent-boundary intersection counters are impossible"),
            (record["lattice_backward_count"] <= REGIONAL_FLOW_CELLS and
             record["lattice_forward_count"] <= REGIONAL_FLOW_CELLS and
             record["lattice_backward_boundary_count"] <= REGIONAL_FLOW_CELLS and
             record["lattice_forward_boundary_count"] <= REGIONAL_FLOW_CELLS,
             "candidate lattice instantaneous counts are impossible"),
            (record["lattice_backward_coherent_boundary_count"] <=
             min(record["lattice_backward_count"],
                 record["lattice_backward_boundary_count"]) and
             record["lattice_forward_coherent_boundary_count"] <=
             min(record["lattice_forward_count"],
                 record["lattice_forward_boundary_count"]),
             "instantaneous coherent-boundary intersections are impossible"),
            (max(record["lattice_backward_peak_support"],
                 record["lattice_forward_peak_support"]) <= 255,
             "candidate support telemetry is out of range"),
            (validated_reset is not None or record["regional_samples"] ==
             record["proof"] * REGIONAL_FLOW_CELLS,
             "regional flow telemetry does not cover every proof region"),
            (record["regional_backward_neighbor"] <= record["regional_samples"] and
             record["regional_forward_neighbor"] <= record["regional_samples"],
             "regional neighbor counters are impossible"),
            (record["regional_backward_constant_neighbor"] <=
             record["regional_backward_neighbor"] and
             record["regional_backward_gradient_neighbor"] <=
             record["regional_backward_neighbor"] and
             record["regional_backward_neighbor"] <=
             record["regional_backward_constant_neighbor"] +
             record["regional_backward_gradient_neighbor"] and
             record["regional_forward_constant_neighbor"] <=
             record["regional_forward_neighbor"] and
             record["regional_forward_gradient_neighbor"] <=
             record["regional_forward_neighbor"] and
             record["regional_forward_neighbor"] <=
             record["regional_forward_constant_neighbor"] +
             record["regional_forward_gradient_neighbor"],
             "neighbor-model subset counters are impossible"),
            (record["regional_backward_accepted"] <=
             record["regional_backward_supported"] <=
             record["regional_samples"] and
             record["regional_backward_accepted"] <=
             record["regional_backward_neighbor"] and
             record["regional_forward_accepted"] <=
             record["regional_forward_supported"] <= record["regional_samples"] and
             record["regional_forward_accepted"] <=
             record["regional_forward_neighbor"] and
             record["regional_backward_cycle"] <=
             record["regional_backward_accepted"] and
             record["regional_forward_cycle"] <=
             record["regional_forward_accepted"],
             "regional cumulative acceptance counters are impossible"),
            (record["regional_backward_accepted_boundary"] <=
             min(record["regional_backward_accepted"],
                 record["lattice_backward_boundary"]) and
             record["regional_forward_accepted_boundary"] <=
             min(record["regional_forward_accepted"],
                 record["lattice_forward_boundary"]),
             "accepted-boundary intersection counters are impossible"),
            (record["regional_backward_count"] <=
             record["regional_backward_supported_count"] <=
             REGIONAL_FLOW_CELLS and
             record["regional_backward_count"] <=
             record["regional_backward_neighbor_count"] and
             record["regional_forward_count"] <=
             record["regional_forward_supported_count"] <=
             REGIONAL_FLOW_CELLS and
             record["regional_forward_count"] <=
             record["regional_forward_neighbor_count"] and
             record["regional_backward_cycle_count"] <=
             record["regional_backward_count"] and
             record["regional_forward_cycle_count"] <=
             record["regional_forward_count"] and
             record["regional_backward_neighbor_count"] <=
             REGIONAL_FLOW_CELLS and
             record["regional_forward_neighbor_count"] <= REGIONAL_FLOW_CELLS,
             "regional instantaneous acceptance counts are impossible"),
            (record["regional_backward_constant_neighbor_count"] <=
             record["regional_backward_neighbor_count"] and
             record["regional_backward_gradient_neighbor_count"] <=
             record["regional_backward_neighbor_count"] and
             record["regional_backward_neighbor_count"] <=
             record["regional_backward_constant_neighbor_count"] +
             record["regional_backward_gradient_neighbor_count"] and
             record["regional_forward_constant_neighbor_count"] <=
             record["regional_forward_neighbor_count"] and
             record["regional_forward_gradient_neighbor_count"] <=
             record["regional_forward_neighbor_count"] and
             record["regional_forward_neighbor_count"] <=
             record["regional_forward_constant_neighbor_count"] +
             record["regional_forward_gradient_neighbor_count"],
             "instantaneous neighbor-model subsets are impossible"),
            (record["regional_backward_accepted_boundary_count"] <=
             min(record["regional_backward_count"],
                 record["lattice_backward_boundary_count"]) and
             record["regional_forward_accepted_boundary_count"] <=
             min(record["regional_forward_count"],
                 record["lattice_forward_boundary_count"]),
             "instantaneous accepted-boundary intersections are impossible"),
            (max(record["regional_backward_support"],
                 record["regional_forward_support"],
                 record["regional_backward_confidence"],
                 record["regional_forward_confidence"]) <= 255,
             "regional flow byte telemetry is out of range"),
            (record["synthetic"] <= record["proof"],
             "synthetic proof samples exceed proof samples"),
            (record["distinct"] <= record["synthetic"],
             "distinct synthetic samples exceed synthetic samples"),
            (record["changing"] <= record["proof"],
             "changing proof outputs exceed proof samples"),
            (record["substantive_pixels"] <= record["eligible_pixels"],
             "substantive pixels exceed eligible pixels"),
            (record["non_crossfade_pixels"] <= record["eligible_pixels"],
             "non-crossfade pixels exceed eligible pixels"),
            (record["correlated_samples"] <= record["motion_eligible_samples"] <=
             record["synthetic"],
             "correlated/motion-eligible/synthetic sample counters are impossible"),
            (record["motion_synthesized_pixels"] <=
             record["motion_eligible_pixels"] <= record["eligible_pixels"],
             "synthesized/motion-eligible/eligible pixel counters are impossible"),
            ((not dense_contract) or
             (record["dense_enabled"] == 1 and
              record["dense_passes"] == record["dense_promotions"] *
                  (48 if record["proof_schema_version"] in (61, 62) else
                   42 if record["proof_schema_version"] == 60 else
                   40 if record["proof_schema_version"] in (51, 54, 55, 56, 57, 58, 59) else 38) and
              record["dense_backward_valid"] <= record["dense_proof_cells"] and
              record["dense_forward_valid"] <= record["dense_proof_cells"]),
             "dense pyramid telemetry is impossible"),
            ((not dense_v27_contract) or _v27_workload_identity_valid(
                record, input_width, input_height),
             "v27 reduced-analysis workload identity is absent or impossible"),
            ((not dense_v28_contract) or _v28_workload_identity_valid(
                record, input_width, input_height),
             "v28 reduced-analysis workload identity is absent or impossible"),
            ((not dense_v28_contract) or _v31_signature_identity_valid(record),
             "v31 ES3 core-query identity is absent or impossible"),
            ((not dense_v28_contract) or
             (record["dense_proof_atlas_completed"] <=
                  record["dense_proof_atlas_enqueued"] and
              record["dense_proof_atlas_layout"] ==
                  (5 if v37_timestamp_contract else
                   4 if v36_evidence_contract else
                   3 if v35_diagnostic_contract else
                   2 if diagnostic_contract else 1) and
              record["dense_proof_atlas_pending"] <= 4 and
              record["dense_proof_atlas_enqueued"] ==
                  record["dense_proof_atlas_completed"] +
                  record["dense_proof_atlas_pending"] and
              record["dense_proof_atlas_ring_full"] == 0 and
              record["dense_proof_atlas_errors"] == 0 and
              record["dense_proof_atlas_tag_errors"] == 0 and
              record["dense_proof_atlas_discarded"] == 0 and
              record["dense_proof_atlas_sync_fallback"] == 0),
             "v32 proof-atlas counter hierarchy is impossible"),
            ((not pair_quota_contract) or
             (record["window_due_selected"] is not None and
              record["window_due_no_endpoint"] is not None and
              record["window_due_phase_clamped"] is not None and
              record["window_real_priority"] is not None and
              record["window_synthetic_quota_skipped"] is not None and
              record["window_presentation_epoch"] is not None and
              record["window_synthetic_quota_opening"] in (0, 1) and
              record["synthetic_quota_pending"] in (0, 1) and
              record["window_synthetic_selected"] ==
                  record["window_generated"] and
              record["window_synthetic_quota_opening"] +
                  record["window_synthetic_pair_created"] ==
                  record["window_synthetic_selected"] +
                  record["window_synthetic_quota_skipped"] +
                  record["synthetic_quota_pending"] and
              record["window_synthetic_not_ready"] is not None and
              record["window_duplicate_pair_selection"] == 0 and
              record["last_selected_synthetic_pair"] >=
                  record["window_synthetic_selected"] and
              record["window_generated"] <= record["window_promoted"] and
              record["window_presents"] == record["window_due_selected"]),
             "v33 pair-quota scheduler accounting is absent or impossible"),
            ((not diagnostic_contract) or
             (record["window_presentation_callbacks"] >=
                  record["window_presents"] and
              (record["window_presentation_callbacks"] > 0 or
               _diagnostic_empty_reset_snapshot(
                   record, v35=v35_diagnostic_contract))),
             "diagnostic presentation callback window is absent or impossible"),
        )
        failures.extend(message for condition, message in hierarchy if not condition)
    for previous, current in zip(segment_records, segment_records[1:]):
        for key in monotonic_cumulative_keys:
            if (validated_reset is not None and
                    key in all_diagnostic_cumulative_keys):
                continue
            if current[key] < previous[key]:
                failures.append(f"cumulative counter regressed: {key}")
        if (v36_evidence_contract and
                current["proof_evidence_presentation_epoch"] ==
                previous["proof_evidence_presentation_epoch"] and
                current["proof_evidence_enqueued_in_epoch"] <
                previous["proof_evidence_enqueued_in_epoch"]):
            failures.append("v36 per-epoch proof enqueue count regressed")
        if diagnostic_contract and validated_reset is None:
            for direction in ("backward", "forward"):
                key = f"dense_{direction}_covered_tile_mask"
                if previous[key] & ~current[key]:
                    failures.append(
                        f"v34 {direction} covered-tile mask regressed")
            for key in (
                    "dense_diagnostic_last_atlas_sequence",
                    "dense_diagnostic_last_pair_sequence",
                    "dense_diagnostic_last_previous_endpoint",
                    "dense_diagnostic_last_current_endpoint"):
                if current[key] < previous[key]:
                    failures.append(f"v34 diagnostic binding regressed: {key}")
            if (v37_timestamp_contract and
                    current["dense_diagnostic_last_target_source_ns"] <
                    previous["dense_diagnostic_last_target_source_ns"]):
                failures.append("v37 target source timestamp regressed")
    if diagnostic_contract and validated_reset is not None:
        for previous, current in zip(evidence_records, evidence_records[1:]):
            for key in all_diagnostic_cumulative_keys:
                if current[key] < previous[key]:
                    failures.append(f"cumulative counter regressed: {key}")
            for direction in ("backward", "forward"):
                key = f"dense_{direction}_covered_tile_mask"
                if previous[key] & ~current[key]:
                    failures.append(
                        f"v34 {direction} covered-tile mask regressed")
            for key in (
                    "dense_diagnostic_last_atlas_sequence",
                    "dense_diagnostic_last_pair_sequence",
                    "dense_diagnostic_last_previous_endpoint",
                    "dense_diagnostic_last_current_endpoint"):
                if current[key] < previous[key]:
                    failures.append(f"v34 diagnostic binding regressed: {key}")
    reset_proof_records = evidence_records if validated_reset is not None \
        else segment_records
    for previous, current in zip(reset_proof_records, reset_proof_records[1:]):
        for key in proof_keys:
            if current[key] < previous[key]:
                failures.append(f"cumulative counter regressed: {key}")

    # Every quality/content counter is cumulative for the lifetime of one GL
    # generator. Qualification is deliberately segment-relative: subtract the
    # exact settled-tier baseline named by the manifest so proof captured at a
    # previous tier cannot qualify this tier or transition.
    values, absolute_values, relative_failures = _segment_relative_counters(
        values, proof_baseline, cumulative_keys,
        asynchronous_atlas=dense_v28_contract,
    )
    failures.extend(relative_failures)
    if diagnostic_contract:
        failures.extend((_v37_diagnostic_hierarchy(
            values, segment_relative=True) if v37_timestamp_contract else
            _v36_diagnostic_hierarchy(
            values, segment_relative=True) if v36_evidence_contract else
            _v35_diagnostic_hierarchy(
                values, segment_relative=True) if v35_diagnostic_contract else
            _v34_diagnostic_hierarchy(values, segment_relative=True)))
    if (values["lattice_samples"] != values["proof"] * REGIONAL_FLOW_CELLS or
            values["regional_samples"] != values["proof"] * REGIONAL_FLOW_CELLS):
        failures.append("segment proof counters do not cover every regional sample")
    segment_hierarchy = (
        (_segment_endpoint_backlogs_valid(proof_baseline, segment_end, values),
         "segment endpoint backlog conservation is impossible"),
        (values["synthetic"] <= values["proof"],
         "segment synthetic samples exceed proof samples"),
        (values["distinct"] <= values["synthetic"],
         "segment distinct samples exceed synthetic samples"),
        (values["changing"] <= values["proof"],
         "segment changing outputs exceed proof samples"),
        (values["substantive_pixels"] <= values["eligible_pixels"] and
         values["non_crossfade_pixels"] <= values["eligible_pixels"],
         "segment pixel subsets exceed eligible pixels"),
        (values["correlated_samples"] <= values["motion_eligible_samples"] <=
         values["synthetic"],
         "segment motion sample subsets are impossible"),
        (values["motion_synthesized_pixels"] <=
         values["motion_eligible_pixels"] <= values["eligible_pixels"],
         "segment motion pixel subsets are impossible"),
        (values["lattice_backward_coherent_boundary"] <=
         min(values["lattice_backward_coherent"],
             values["lattice_backward_boundary"]) and
         values["lattice_forward_coherent_boundary"] <=
         min(values["lattice_forward_coherent"],
             values["lattice_forward_boundary"]),
         "segment coherent-boundary subsets are impossible"),
        (values["regional_backward_accepted"] <=
         values["regional_backward_supported"] <= values["regional_samples"] and
         values["regional_backward_accepted"] <=
         values["regional_backward_neighbor"] and
         values["regional_forward_accepted"] <=
         values["regional_forward_supported"] <= values["regional_samples"] and
         values["regional_forward_accepted"] <=
         values["regional_forward_neighbor"],
         "segment regional acceptance subsets are impossible"),
        (values["regional_backward_cycle"] <=
         values["regional_backward_accepted"] and
         values["regional_forward_cycle"] <=
         values["regional_forward_accepted"],
         "segment regional cycle subsets are impossible"),
    )
    failures.extend(message for condition, message in segment_hierarchy if not condition)
    if v37_timestamp_contract:
        if values["endpoint_fifo_coalesced"] != 0:
            failures.append("v37 segment coalesced a retained source endpoint")
        if values["endpoint_timestamp_corrections"] != 0:
            failures.append("v37 segment repaired a nonmonotonic source timestamp")
        if not _v37_segment_source_evidence_valid(values):
            failures.append("v37 segment output exceeds twice its source evidence")
        unavailable_output = any(
            record["window_due_no_endpoint"] != 0 and
            (not v38_vector_trajectory_contract or
             not _window_completed_output_meets_cadence(record))
            for record in proof_records
        )
        if unavailable_output:
            failures.append(
                "v37 segment selected an output slot without buffered evidence")

    maximum_fallback = segment["maxFallbackPresents"]
    if v37_timestamp_contract:
        # Timestamp resampling may show several distinct target instants from
        # one adjacent source pair, but every successful v37 swap is still
        # classified exactly once as REAL or SYNTHETIC in its health window.
        window_classified, segment_fallback, segment_classified = \
            _rational_visible_accounting(proof_records, values)
    elif v36_evidence_contract:
        # Every post-baseline schema36 window has already passed exact
        # successful-output accounting above. Sum those disjoint windows
        # instead of misclassifying promoted input images as visible swaps.
        window_classified, segment_fallback, segment_classified = \
            _rational_visible_accounting(proof_records, values)
    else:
        window_classified = (values["window_generated"] +
                             values["window_promoted"])
        segment_classified = values["generated"] + values["promoted"]
        segment_fallback = values["presents"] - segment_classified
    window_fallback = values["window_presents"] - window_classified
    if window_fallback < 0 or segment_fallback < 0:
        failures.append("present classification produced a negative fallback count")
    if window_fallback > maximum_fallback:
        failures.append("cadence window contains undeclared fallback presents")
    if segment_fallback > maximum_fallback:
        failures.append("qualification segment contains undeclared fallback presents")
    # Pixel readback is bounded qualification instrumentation and stops before
    # the final cadence window. Validate its cumulative counters from this
    # exact generator, while using only the final production-equivalent health
    # interval and SurfaceFlinger history for cadence. This prevents proof
    # readback from becoming the very source of missed display deadlines.
    changing_records = [
        current for previous, current in zip(evidence_records, evidence_records[1:])
        if current["proof"] > previous["proof"]
    ]
    # The final cadence interval may legitimately be a static menu, dialog, or
    # held frame after a motion-rich proof window.  Motion vectors are
    # instantaneous counters, unlike the cumulative pixel/proof counters
    # below.  Evaluate their peak only across records in which proof sampling
    # was active.  This still fails closed when the field was zero for the
    # entire proof window, without rejecting valid interpolation merely because
    # the last frame stopped moving.
    motion_records = [record for record in changing_records if record["proof"] > 0]
    peak_active = max((record["active"] for record in motion_records), default=0)
    peak_confident = max((record["confident"] for record in motion_records), default=0)
    proof_span_seconds = max(0.0, (
        changing_records[-1]["window_end_ns"] -
        changing_records[0]["window_end_ns"]
    ) / 1_000_000_000.0) if changing_records else 0.0
    window_seconds = values["window_ms"] / 1000.0
    present_rate = values["window_presents"] / window_seconds
    generated_rate = values["window_generated"] / window_seconds
    promoted_rate = values["window_promoted"] / window_seconds
    if v36_evidence_contract:
        expected_output = (int(math.floor(
            values.get("target_millihz", 0) / 1000.0 + 0.5))
            if v43_rational_contract else _schema42_output_fps(
            values["panel"], values["locked"])
            if v42_uniform_contract else _schema37_output_fps(
                values["panel"], values["locked"])
            if v37_timestamp_contract else _schema36_output_fps(
                values["panel"], values["locked"]))
        if v43_rational_contract:
            # With non-commensurate source/output clocks, exact endpoint
            # coincidences depend on their relative phase.  For example,
            # 59.94->60 may classify almost every selected timestamp as an
            # interpolation even though both clocks are correct.  Do not
            # fabricate gcd rates from rounded 60/60 labels.
            expected_exact_real_rate = None
            expected_generated_rate = None
        else:
            expected_exact_real_rate, expected_generated_rate = \
                _schema36_rational_rates(values["locked"], values["output"])
        exact_real_rate = values["window_real_priority"] / window_seconds
    else:
        expected_output = min(values["panel"], values["locked"] * 2)
        expected_exact_real_rate = values["locked"]
        expected_generated_rate = values["output"] - values["locked"]
        exact_real_rate = promoted_rate
    quantized_cadence = _panel_quantized_latch_cadence(
        latency["actualPresentTimestamps"], values["panel"], values["output"])
    output_on_time_fraction = quantized_cadence["quantizedFraction"]

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    require(values["panel"] in (60, 120),
            "physical panel rate is not an audited 60/120-Hz mode")
    if _max_generation_factor(values) >= MAX_GENERATION_FACTOR_V62:
        # Tier protocol 2026-09-01: 50 is not a tier.
        require(values["locked"] in (20, 30, 40, 60),
                "source presentation is not locked to a 20/30/40/60 tier")
    else:
        require(values["locked"] in (20, 30, 40, 50, 60),
                "source presentation is not locked to 20/30/40/50/60 FPS")
    require(values["output"] == expected_output,
            ("reported output does not match the timestamp-resampled panel policy"
             if v37_timestamp_contract else
             "reported output does not match the schema36 rational panel policy"
             if v36_evidence_contract else
             "reported output is not the exact panel-capped x2 source rate"))
    if v42_uniform_contract or v43_rational_contract:
        require(values["panel"] % values["output"] == 0,
                "uniform output label is not a panel-scan divisor")
    if v43_rational_contract:
        require(values["uniform_output_qualified"] == 1 and
                values["panel_scans_per_output"] > 0,
                "rational-clock segment is not uniformly qualified")
    require(values["real"] >= 120, "too few real producer frames")
    require(values["submitted"] >= values["real"],
            "unique source images exceed submitted emulator buffers")
    if not v37_timestamp_contract:
        require(values["window_generated"] <= values["window_promoted"],
                "cadence window synthesized more than one frame per promoted real frame")
    if pair_quota_contract:
        require(values["window_due_selected"] == values["window_presents"] and
                values["window_due_phase_clamped"] == 0,
                "v33 selected scheduler work does not match actual presents")
    # Lifetime counters may span pre-segment tiers, including a transition
    # whose old cadence had a different real/generated ratio. The selected
    # final window is tier-pure and is therefore the fail-closed place to
    # enforce the one-synthetic-per-real contract.
    require(values["cells"] > 0, "motion field has no cells")
    require(peak_active >= values["cells"] * 0.05,
            "motion field is effectively zero")
    require(peak_confident >= values["cells"] * 0.02,
            "motion field has no confident vectors")
    require(values["proof"] >= 30, "too few framebuffer proof samples")
    require(values["synthetic"] >= 15, "too few synthesized framebuffer samples")
    require(values["distinct"] >= values["synthetic"] * 0.80,
            "synthesized frames repeat a real endpoint too often")
    require(values["changing"] >= values["proof"] * 0.50,
            "sampled output content does not change often enough")
    failures.extend(_motion_content_failures(
        values, vector_trajectory_contract=v38_vector_trajectory_contract))
    if dense_contract:
        require(values["dense_enabled"] == 1,
                "dense qualification contract is not actively selected")
        require(values["dense_promotions"] >= 120,
                "too few dense endpoint pairs were measured")
        require(values["dense_passes"] == values["dense_promotions"] *
                (48 if values["proof_schema_version"] in (61, 62) else
                 42 if values["proof_schema_version"] == 60 else
                 40 if values["proof_schema_version"] in (51, 54, 55, 56, 57, 58, 59) else 38),
                "dense pass accounting does not match the fixed budget")
        require(values["dense_proof_cells"] == values["proof"] * DENSE_PROOF_CELLS,
                "dense validation telemetry does not cover every proof cell")
        require(values["dense_backward_valid"] >= values["dense_proof_cells"] * 0.50 and
                values["dense_forward_valid"] >= values["dense_proof_cells"] * 0.50,
                "dense bidirectional final-valid coverage is below 50 percent")
        require(values["dense_submit_max_us"] > 0 and
                values["dense_submit_total_us"] >= values["dense_submit_max_us"],
                "dense CPU submission telemetry is absent or impossible")
        require(values["dense_gpu_budget_us"] == 7333 and
                values["dense_gpu_max_us"] > 0 and
                values["dense_gpu_total_us"] >= values["dense_gpu_max_us"],
                "dense GPU-completion telemetry is absent or impossible")
        require(values["dense_timed_pairs"] >= 120 and
                _segment_dense_timer_pairs_valid(
                    proof_baseline, segment_end, values) and
                values["dense_timer_pending"] < 32 and
                values["dense_timer_disjoint"] == 0 and
                values["dense_timer_unavailable"] == 0 and
                values["dense_timer_stale"] == 0 and
                values["dense_performance_rejected"] == 0,
                "dense asynchronous timer evidence is incomplete or invalid")
        require(values["dense_calibration_runs"] == 1 and
                values["dense_calibration_us"] > 0,
                "dense intrusive calibration or cadence-source binding is invalid")
        require(values["dense_timer_max_queue_age"] <= 64,
                "dense GPU timer result is too stale to bind to its endpoint pair")
        for stage in ("copy", "pyramid", "forward", "reverse", "validation"):
            require(values[f"dense_{stage}_samples"] >= 120 and
                    values[f"dense_{stage}_total_us"] >=
                        values[f"dense_{stage}_max_us"] >=
                        values[f"dense_{stage}_p95_us"] > 0,
                    f"dense {stage} GPU timer telemetry is absent or impossible")
        require(values["dense_warp_samples"] >= 30 and
                values["dense_warp_samples"] <= values["dense_warp_sequence"] and
                values["dense_warp_completed_sequence"] <=
                    values["dense_warp_sequence"] and
                values["dense_warp_completed_sequence"] > 0 and
                values["dense_warp_total_us"] >= values["dense_warp_max_us"] >=
                    values["dense_warp_p95_us"] > 0,
                "dense visible-warp GPU timer telemetry is absent or impossible")
        require(max(values["dense_copy_p95_us"], values["dense_pyramid_p95_us"],
                    values["dense_forward_p95_us"], values["dense_reverse_p95_us"],
                    values["dense_validation_p95_us"], values["dense_warp_p95_us"]) <=
                    values["dense_gpu_budget_us"],
                "dense stage p95 exceeds the generated-frame deadline budget")
        require(values["dense_gpu_max_us"] <= values["dense_gpu_budget_us"],
                "dense GPU-complete pair exceeds the generated-frame deadline budget")
        if dense_v28_contract:
            require(values["dense_combined_pair_warp_us"] > 0 and
                    values["dense_combined_pair_warp_us"] ==
                        values["dense_gpu_max_us"] + values["dense_warp_p95_us"] and
                    values["dense_combined_pair_warp_us"] <=
                        values["dense_gpu_budget_us"],
                    "v28 combined estimator plus visible warp exceeds the deadline")
            # Timestamp resampling is allowed to choose only fractional target
            # instants for an entire segment.  In that case no visible swap is
            # classified as PRESENT_REAL, so the legacy REAL-only promotion
            # wall series has a legitimate zero segment delta.  Every v37 swap
            # is still covered by the mandatory present/swap wall series below.
            require(_dense_v28_wall_telemetry_valid(
                        values, v37_timestamp_contract),
                    "v32 wall-time telemetry or synchronous-proof ban is invalid")
            require(values["dense_signature_sequence"] >= 120 and
                    values["dense_signature_ready"] >= 120 and
                    values["dense_signature_ready"] <=
                        values["dense_signature_sequence"] and
                    values["dense_signature_unavailable"] == 0 and
                    values["dense_signature_pending"] < 4 and
                    values["dense_signature_max_queue_age"] <= 4 and
                    _v31_signature_identity_valid(values),
                    "v31 ES3 core-query signature evidence is incomplete or invalid")
            require(values["dense_proof_atlas_capability"] == 63 and
                    values["dense_proof_atlas_layout"] ==
                        (5 if v37_timestamp_contract else
                         4 if v36_evidence_contract else
                         3 if v35_diagnostic_contract else
                         2 if diagnostic_contract else 1) and
                    _segment_async_atlas_completion_valid(values) and
                    values["dense_proof_atlas_max_queue_age"] <= 8 and
                    values["dense_proof_atlas_ring_full"] == 0 and
                    values["dense_proof_atlas_errors"] == 0 and
                    values["dense_proof_atlas_tag_errors"] == 0 and
                    values["dense_proof_atlas_discarded"] == 0 and
                    values["dense_proof_atlas_sync_fallback"] == 0,
                    "v32 asynchronous proof atlas is incomplete or invalid")
            require(values["dense_callback_delta_samples"] >= 120 and
                    values["dense_callback_delta_total_us"] >=
                        values["dense_callback_delta_max_us"] > 0 and
                    values["dense_present_wall_samples"] >= 120 and
                    values["dense_present_wall_total_us"] >=
                        values["dense_present_wall_max_us"] >=
                        values["dense_present_wall_p95_us"] > 0 and
                    values["dense_swap_wall_samples"] >= 120 and
                    values["dense_swap_wall_total_us"] >=
                        values["dense_swap_wall_max_us"] >=
                        values["dense_swap_wall_p95_us"] > 0 and
                    values["dense_proof_enqueue_wall_samples"] ==
                        values["dense_proof_atlas_enqueued"] and
                    values["dense_proof_enqueue_wall_total_us"] >=
                        values["dense_proof_enqueue_wall_max_us"] >=
                        values["dense_proof_enqueue_wall_p95_us"] > 0 and
                    values["dense_proof_poll_wall_samples"] >=
                        values["dense_proof_atlas_completed"] and
                    values["dense_proof_poll_wall_total_us"] >=
                        values["dense_proof_poll_wall_max_us"] >=
                        values["dense_proof_poll_wall_p95_us"] > 0,
                    "v32 callback/present/swap/proof wall telemetry is invalid")
        require(values["dense_max_flow_pixels"] == 47,
                "dense flow range exceeds its bounded search walk")
        if dense_v28_contract:
            require(_v28_workload_identity_valid(values, input_width, input_height),
                    "v28 reduced-analysis workload does not match its contract")
        elif dense_v27_contract:
            require(_v27_workload_identity_valid(values, input_width, input_height),
                    "v27 reduced-analysis workload does not match its contract")
        else:
            require(values["dense_variant"] in (None, "fragment-256x144-v26") and
                    values["dense_analysis_width"] in (0, 256) and
                    values["dense_analysis_height"] in (0, 144) and
                    values["dense_solve_texels"] in (0, 405504) and
                    values["dense_total_texels"] in (0, 502272),
                    "v26 evidence is mixed with a different dense workload")
    require(proof_span_seconds >= 11.0,
            "motion-compensated pixel proof window is too short")
    if v39_present_timed_contract:
        require(values.get("presentation_timing_mode") ==
                    "egl-android-next-vsync" and
                values.get("cadence_reject_consecutive_windows") == 3,
                "v39 Android presentation pacing contract is missing")
    require(window_seconds >= 0.8, "cadence window is too short")
    exact_target_hz = (values.get("target_millihz", 0) / 1000.0
                       if v43_rational_contract else values["output"])
    exact_source_hz = (values.get("source_millihz", 0) / 1000.0
                       if v43_rational_contract else values["locked"])
    exact_panel_hz = (values.get("panel_millihz", 0) / 1000.0
                      if v43_rational_contract else values["panel"])
    require(abs(present_rate - exact_target_hz) <=
            max(3.0, exact_target_hz * 0.04),
            "generator did not present at its reported output target")
    if v37_timestamp_contract:
        # Max-2x is an ownership/count invariant, not a floating-rate
        # approximation.  A 998 ms HEALTH window can report 120 presents and
        # 59 promotions as 120.240 and 59.118 Hz; comparing those rounded
        # rates misses the exact boundary by millihertz even though the active
        # pair and bounded FIFO fully account for every output.  The same
        # exact retained-endpoint predicate is already required above for the
        # rebased segment; keep this final gate in that integer domain too.
        require(_v37_segment_source_evidence_valid(values),
                "timestamp-resampled output exceeds its contract factor of the consumed source cadence")
        require(promoted_rate >= exact_source_hz * 0.92,
                "consumed source cadence does not sustain the selected source tier")
    else:
        require(abs(promoted_rate - values["locked"]) <=
                max(2.5, values["locked"] * 0.08),
                "real-frame cadence does not match the selected source lock")
    if v36_evidence_contract and not v37_timestamp_contract:
        require(abs(exact_real_rate - expected_exact_real_rate) <=
                max(2.5, expected_exact_real_rate * 0.08),
                "exact-real output cadence does not match the rational lattice")
    if not v37_timestamp_contract:
        require(abs(generated_rate - expected_generated_rate) <=
                max(3.5, expected_generated_rate * 0.08),
                "generated-frame cadence does not fill the exact source-to-panel gap")
    require(abs(latency["targetHz"] - exact_panel_hz) <=
            max(2.0, exact_panel_hz * 0.02),
            "SurfaceFlinger physical refresh does not match reported panel rate")
    require(abs(latency["measuredHz"] - exact_target_hz) <=
            max(2.0, exact_target_hz * 0.05),
            "SurfaceFlinger did not latch at the reported output cadence")
    require(quantized_cadence["valid"],
            "SurfaceFlinger latch cadence is not a balanced panel-vsync subset")
    # Both sources use Android's monotonic clock. Never infer an offset from
    # the endpoints being compared: doing so can force an unrelated trace to
    # align by construction. Require a meaningful raw overlap instead.
    inside = [timestamp for timestamp in latency["actualPresentTimestamps"]
              if values["window_start_ns"] <= timestamp <= values["window_end_ns"]]
    require(len(inside) >= max(31, int(latency["frames"] * 0.25)),
            "SurfaceFlinger evidence does not overlap the selected generator window")
    require(latency["firstActualPresentNs"] >= session_start and
            latency["lastActualPresentNs"] <= session_end,
            "SurfaceFlinger evidence is outside the bound qualification session")

    report = {
        "passed": not failures,
        "failures": failures,
        "proofContract": values["proof_contract"],
        "proofSchemaVersion": values["proof_schema_version"],
        "role": role,
        "displayId": display_id,
        "qualification": {
            "manifestSha256": _sha256(qualification_path),
            "identity": qualification_identity,
            "segment": segment,
            "transition": transition,
            "proofReset": validated_reset,
        },
        "generator": values,
        "absoluteGeneratorAtSegmentEnd": absolute_values,
        "presentAccounting": {
            "windowPresents": values["window_presents"],
            "windowGenerated": values["window_generated"],
            "windowPromoted": values["window_promoted"],
            "windowClassified": window_classified,
            "windowFallback": window_fallback,
            "segmentPresents": values["presents"],
            "segmentGenerated": values["generated"],
            "segmentPromoted": values["promoted"],
            "segmentClassified": segment_classified,
            "segmentFallback": segment_fallback,
            "maxFallbackPresents": maximum_fallback,
        },
        "sourceContent": {
            "submittedBuffers": values["submitted"],
            "uniqueImages": values["real"],
            "duplicateBuffers": values["submitted"] - values["real"],
        },
        "surfaceFlinger": {key: value for key, value in latency.items()
                           if key != "actualPresentTimestamps"},
        "cadence": {
            "windowSeconds": window_seconds,
            "realFps": promoted_rate,
            "generatedFps": generated_rate,
            "outputFps": present_rate,
            "expectedGeneratedFps": expected_generated_rate,
            "minimumGeneratedFps": (max(0.0,
                exact_target_hz - exact_source_hz)
                if v43_rational_contract else expected_generated_rate),
            "outputOnTimeFraction": output_on_time_fraction,
            "panelQuantizedPhaseExcursionTicks":
                    quantized_cadence["phaseExcursionTicks"],
        },
        "proofWindowSeconds": proof_span_seconds,
        "proofWindowPeakMotion": {
            "activeVectors": peak_active,
            "confidentVectors": peak_confident,
        },
        "candidateLattice": {
            "regionSamples": values["lattice_samples"],
            "backwardCoherentRegions": values["lattice_backward_coherent"],
            "forwardCoherentRegions": values["lattice_forward_coherent"],
            "backwardBoundaryRegions": values["lattice_backward_boundary"],
            "forwardBoundaryRegions": values["lattice_forward_boundary"],
            "backwardCoherentBoundaryRegions":
                values["lattice_backward_coherent_boundary"],
            "forwardCoherentBoundaryRegions":
                values["lattice_forward_coherent_boundary"],
            "lastBackwardCoherentRegionCount": values["lattice_backward_count"],
            "lastForwardCoherentRegionCount": values["lattice_forward_count"],
            "lastBackwardBoundaryRegionCount":
                values["lattice_backward_boundary_count"],
            "lastForwardBoundaryRegionCount":
                values["lattice_forward_boundary_count"],
            "lastBackwardCoherentBoundaryRegionCount":
                values["lattice_backward_coherent_boundary_count"],
            "lastForwardCoherentBoundaryRegionCount":
                values["lattice_forward_coherent_boundary_count"],
            "lastBackwardPeakSupportByte":
                values["lattice_backward_peak_support"],
            "lastForwardPeakSupportByte": values["lattice_forward_peak_support"],
        },
        "regionalFlow": {
            "regionSamples": values["regional_samples"],
            "backwardSupportedRegions": values["regional_backward_supported"],
            "forwardSupportedRegions": values["regional_forward_supported"],
            "backwardNeighborRegions": values["regional_backward_neighbor"],
            "forwardNeighborRegions": values["regional_forward_neighbor"],
            "backwardConstantNeighborRegions":
                values["regional_backward_constant_neighbor"],
            "forwardConstantNeighborRegions":
                values["regional_forward_constant_neighbor"],
            "backwardGradientNeighborRegions":
                values["regional_backward_gradient_neighbor"],
            "forwardGradientNeighborRegions":
                values["regional_forward_gradient_neighbor"],
            "backwardAcceptedRegions": values["regional_backward_accepted"],
            "forwardAcceptedRegions": values["regional_forward_accepted"],
            "backwardAcceptedBoundaryRegions":
                values["regional_backward_accepted_boundary"],
            "forwardAcceptedBoundaryRegions":
                values["regional_forward_accepted_boundary"],
            "backwardCycleAcceptedRegions": values["regional_backward_cycle"],
            "forwardCycleAcceptedRegions": values["regional_forward_cycle"],
            "lastBackwardAcceptedRegionCount":
                values["regional_backward_count"],
            "lastForwardAcceptedRegionCount": values["regional_forward_count"],
            "lastBackwardAcceptedBoundaryRegionCount":
                values["regional_backward_accepted_boundary_count"],
            "lastForwardAcceptedBoundaryRegionCount":
                values["regional_forward_accepted_boundary_count"],
            "lastBackwardCycleAcceptedRegionCount":
                values["regional_backward_cycle_count"],
            "lastForwardCycleAcceptedRegionCount":
                values["regional_forward_cycle_count"],
            "lastBackwardSupportedRegionCount":
                values["regional_backward_supported_count"],
            "lastForwardSupportedRegionCount":
                values["regional_forward_supported_count"],
            "lastBackwardNeighborRegionCount":
                values["regional_backward_neighbor_count"],
            "lastForwardNeighborRegionCount":
                values["regional_forward_neighbor_count"],
            "lastBackwardConstantNeighborRegionCount":
                values["regional_backward_constant_neighbor_count"],
            "lastForwardConstantNeighborRegionCount":
                values["regional_forward_constant_neighbor_count"],
            "lastBackwardGradientNeighborRegionCount":
                values["regional_backward_gradient_neighbor_count"],
            "lastForwardGradientNeighborRegionCount":
                values["regional_forward_gradient_neighbor_count"],
            "lastBackwardPeakSupportByte":
                values["regional_backward_support"],
            "lastForwardPeakSupportByte": values["regional_forward_support"],
            "lastBackwardPeakConfidenceByte":
                values["regional_backward_confidence"],
            "lastForwardPeakConfidenceByte":
                values["regional_forward_confidence"],
        },
        "surfaceFlingerRawOverlapFrames": len(inside),
        "selectedHealthRecordIndex": selected_index,
        "syntheticDistinctFraction": (
            values["distinct"] / values["synthetic"] if values["synthetic"] else 0.0
        ),
        "substantivePixelFraction": (
            values["substantive_pixels"] / values["eligible_pixels"]
            if values["eligible_pixels"] else 0.0
        ),
        "nonCrossfadePixelFraction": (
            values["non_crossfade_pixels"] / values["eligible_pixels"]
            if values["eligible_pixels"] else 0.0
        ),
        "spatialMotionSynthesisFraction": (
            values["motion_synthesized_pixels"] / values["motion_eligible_pixels"]
            if values["motion_eligible_pixels"] else 0.0
        ),
        "vectorTrajectoryContract": v38_vector_trajectory_contract,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--latency", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--role", default="primary",
                        choices=("primary", "secondary"))
    parser.add_argument("--display-id", type=int, default=0)
    parser.add_argument("--qualification-manifest", required=True, type=Path)
    parser.add_argument("--segment-id", required=True)
    args = parser.parse_args()
    try:
        report = verify(args.log, args.latency, role=args.role,
                        display_id=args.display_id,
                        qualification_path=args.qualification_manifest,
                        segment_id=args.segment_id)
    except (OSError, ValueError) as failure:
        report = {"passed": False, "failures": [str(failure)]}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
