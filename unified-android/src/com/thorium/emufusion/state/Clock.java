package com.thorium.emufusion.state;

/** Injectable time source so checkpoint behavior can be tested without sleeping. */
public interface Clock {
    long wallTimeMillis();

    Clock SYSTEM = new Clock() {
        @Override public long wallTimeMillis() {
            return System.currentTimeMillis();
        }
    };
}
