"""The library does no needless work while the Thor sleeps.

October 24, 2026, both panels off for hours: the device stayed at 75-82 C.
EmuFusion used ~185% CPU. The library media pass spent 4-5 s of CPU per
game: every title lookup re-derived all ~6000 entries of the system's
thumbnail listing with a dozen regular expressions each, several lookups
per game, freeing ~75 MB of garbage a second. And the lower-screen preview
kept two looping movies running through the hardware decoder because
nothing paused them when its window stopped.
"""
import re
import unittest

from tools.tests.test_first_install_startup import ROOT

IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'
MATCHER = ROOT / 'unified-android/src/com/thorium/emufusion/metadata/TitleMatcher.java'
PREVIEW = ROOT / 'android-companion/src/com/thorium/preview/PreviewActivity.java'
MATCHER_TEST = ROOT / 'unified-android/test/com/thorium/emufusion/metadata/TitleMatcherTest.java'


def body(source, start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin + len(start))]


class PreparedCatalogTest(unittest.TestCase):
    def setUp(self):
        self.importer = IMPORTER.read_text()
        self.matcher = MATCHER.read_text()

    def test_the_importer_prepares_each_listing_once_per_file_version(self):
        entries = body(self.importer, 'private TitleMatcher.Catalog catalogEntries(',
                       '\n    }\n')
        self.assertIn('String key = cache.getPath() + ":" + cache.lastModified() + ":" + '
                      'cache.length();', entries)
        self.assertIn('TitleMatcher.Catalog prepared = preparedCatalogs.get(key);', entries)
        self.assertIn('if (prepared != null) return prepared;', entries)
        # An unchanged, fresh listing is not even read again.
        self.assertLess(entries.index('if (prepared != null) return prepared;'),
                        entries.index('if (html == null) html = readText(cache);'))
        self.assertIn('prepared = new TitleMatcher.Catalog(hrefs);', entries)
        # Bounded: the per-game pass needs one system's listings at a time.
        self.assertIn('private static final int PREPARED_CATALOGS = 6;', self.importer)
        self.assertIn('return size() > PREPARED_CATALOGS;', self.importer)

    def test_the_checksum_lookup_does_not_decode_the_listing_per_game(self):
        lookup = body(self.importer, 'private CatalogMatch noIntroMatch(', '/** The game')
        self.assertIn('.withDecodedName(exact);', lookup)
        self.assertNotIn('for (String href : catalogEntries(', lookup)

    def test_questions_use_the_prepared_indexes(self):
        select = body(self.matcher, 'public static Match select(', '/** Convenience wrapper')
        self.assertIn('Catalog catalog = Catalog.of(candidateNames);', select)
        self.assertNotIn('for (String name : candidateNames)', select)
        probe = body(self.matcher, 'public static boolean hasAnyCandidate(', '/** The strength')
        self.assertIn('Catalog catalog = Catalog.of(candidateNames);', probe)
        self.assertNotIn('for (String name : candidateNames)', probe)
        self.assertIn('return Catalog.of(candidateNames).hasStemStartingWith(base + " ");',
                      self.matcher)

    def test_regular_expressions_are_compiled_once(self):
        # Every per-entry derivation runs on thousands of names; String's
        # regex helpers recompile their pattern on each call.
        for helper in ('normalize(String value)', 'articleless(String normalized)',
                       'andless(String normalized)', 'collapse(String value)',
                       'sequelKey(String normalized)', 'isUnwantedVariant(',
                       'variantBits(String lower)', 'fullTitleForms(String title)'):
            code = body(self.matcher, helper, '\n    }\n')
            self.assertIsNone(re.search(r'\w\.(replaceAll|matches)\(', code), helper)

    def test_metadata_fields_are_read_without_regular_expressions(self):
        # A publish reads every stanza of every metafile; split("\\n")
        # compiled a pattern per call (2/3 of the pass's CPU on the Thor).
        field = body(self.importer, 'private static String field(String stanza, String key) {',
                     '\n    }\n')
        self.assertNotIn('split(', field)
        self.assertIn("int end = stanza.indexOf('\\n', start);", field)
        self.assertIn('private static final Pattern STANZA_BREAK = Pattern.compile(', self.importer)
        self.assertIn('for (String item : STANZA_BREAK.split(text))', self.importer)

    def test_prepared_and_plain_listings_are_pinned_equal(self):
        test = MATCHER_TEST.read_text()
        self.assertIn('aPreparedCatalogGivesTheSameAnswers();', test)


class StoppedPreviewTest(unittest.TestCase):
    def setUp(self):
        self.preview = PREVIEW.read_text()

    def test_a_stopped_window_pauses_every_decoder(self):
        self.assertIn('holdWhileStopped(true);',
                      body(self.preview, 'protected void onStop() {', '\n    }\n'))
        self.assertIn('holdWhileStopped(false);',
                      body(self.preview, 'protected void onStart() {', '\n    }\n'))
        hold = body(self.preview, 'private void holdWhileStopped(boolean stopped) {',
                    '\n    }\n')
        self.assertIn('if (stopped) slot.pause();', hold)
        self.assertIn('else slot.resume();', hold)
        self.assertIn('if (slots == null || playersPaused) return;', hold)
        self.assertNotIn('release()', hold)

    def test_nothing_restarts_a_held_decoder(self):
        resume = body(self.preview, 'private void resumePlayers() {',
                      'private void applyPlayerVolumes() {')
        self.assertIn('if (slots != null && !windowStopped)', resume)
        prepared = body(self.preview, 'player.setOnPreparedListener(', '});')
        self.assertIn('if (!playersPaused && !windowStopped) mediaPlayer.start();', prepared)
        completion = body(self.preview, 'player.setOnCompletionListener(', '});')
        self.assertIn('if (!playersPaused && !windowStopped) mediaPlayer.start();', completion)


if __name__ == '__main__':
    unittest.main()
