package com.thorium.emufusion.state;

/** A failed validation is explicit; callers must boot normally and retain the snapshot. */
public final class StateLoadResult {
    public enum Status {
        OK, NOT_FOUND, IDENTITY_MISMATCH, CORRUPT, IO_ERROR
    }

    public final Status status;
    public final StateSnapshot snapshot;
    public final byte[] state;
    public final String detail;

    private StateLoadResult(Status status, StateSnapshot snapshot, byte[] state, String detail) {
        this.status = status;
        this.snapshot = snapshot;
        this.state = state;
        this.detail = detail;
    }

    static StateLoadResult ok(StateSnapshot snapshot, byte[] state) {
        return new StateLoadResult(Status.OK, snapshot, state, "");
    }

    static StateLoadResult failure(Status status, StateSnapshot snapshot, String detail) {
        return new StateLoadResult(status, snapshot, null, detail == null ? "" : detail);
    }
}
