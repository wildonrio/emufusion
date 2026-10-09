package com.thorium.preview;

import java.io.File;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Immutable platform catalog shared by discovery, identification and metadata. */
final class GameSystems {
    static final class SystemDef {
        final String folder;
        final String collection;
        final String libretro;
        final List<String> extensions;
        final List<String> aliases;
        final String videoArchive;
        final String metacriticPlatform;
        final String metacriticSlug;

        SystemDef(String folder, String collection, String libretro, String extensions,
                  String aliases, String videoArchive, String metacriticPlatform,
                  String metacriticSlug) {
            this.folder = folder;
            this.collection = collection;
            this.libretro = libretro;
            this.extensions = words(extensions);
            this.aliases = words(aliases);
            this.videoArchive = videoArchive;
            this.metacriticPlatform = metacriticPlatform;
            this.metacriticSlug = metacriticSlug;
        }
    }

    private static final Map<String, SystemDef> BY_FOLDER = new LinkedHashMap<>();
    private static final Map<String, SystemDef> BY_ALIAS = new LinkedHashMap<>();

    static {
        // Chronological catalog. Directory aliases are normalized before lookup,
        // so "Sony PlayStation 2", "PS2", and "playstation-2" all converge.
        add("odyssey2", "Magnavox Odyssey²", "Magnavox - Odyssey2", "bin rom",
                "odyssey2 videopac magnavoxodyssey2", "", "", "");
        add("arcade", "Arcade", "MAME", "zip 7z chd",
                "arcade mame fbneo fba finalburnneo", "", "", "");
        add("atari2600", "Atari 2600", "Atari - 2600", "a26 bin rom",
                "atari2600 2600", "", "", "");
        add("intellivision", "Mattel Intellivision", "Mattel - Intellivision", "int bin rom",
                "intellivision mattelintellivision", "", "", "");
        add("apple2", "Apple II", "Apple - II", "dsk po do nib 2mg",
                "apple2 appleii", "", "", "");
        add("atari5200", "Atari 5200", "Atari - 5200", "a52 bin rom",
                "atari5200 5200", "", "", "");
        add("colecovision", "ColecoVision", "Coleco - ColecoVision", "col bin rom",
                "coleco colecovision", "", "", "");
        add("c64", "Commodore 64", "Commodore - 64", "d64 t64 prg crt tap",
                "c64 commodore64", "", "", "");
        add("atari800", "Atari 8-bit", "Atari - 8-bit", "atr xfd atx cas",
                "atari800 atari8bit", "", "", "");
        add("nes", "Nintendo Entertainment System", "Nintendo - Nintendo Entertainment System",
                "nes unf unif fds", "nes famicom fc nintendoentertainmentsystem", 
                "nintendo-entertainment-system-video-snaps", "", "");
        add("sg1000", "Sega SG-1000", "Sega - SG-1000", "sg bin rom",
                "sg1000 segasg1000", "", "", "");
        add("amstradcpc", "Amstrad CPC", "Amstrad - CPC", "dsk sna tap cdt",
                "amstrad amstradcpc cpc", "", "", "");
        add("mastersystem", "Sega Master System", "Sega - Master System - Mark III", "sms bin rom",
                "mastersystem segamastersystem markiii", "", "", "");
        add("atari7800", "Atari 7800", "Atari - 7800", "a78 bin rom",
                "atari7800 7800", "", "", "");
        add("amiga", "Commodore Amiga", "Commodore - Amiga", "adf adz dms ipf hdf lha",
                "amiga commodoreamiga", "", "", "");
        add("atarist", "Atari ST", "Atari - ST", "st msa stx dim",
                "atarist st", "", "", "");
        add("pcengine", "NEC PC Engine", "NEC - PC Engine - TurboGrafx 16", "pce",
                "pcengine turbografx16 tg16", "", "", "");
        add("megadrive", "Sega Genesis", "Sega - Mega Drive - Genesis", "gen md bin smd",
                "megadrive genesis segagenesis segamegadrive", 
                "sega-genesis-video-snaps", "", "");
        add("gb", "Nintendo Game Boy", "Nintendo - Game Boy", "gb",
                "gb gameboy nintendogameboy", "NintendoGameBoyVideoSnaps", "", "");
        add("gamegear", "Sega Game Gear", "Sega - Game Gear", "gg",
                "gamegear segagamegear", "SegaGameGearVideoSnaps", "", "");
        add("neogeo", "SNK Neo Geo", "SNK - Neo Geo", "zip 7z",
                "neogeo snkneogeo", "", "", "");
        add("snes", "Super Nintendo Entertainment System",
                "Nintendo - Super Nintendo Entertainment System", "smc sfc fig",
                "snes superfamicom supernintendo supernintendoentertainmentsystem", 
                "super-nintendo-entertainment-system-video-snaps", "", "");
        add("segacd", "Sega CD", "Sega - Mega-CD - Sega CD", "chd cue iso",
                "segacd megacd", "", "", "");
        add("pcenginecd", "NEC PC Engine CD", "NEC - PC Engine CD - TurboGrafx-CD", "chd cue iso",
                "pcenginecd turbografxcd tgcd", "", "", "");
        add("3do", "3DO Interactive Multiplayer", "The 3DO Company - 3DO", "iso chd cue",
                "3do panasonic3do", "", "", "");
        add("amigacd32", "Commodore Amiga CD32", "Commodore - Amiga CD32", "iso chd cue",
                "amigacd32 cd32", "", "", "");
        add("jaguar", "Atari Jaguar", "Atari - Jaguar", "jag j64 rom",
                "jaguar atarijaguar", "", "", "");
        add("sega32x", "Sega 32X", "Sega - 32X", "32x bin",
                "sega32x 32x", "", "", "");
        add("saturn", "Sega Saturn", "Sega - Saturn", "chd cue iso",
                "saturn segasaturn", "", "", "");
        add("psx", "Sony PlayStation", "Sony - PlayStation", "chd cue m3u pbp bin",
                "psx ps1 playstation sonyplaystation", 
                "sony-playstation-video-snaps", "PlayStation", "playstation");
        add("virtualboy", "Nintendo Virtual Boy", "Nintendo - Virtual Boy", "vb",
                "virtualboy nintendovirtualboy", "", "", "");
        add("n64", "Nintendo 64", "Nintendo - Nintendo 64", "z64 n64 v64",
                "n64 nintendo64", "Nintendo64VideoSnaps", "Nintendo 64", "nintendo-64");
        add("neogeocd", "SNK Neo Geo CD", "SNK - Neo Geo CD", "chd cue",
                "neogeocd snkneogeocd", "", "", "");
        add("gbc", "Nintendo Game Boy Color", "Nintendo - Game Boy Color", "gbc gb",
                "gbc gameboycolor nintendogameboycolor", "NintendoGameBoyColorVideoSnaps", "", "");
        add("dreamcast", "Sega Dreamcast", "Sega - Dreamcast", "gdi chd cdi cue",
                "dreamcast segadreamcast dc", "SegaDreamcastVideoSnaps", "Dreamcast", "dreamcast");
        add("ngp", "SNK Neo Geo Pocket", "SNK - Neo Geo Pocket", "ngp",
                "ngp neogeopocket", "", "", "");
        add("wonderswan", "Bandai WonderSwan", "Bandai - WonderSwan", "ws",
                "wonderswan ws", "", "", "");
        add("ps2", "Sony PlayStation 2", "Sony - PlayStation 2", "iso chd cso nrg",
                "ps2 playstation2 sonyplaystation2", "SonyPlaystation2VideoSnaps", 
                "PlayStation 2", "playstation-2");
        add("wonderswancolor", "Bandai WonderSwan Color", "Bandai - WonderSwan Color", "wsc",
                "wonderswancolor wsc", "", "", "");
        add("gba", "Nintendo Game Boy Advance", "Nintendo - Game Boy Advance", "gba",
                "gba gameboyadvance nintendogameboyadvance", 
                "NintendoGameBoyAdvanceVideoSnaps", "Game Boy Advance", "game-boy-advance");
        add("gc", "Nintendo GameCube", "Nintendo - GameCube", "rvz iso ciso gcz",
                "gc gamecube ngc nintendogamecube", "NintendoGameCubeVideoSnaps", 
                "GameCube", "gamecube");
        add("xbox", "Microsoft Xbox", "Microsoft - Xbox", "iso xiso",
                "xbox microsoftxbox", "", "Xbox", "xbox");
        add("nds", "Nintendo DS", "Nintendo - Nintendo DS", "nds",
                "nds ds nintendods", "NintendoDSVideoSnaps", "Nintendo DS", "nintendo-ds");
        add("psp", "Sony PlayStation Portable", "Sony - PlayStation Portable", "iso cso pbp",
                "psp playstationportable sonypsp", "SonyPSPVideoSnaps", "PSP", "psp");
        add("xbox360", "Microsoft Xbox 360", "Microsoft - Xbox 360", "iso xex",
                "xbox360 microsoftxbox360", "", "Xbox 360", "xbox-360");
        // PKG is an installation package, not a directly bootable title. The
        // importer separately recognizes decrypted PS3_GAME/USRDIR/EBOOT.BIN
        // directory dumps; only verified ISO remains a file launch shape.
        add("ps3", "Sony PlayStation 3", "Sony - PlayStation 3", "iso",
                "ps3 playstation3 sonyplaystation3", "", "PlayStation 3", "playstation-3");
        add("wii", "Nintendo Wii", "Nintendo - Wii", "wbfs rvz iso wad",
                "wii nintendowii", "nintendo-wii-video-snaps", "Wii", "wii");
        // .3dsx is an executable homebrew-application format, not a dumped
        // retail game format. Including it caused utilities such as Universal
        // Updater to appear in the game library.
        add("n3ds", "Nintendo 3DS", "Nintendo - Nintendo 3DS", "3ds cia cci",
                "n3ds 3ds nintendo3ds", "nintendo-3ds-video-snaps", "3DS", "3ds");
        add("psvita", "Sony PlayStation Vita", "Sony - PlayStation Vita", "vpk",
                "psvita vita playstationvita sonyplaystationvita", "", 
                "PlayStation Vita", "playstation-vita");
        add("wiiu", "Nintendo Wii U", "Nintendo - Wii U", "wux wua rpx",
                "wiiu nintendowiiu", "nintendo-wii-u-video-snaps", "Wii U", "wii-u");
        // The built-in PC route is DOSBox Pure. Keep this list aligned with the
        // pinned core's retro_system_info instead of accepting MSI/CMD files
        // that the internal engine cannot load. Windows 3.x/9x guests remain
        // user-supplied disk images; EmuFusion never bundles an operating system.
        add("windows", "Microsoft Windows", "Microsoft - Windows",
                "zip dosz exe com bat iso chd cue ins img ima vhd jrc m3u m3u8 conf",
                "windows windows10 pc", "", "PC", "pc");
        add("switch", "Nintendo Switch", "Nintendo - Nintendo Switch", "nsp xci",
                "switch nintendoswitch", "nintendo-switch-video-archive", 
                "Nintendo Switch", "switch");
        add("dos", "DOS", "DOS", "exe com bat conf zip",
                "dos msdos", "", "PC", "pc");
        add("scummvm", "ScummVM", "ScummVM", "scummvm",
                "scummvm", "", "PC", "pc");
        add("zxspectrum", "Sinclair ZX Spectrum", "Sinclair - ZX Spectrum", "tzx tap z80 sna",
                "zxspectrum sinclairzxspectrum spectrum", "", "", "");
        add("msx", "Microsoft MSX", "Microsoft - MSX", "rom mx1 mx2 dsk cas",
                "msx msx1 msx2", "", "", "");
    }

    private static void add(String folder, String collection, String libretro, String extensions,
                            String aliases, String videoArchive, String mcPlatform,
                            String mcSlug) {
        SystemDef def = new SystemDef(folder, collection, libretro, extensions, aliases,
                videoArchive, mcPlatform, mcSlug);
        BY_FOLDER.put(folder, def);
        BY_ALIAS.put(normalizeAlias(folder), def);
        BY_ALIAS.put(normalizeAlias(collection), def);
        for (String alias : def.aliases) BY_ALIAS.put(normalizeAlias(alias), def);
    }

    static SystemDef byFolder(String folder) { return BY_FOLDER.get(folder); }
    static Iterable<SystemDef> all() { return BY_FOLDER.values(); }

    /** Resolves a folder name, collection name, or any declared alias. */
    static SystemDef byAlias(String value) {
        return value == null || value.isEmpty() ? null : BY_ALIAS.get(normalizeAlias(value));
    }

    static SystemDef byPath(File file) {
        String ext = extension(file.getName());
        File parent = file.getParentFile();
        for (int depth = 0; parent != null && depth < 6; depth++, parent = parent.getParentFile()) {
            String hint = normalizeAlias(parent.getName());
            SystemDef def = BY_ALIAS.get(hint);
            if (def != null && def.extensions.contains(ext)) return def;
            if ("pce".equals(hint) && ("chd".equals(ext) || "cue".equals(ext) || "iso".equals(ext)))
                return BY_FOLDER.get("pcenginecd");
            hint = hint.replaceFirst("^other", "")
                    .replaceFirst("(?:roms?|games?)$", "");
            def = BY_ALIAS.get(hint);
            if (def != null && def.extensions.contains(ext)) return def;
        }
        return null;
    }

    static SystemDef unambiguousByExtension(String extension) {
        String ext = extension.toLowerCase(Locale.US);
        SystemDef match = null;
        for (SystemDef system : BY_FOLDER.values()) {
            if (!system.extensions.contains(ext)) continue;
            if (match != null) return null;
            match = system;
        }
        return match;
    }

    static boolean isKnownSystemDirectory(File directory) {
        return directory != null && BY_ALIAS.containsKey(normalizeAlias(directory.getName()));
    }

    private static List<String> words(String value) {
        String trimmed = value == null ? "" : value.trim();
        return trimmed.isEmpty() ? Collections.emptyList() :
                Collections.unmodifiableList(Arrays.asList(trimmed.split("\\s+")));
    }

    private static String normalizeAlias(String value) {
        return value == null ? "" : value.toLowerCase(Locale.US).replaceAll("[^a-z0-9]", "");
    }

    private static String extension(String name) {
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot + 1).toLowerCase(Locale.US);
    }

    private GameSystems() {}
}
