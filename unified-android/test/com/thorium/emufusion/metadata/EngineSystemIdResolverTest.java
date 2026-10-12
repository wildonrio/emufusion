package com.thorium.emufusion.metadata;

import com.thorium.emufusion.TestSupport;

public final class EngineSystemIdResolverTest {
    public static void main(String[] args) {
        TestSupport.equal("gamecube", EngineSystemIdResolver.canonical("gc"),
                "live GameCube shortname");
        TestSupport.equal("3ds", EngineSystemIdResolver.canonical("n3ds"),
                "auto-import 3DS shortname");
        TestSupport.equal("megadrive", EngineSystemIdResolver.canonical("genesis"),
                "legacy Genesis shortname");
        TestSupport.equal("nds", EngineSystemIdResolver.canonical("nds"),
                "DS remains canonical for melonDS");
        TestSupport.equal("wii", EngineSystemIdResolver.canonical("wii"),
                "canonical systems pass through");

        String gamecube = MetadataGameLaunchCommand.build("gc", "dolphin");
        TestSupport.truth(gamecube.contains("--es system gamecube"),
                "GameCube command uses Dolphin's canonical system");
        TestSupport.truth(gamecube.contains("--es engine_id dolphin"),
                "GameCube command uses Dolphin");
        String threeDs = MetadataGameLaunchCommand.build("n3ds", "azahar");
        TestSupport.truth(threeDs.contains("--es system 3ds"),
                "3DS command uses Azahar's canonical system");
        TestSupport.truth(threeDs.contains("--es engine_id azahar"),
                "3DS command uses Azahar");
        String genesis = MetadataGameLaunchCommand.build("genesis", "blastem");
        TestSupport.truth(genesis.contains("--es system megadrive"),
                "Genesis command uses BlastEm's canonical system");

        String collections = "collection: GameCube\nshortname: gc\ngame: Prime\n" +
                "collection: Nintendo 3DS\nshortname: n3ds\ngame: Zelda\n";
        String rewritten = MetadataLaunchNormalizer.rewrite(collections, system -> {
            String canonical = EngineSystemIdResolver.canonical(system);
            return MetadataGameLaunchCommand.build(canonical,
                    "gamecube".equals(canonical) ? "dolphin" : "azahar");
        });
        TestSupport.truth(rewritten.contains(
                "--es system gamecube --es engine_id dolphin"),
                "GameCube collection route is canonical");
        TestSupport.truth(rewritten.contains(
                "--es system 3ds --es engine_id azahar"),
                "3DS collection route is canonical");
    }
}
