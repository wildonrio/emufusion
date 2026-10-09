"""Folder-format games get their real title, not the launched file's name.

October 9 clean-phone run: the PS3 pause menu was titled "EBOOT" because a PS3
disc folder always launches PS3_GAME/USRDIR/EBOOT.BIN.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/GameTitles.java'
HOST = (ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java').read_text()


def jdk_tool(name):
    home = os.environ.get('JAVA_HOME')
    candidates = [Path(home) / 'bin' / name] if home else []
    candidates.append(Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin') / name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def param_sfo(title):
    """Minimal PS3 PARAM.SFO with TITLE and CATEGORY entries."""
    keys = b'CATEGORY\0TITLE\0'
    values = [b'DG\0\0', title.encode() + b'\0']
    key_start = 20 + 2 * 16
    key_table = keys + b'\0' * (-len(keys) % 4)
    data_start = key_start + len(key_table)
    entries, data, offsets = b'', b'', (0, keys.index(b'TITLE'))
    for key_offset, value in zip(offsets, values):
        entries += struct.pack('<HHIII', key_offset, 0x0204, len(value), len(value), len(data))
        data += value
    return struct.pack('<IIIII', 0x46535000, 0x101, key_start, data_start, 2) + entries + key_table + data


HARNESS = r'''
package com.thorium.preview.game;
public class GameTitlesHarness {
    public static void main(String[] args) {
        for (String path : args) System.out.println(GameTitles.forFile(new java.io.File(path)));
    }
}
'''


class GameTitlesTest(unittest.TestCase):
    def test_launch_titles_use_the_helper(self):
        self.assertIn('return GameTitles.forFile(file);', HOST)

    def test_folder_games_and_plain_files(self):
        javac, java = jdk_tool('javac'), jdk_tool('java')
        if not javac or not java:
            self.skipTest('JDK required')
        with tempfile.TemporaryDirectory(prefix='game-titles-') as work:
            work = Path(work)
            ps3 = work / 'ps3' / 'Ico & Shadow of the Colossus Collection, The (World) (En,Fr,Es)'
            (ps3 / 'PS3_GAME/USRDIR').mkdir(parents=True)
            (ps3 / 'PS3_GAME/USRDIR/EBOOT.BIN').write_bytes(b'')
            (ps3 / 'PS3_GAME/PARAM.SFO').write_bytes(param_sfo('ICO & Shadow of the\nColossus Collection'))
            bare = work / 'ps3' / 'Shadow of the Colossus (USA)'
            (bare / 'PS3_GAME/USRDIR').mkdir(parents=True)
            (bare / 'PS3_GAME/USRDIR/EBOOT.BIN').write_bytes(b'')
            wiiu = work / 'wiiu' / 'Super Mario 3D World [ARDE01]'
            (wiiu / 'code').mkdir(parents=True)
            (wiiu / 'code/RedCarpet.rpx').write_bytes(b'')
            plain = work / 'psp' / 'Castlevania The Dracula X Chronicles.iso'
            plain.parent.mkdir(parents=True)
            plain.write_bytes(b'')
            src = work / 'src'
            (src / 'com/thorium/preview/game').mkdir(parents=True)
            harness = src / 'com/thorium/preview/game/GameTitlesHarness.java'
            harness.write_text(HARNESS)
            out = work / 'classes'
            subprocess.run([javac, '-d', str(out), str(SOURCE), str(harness)], check=True,
                           capture_output=True, timeout=60)
            run = subprocess.run([java, '-cp', str(out), 'com.thorium.preview.game.GameTitlesHarness',
                                  str(ps3 / 'PS3_GAME/USRDIR/EBOOT.BIN'), str(bare / 'PS3_GAME/USRDIR/EBOOT.BIN'),
                                  str(wiiu / 'code/RedCarpet.rpx'), str(plain)],
                                 check=True, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.stdout.splitlines(), [
                'ICO & Shadow of the Colossus Collection',
                'Shadow of the Colossus',
                'Super Mario 3D World',
                'Castlevania The Dracula X Chronicles',
            ])


if __name__ == '__main__':
    unittest.main()
