package com.thorium.lucent.cheats;

/** One toggleable cheat: a stable id, a display name, and the core's raw code. */
public final class Cheat {
    /** Stable across database updates; this is what the enabled set records. */
    public final String id;
    public final String name;
    public final String description;
    /**
     * Passed to the core verbatim. Multi-line codes are joined with '+', which
     * is the separator libretro cores parse as "one cheat, several lines".
     */
    public final String code;

    public Cheat(String id, String name, String description, String code) {
        if (id == null || id.isEmpty()) throw new IllegalArgumentException("cheat id required");
        if (code == null || code.trim().isEmpty())
            throw new IllegalArgumentException("cheat code required");
        this.id = id;
        this.name = name == null || name.isEmpty() ? id : name;
        this.description = description == null ? "" : description;
        this.code = code.trim();
    }

    @Override public boolean equals(Object other) {
        return other instanceof Cheat && id.equals(((Cheat) other).id);
    }

    @Override public int hashCode() { return id.hashCode(); }

    @Override public String toString() { return "Cheat{" + id + "}"; }
}
