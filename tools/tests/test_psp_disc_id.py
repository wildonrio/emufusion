"""PSP DISC_ID is read from an ISO9660 image and from an EBOOT.PBP.

PPSSPP's cheat file is <memstick>/PSP/Cheats/<DISC_ID>.ini; EmuFusion writes it
before boot because the core's live retro_cheat_set corrupts it.
"""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT

SOURCE = ROOT / 'unified-android/src/com/thorium/preview/cheats/delivery/PspDiscId.java'
SECTOR = 2048


def param_sfo(disc_id):
    keys = b'DISC_ID\0TITLE\0'
    key_table = keys + b'\0' * (-len(keys) % 4)
    values = [disc_id.encode() + b'\0', b'God of War\0']
    key_start = 20 + 2 * 16
    data_start = key_start + len(key_table)
    entries, data = b'', b''
    for offset, value in zip((0, keys.index(b'TITLE')), values):
        size = len(value) + (-len(value) % 4)
        entries += struct.pack('<HHIII', offset, 0x0204, len(value), size, len(data))
        data += value + b'\0' * (size - len(value))
    return struct.pack('<IIIII', 0x46535000, 0x101, key_start, data_start, 2) + entries + key_table + data


def record(name, lba, size, directory):
    ident = name.encode()
    length = 33 + len(ident) + (len(ident) + 1) % 2
    rec = bytearray(length)
    rec[0] = length
    rec[2:6] = struct.pack('<I', lba)
    rec[6:10] = struct.pack('>I', lba)
    rec[10:14] = struct.pack('<I', size)
    rec[14:18] = struct.pack('>I', size)
    rec[25] = 0x02 if directory else 0x00
    rec[32] = len(ident)
    rec[33:33 + len(ident)] = ident
    return bytes(rec)


def iso(disc_id):
    image = bytearray(SECTOR * 24)
    pvd = bytearray(SECTOR)
    pvd[0], pvd[1:6] = 1, b'CD001'
    pvd[156:156 + 34] = record('\0', 18, SECTOR, True)[:34]
    image[16 * SECTOR:17 * SECTOR] = pvd
    root = record('\0', 18, SECTOR, True) + record('\1', 18, SECTOR, True) + \
        record('PSP_GAME', 19, SECTOR, True)
    image[18 * SECTOR:18 * SECTOR + len(root)] = root
    sfo = param_sfo(disc_id)
    game = record('\0', 19, SECTOR, True) + record('\1', 18, SECTOR, True) + \
        record('ICON0.PNG;1', 21, 4, False) + record('PARAM.SFO;1', 20, len(sfo), False)
    image[19 * SECTOR:19 * SECTOR + len(game)] = game
    image[20 * SECTOR:20 * SECTOR + len(sfo)] = sfo
    return bytes(image)


def pbp(disc_id):
    sfo = param_sfo(disc_id)
    header = b'\0PBP' + struct.pack('<I', 0x10000) + struct.pack('<8I', 40, 40 + len(sfo), *([40 + len(sfo)] * 6))
    return header + sfo + b'icon'


HARNESS = r'''
package com.thorium.preview.cheats.delivery;
public class PspDiscIdProbe {
    public static void main(String[] args) {
        for (String path : args) System.out.println(PspDiscId.of(new java.io.File(path)));
    }
}
'''


class PspDiscIdTest(unittest.TestCase):
    def test_iso_and_pbp(self):
        with tempfile.TemporaryDirectory(prefix='psp-disc-id-') as work:
            work = Path(work)
            (work / 'Game.iso').write_bytes(iso('ULUS-10391'))
            (work / 'EBOOT.PBP').write_bytes(pbp('NPUH10045'))
            (work / 'notes.iso').write_bytes(b'not an iso' * 400)
            (work / 'Game.cso').write_bytes(b'CISO')
            src = work / 'src/com/thorium/preview/cheats/delivery'
            src.mkdir(parents=True)
            (src / 'PspDiscIdProbe.java').write_text(HARNESS)
            out = work / 'classes'
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), str(SOURCE), str(src / 'PspDiscIdProbe.java')],
                           check=True, capture_output=True, text=True)
            run = subprocess.run([str(JAVA / 'java'), '-cp', str(out),
                                  'com.thorium.preview.cheats.delivery.PspDiscIdProbe',
                                  str(work / 'Game.iso'), str(work / 'EBOOT.PBP'),
                                  str(work / 'notes.iso'), str(work / 'Game.cso')],
                                 check=True, capture_output=True, text=True)
            self.assertEqual(run.stdout.split('\n')[:4], ['ULUS10391', 'NPUH10045', '', ''])


if __name__ == '__main__':
    unittest.main()
