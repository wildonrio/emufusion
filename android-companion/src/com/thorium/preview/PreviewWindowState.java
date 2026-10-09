package com.thorium.preview;

/** Window presence is independent of the Activity that currently has focus. */
final class PreviewWindowState {
    private Object owner;
    private boolean started;

    synchronized void created(Object instance) {
        if (instance == null) return;
        owner = instance;
        started = false;
    }

    synchronized void started(Object instance) {
        if (owner == instance && owner != null) started = true;
    }

    synchronized void stopped(Object instance) {
        if (owner == instance) started = false;
    }

    synchronized void destroyed(Object instance) {
        if (owner != instance) return;
        owner = null;
        started = false;
    }

    synchronized boolean isVisible() {
        return owner != null && started;
    }
}
