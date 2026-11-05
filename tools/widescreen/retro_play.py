#!/usr/bin/env python3
"""Play a game through a libretro core on the Mac from a button script, saving screenshots.

The Widescreen Hack needs every recipe tried in real gameplay, and that takes far
more runs than the Thor should do. This harness loads the same core sources built
for the host and runs faster than real time, so a game can be played to its first
level, widened, and looked at. A recipe still has to pass on the Thor.

Script, one step per whitespace-separated token (read from --play or a file):
  wait:N          run N frames with no buttons
  tap:A,B         press buttons for 4 frames, then release for 12
  hold:RIGHT,Y:N  hold buttons for N frames
  shot:NAME       save the current frame as NAME.png in --out
  opt:KEY=VALUE   change a core option live (the host reports the variable update)
  save:SLOT       snapshot the emulator in memory; load:SLOT restores it
  savefile:PATH   write a save state to disk; loadfile:PATH restores one
  ram:NAME        dump the console's main RAM to NAME.ram in --out
Buttons: B Y SELECT START UP DOWN LEFT RIGHT A X L R L2 R2 L3 R3.
"""
import argparse
import ctypes as C
import json
import os
import struct
import sys
import zlib

RETRO_API = 1
ENV = dict(
    GET_OVERSCAN=2, GET_CAN_DUPE=3, SET_MESSAGE=6, SET_PERFORMANCE_LEVEL=8,
    GET_SYSTEM_DIRECTORY=9, SET_PIXEL_FORMAT=10, SET_INPUT_DESCRIPTORS=11,
    GET_VARIABLE=15, SET_VARIABLES=16, GET_VARIABLE_UPDATE=17, SET_SUPPORT_NO_GAME=18,
    GET_LOG_INTERFACE=27, GET_SAVE_DIRECTORY=31, SET_SYSTEM_AV_INFO=32,
    SET_CONTROLLER_INFO=35, SET_GEOMETRY=37, GET_CORE_OPTIONS_VERSION=52,
    SET_CORE_OPTIONS=53, SET_CORE_OPTIONS_INTL=54, SET_CORE_OPTIONS_DISPLAY=55,
)
ENV_EXPERIMENTAL = 0x10000
BUTTONS = dict(B=0, Y=1, SELECT=2, START=3, UP=4, DOWN=5, LEFT=6, RIGHT=7, A=8, X=9,
               L=10, R=11, L2=12, R2=13, L3=14, R3=15)


class SystemInfo(C.Structure):
    _fields_ = [('library_name', C.c_char_p), ('library_version', C.c_char_p),
                ('valid_extensions', C.c_char_p), ('need_fullpath', C.c_bool),
                ('block_extract', C.c_bool)]


class GameInfo(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t),
                ('meta', C.c_char_p)]


class Geometry(C.Structure):
    _fields_ = [('base_width', C.c_uint), ('base_height', C.c_uint), ('max_width', C.c_uint),
                ('max_height', C.c_uint), ('aspect_ratio', C.c_float)]


class Timing(C.Structure):
    _fields_ = [('fps', C.c_double), ('sample_rate', C.c_double)]


class AvInfo(C.Structure):
    _fields_ = [('geometry', Geometry), ('timing', Timing)]


class Variable(C.Structure):
    _fields_ = [('key', C.c_char_p), ('value', C.c_char_p)]


class OptionValue(C.Structure):
    _fields_ = [('value', C.c_char_p), ('label', C.c_char_p)]


class OptionDefinition(C.Structure):
    _fields_ = [('key', C.c_char_p), ('desc', C.c_char_p), ('info', C.c_char_p),
                ('values', OptionValue * 128), ('default_value', C.c_char_p)]


ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIO_BATCH_CB = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
POLL_CB = C.CFUNCTYPE(None)
STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)
LOG_CB = C.CFUNCTYPE(None, C.c_int, C.c_char_p)


def write_png(path, width, height, rgb):
    rows = bytearray()
    stride = width * 3
    for y in range(height):
        rows.append(0)
        rows += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    with open(path, 'wb') as out:
        out.write(b'\x89PNG\r\n\x1a\n')
        out.write(chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)))
        out.write(chunk(b'IDAT', zlib.compress(bytes(rows), 6)))
        out.write(chunk(b'IEND', b''))


class Player:
    def __init__(self, core, rom, options, workdir):
        self.lib = C.CDLL(core)
        self.options = dict(options)
        self.defaults = {}
        self.updated = False
        self.pressed = set()
        self.frame = None
        self.pixel_format = 0
        self.geometry = None
        self.keep = []
        self.frames = 0
        self.strings = {}
        self.system_dir = C.create_string_buffer(os.fsencode(workdir))
        os.makedirs(workdir, exist_ok=True)
        self.env_cb = ENV_CB(self.environment)
        self.video_cb = VIDEO_CB(self.video)
        self.audio_cb = AUDIO_CB(lambda left, right: None)
        self.batch_cb = AUDIO_BATCH_CB(lambda data, frames: frames)
        self.poll_cb = POLL_CB(lambda: None)
        self.state_cb = STATE_CB(self.input_state)
        self.log_cb = LOG_CB(lambda level, text: None)
        lib = self.lib
        lib.retro_set_environment(self.env_cb)
        lib.retro_init()
        lib.retro_set_video_refresh(self.video_cb)
        lib.retro_set_audio_sample(self.audio_cb)
        lib.retro_set_audio_sample_batch(self.batch_cb)
        lib.retro_set_input_poll(self.poll_cb)
        lib.retro_set_input_state(self.state_cb)
        info = SystemInfo()
        lib.retro_get_system_info(C.byref(info))
        self.rom_bytes = open(rom, 'rb').read()
        self.rom_buffer = C.create_string_buffer(self.rom_bytes, len(self.rom_bytes))
        game = GameInfo(os.fsencode(rom), C.cast(self.rom_buffer, C.c_void_p),
                        len(self.rom_bytes), None)
        lib.retro_load_game.restype = C.c_bool
        lib.retro_load_game.argtypes = [C.POINTER(GameInfo)]
        if not lib.retro_load_game(C.byref(game)):
            raise SystemExit('core refused ' + rom)
        lib.retro_serialize_size.restype = C.c_size_t
        lib.retro_serialize.restype = C.c_bool
        lib.retro_serialize.argtypes = [C.c_void_p, C.c_size_t]
        lib.retro_unserialize.restype = C.c_bool
        lib.retro_unserialize.argtypes = [C.c_void_p, C.c_size_t]
        lib.retro_set_controller_port_device(0, 1)
        av = AvInfo()
        lib.retro_get_system_av_info(C.byref(av))
        self.geometry = (av.geometry.base_width, av.geometry.base_height, av.geometry.aspect_ratio)
        self.slots = {}

    def cstring(self, text):
        value = self.strings.get(text)
        if value is None:
            value = C.create_string_buffer(os.fsencode(text))
            self.strings[text] = value
        return value

    def environment(self, command, data):
        cmd = command & ~ENV_EXPERIMENTAL
        if cmd == ENV['GET_CAN_DUPE']:
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        if cmd == ENV['GET_OVERSCAN']:
            C.cast(data, C.POINTER(C.c_bool))[0] = False
            return True
        if cmd == ENV['SET_PIXEL_FORMAT']:
            self.pixel_format = C.cast(data, C.POINTER(C.c_int))[0]
            return True
        if cmd in (ENV['GET_SYSTEM_DIRECTORY'], ENV['GET_SAVE_DIRECTORY']):
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(self.system_dir, C.c_void_p)
            return True
        if cmd == ENV['GET_VARIABLE']:
            var = C.cast(data, C.POINTER(Variable))[0]
            key = var.key.decode()
            value = self.options.get(key, self.defaults.get(key))
            if value is None:
                C.cast(data, C.POINTER(Variable))[0].value = None
                return False
            C.cast(data, C.POINTER(Variable))[0].value = C.cast(self.cstring(value), C.c_char_p)
            return True
        if cmd == ENV['GET_VARIABLE_UPDATE']:
            C.cast(data, C.POINTER(C.c_bool))[0] = self.updated
            self.updated = False
            return True
        if cmd == ENV['SET_VARIABLES']:
            array = C.cast(data, C.POINTER(Variable))
            index = 0
            while array[index].key:
                text = array[index].value.decode()
                choices = text.split(';', 1)[1].strip().split('|')
                self.defaults[array[index].key.decode()] = choices[0]
                index += 1
            return True
        if cmd == ENV['GET_CORE_OPTIONS_VERSION']:
            C.cast(data, C.POINTER(C.c_uint))[0] = 0
            return True
        if cmd == ENV['SET_SYSTEM_AV_INFO']:
            av = C.cast(data, C.POINTER(AvInfo))[0]
            self.geometry = (av.geometry.base_width, av.geometry.base_height, av.geometry.aspect_ratio)
            return True
        if cmd == ENV['SET_GEOMETRY']:
            geo = C.cast(data, C.POINTER(Geometry))[0]
            self.geometry = (geo.base_width, geo.base_height, geo.aspect_ratio)
            return True
        return False

    def video(self, data, width, height, pitch):
        if data:
            self.frame = (C.string_at(data, pitch * height), width, height, pitch)

    def input_state(self, port, device, index, button):
        if port != 0 or device != 1:
            return 0
        if button == 256:
            mask = 0
            for name in self.pressed:
                mask |= 1 << BUTTONS[name]
            return mask
        return 1 if any(BUTTONS[name] == button for name in self.pressed) else 0

    def run(self, count):
        for _ in range(count):
            self.lib.retro_run()
            self.frames += 1

    def shot(self, path):
        if self.frame is None:
            print('no frame for', path)
            return
        data, width, height, pitch = self.frame
        rgb = bytearray(width * height * 3)
        out = 0
        fmt = self.pixel_format
        for y in range(height):
            start = y * pitch
            if fmt == 1:  # XRGB8888
                row = data[start:start + width * 4]
                rgb[out:out + width * 3:3] = row[2::4]
                rgb[out + 1:out + width * 3:3] = row[1::4]
                rgb[out + 2:out + width * 3:3] = row[0::4]
                out += width * 3
            else:
                bits = 5 if fmt == 0 else 6
                for x in range(width):
                    value = data[start + x * 2] | data[start + x * 2 + 1] << 8
                    red = (value >> (10 if fmt == 0 else 11)) & 31
                    green = (value >> 5) & (31 if bits == 5 else 63)
                    blue = value & 31
                    rgb[out] = red << 3 | red >> 2
                    rgb[out + 1] = (green << 3 | green >> 2) if bits == 5 else (green << 2 | green >> 4)
                    rgb[out + 2] = blue << 3 | blue >> 2
                    out += 3
        write_png(path, width, height, bytes(rgb))

    def save(self, slot):
        size = self.lib.retro_serialize_size()
        buffer = C.create_string_buffer(size)
        if not self.lib.retro_serialize(buffer, size):
            raise SystemExit('serialize failed')
        self.slots[slot] = buffer

    def load(self, slot):
        buffer = self.slots[slot]
        if not self.lib.retro_unserialize(buffer, len(buffer)):
            raise SystemExit('unserialize failed')

    def play(self, tokens, out):
        for token in tokens:
            kind, _, rest = token.partition(':')
            if kind == 'wait':
                self.run(int(rest))
            elif kind == 'tap':
                self.pressed = set(rest.split(','))
                self.run(4)
                self.pressed = set()
                self.run(12)
            elif kind == 'hold':
                names, _, count = rest.rpartition(':')
                self.pressed = set(names.split(','))
                self.run(int(count))
                self.pressed = set()
            elif kind == 'shot':
                self.shot(os.path.join(out, rest + '.png'))
                print(f'{rest}: frame {self.frames} geometry {self.geometry}')
            elif kind == 'opt':
                key, _, value = rest.partition('=')
                self.options[key] = value
                self.updated = True
            elif kind == 'save':
                self.save(rest)
            elif kind == 'load':
                self.load(rest)
            elif kind == 'ram':
                self.lib.retro_get_memory_data.restype = C.c_void_p
                self.lib.retro_get_memory_size.restype = C.c_size_t
                size = self.lib.retro_get_memory_size(2)
                with open(os.path.join(out, rest + '.ram'), 'wb') as dump:
                    dump.write(C.string_at(self.lib.retro_get_memory_data(2), size))
            elif kind == 'savefile':
                self.save('_file')
                os.makedirs(os.path.dirname(rest) or '.', exist_ok=True)
                with open(rest, 'wb') as state:
                    state.write(self.slots['_file'].raw)
            elif kind == 'loadfile':
                self.slots['_file'] = C.create_string_buffer(open(rest, 'rb').read())
                self.load('_file')
            else:
                raise SystemExit('unknown step ' + token)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('core')
    parser.add_argument('rom')
    parser.add_argument('--out', required=True)
    parser.add_argument('--play', default='', help='script text, or @file')
    parser.add_argument('--opt', action='append', default=[], help='KEY=VALUE at load')
    parser.add_argument('--recipe', help='SYSTEM/TITLE from the shipped table, widened to --width')
    parser.add_argument('--width', type=int, default=348, help='picture width with --recipe')
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    options = {}
    if args.recipe:
        system, title = args.recipe.split('/', 1)
        table = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             '../../engines/widescreen/widescreen-recipes.json')
        entry = json.load(open(table))['systems'][system]
        options.update(entry['options'])
        options.update(entry['games'][title].get('options', {}))
        options[entry['widthOption']] = str(args.width)
    options.update(dict(pair.split('=', 1) for pair in args.opt))
    player = Player(os.path.abspath(args.core), args.rom, options, os.path.join(args.out, '.system'))
    text = args.play
    if text.startswith('@'):
        text = open(text[1:]).read()
    player.play(text.split(), args.out)


if __name__ == '__main__':
    sys.exit(main())
