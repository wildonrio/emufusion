#!/usr/bin/env python3
"""Find RAM bytes that tell gameplay from menus: same in every play dump, different in every other.

usage: ram_scene.py --play a.ram b.ram --menu c.ram d.ram [--base 0x7E0000]
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--play', nargs='+', required=True)
    parser.add_argument('--menu', nargs='+', required=True)
    parser.add_argument('--base', type=lambda text: int(text, 0), default=0x7E0000)
    parser.add_argument('--limit', type=int, default=40)
    parser.add_argument('--swap', action='store_true', help='68000 RAM dumps: print the address the game uses')
    args = parser.parse_args()
    play = [open(path, 'rb').read() for path in args.play]
    menu = [open(path, 'rb').read() for path in args.menu]
    size = min(map(len, play + menu))
    found = []
    for address in range(size):
        values = {dump[address] for dump in play}
        others = {dump[address] for dump in menu}
        if len(values) == 1 and not values & others:
            found.append((address, values.pop(), sorted(others)))
    print(f'{len(found)} candidates of {size} bytes')
    for address, value, others in found[:args.limit]:
        print(f'{args.base + (address ^ 1 if args.swap else address):06X}={value:02X}  menus {" ".join(f"{v:02X}" for v in others)}')


if __name__ == '__main__':
    main()
