#!/usr/bin/env python3
"""z80_disasm.py ROM START END: a small Z80 disassembler, enough to read a game's map routines. Addresses are file offsets."""
import sys

R = ['b', 'c', 'd', 'e', 'h', 'l', '(hl)', 'a']
RP = ['bc', 'de', 'hl', 'sp']
RP2 = ['bc', 'de', 'hl', 'af']
CC = ['nz', 'z', 'nc', 'c', 'po', 'pe', 'p', 'm']
ALU = ['add a,', 'adc a,', 'sub ', 'sbc a,', 'and ', 'xor ', 'or ', 'cp ']
ROT = ['rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'sll', 'srl']


def dis(rom, pc):
    start = pc
    op = rom[pc]
    pc += 1
    prefix = None
    if op in (0xDD, 0xFD):
        prefix = 'ix' if op == 0xDD else 'iy'
        op = rom[pc]
        pc += 1

    def s8():
        nonlocal pc
        v = rom[pc]
        pc += 1
        return v - 256 if v >= 128 else v

    def u8():
        nonlocal pc
        v = rom[pc]
        pc += 1
        return v

    def u16():
        nonlocal pc
        v = rom[pc] | rom[pc + 1] << 8
        pc += 2
        return v

    def reg(i):
        name = R[i]
        if prefix:
            if i == 6:
                d = s8()
                return f'({prefix}{d:+d})'
            if i == 4:
                return prefix + 'h'
            if i == 5:
                return prefix + 'l'
        return name

    def pair(i, table=RP):
        name = table[i]
        return prefix if prefix and name == 'hl' else name

    if op == 0xCB:
        d = s8() if prefix else None
        sub = u8()
        x, y, z = sub >> 6, (sub >> 3) & 7, sub & 7
        target = f'({prefix}{d:+d})' if prefix else R[z]
        text = f'{ROT[y]} {target}' if x == 0 else f"{['', 'bit', 'res', 'set'][x]} {y},{target}"
    elif op == 0xED:
        sub = u8()
        x, y, z = sub >> 6, (sub >> 3) & 7, sub & 7
        p, q = y >> 1, y & 1
        names = {0xA0: 'ldi', 0xB0: 'ldir', 0xA8: 'ldd', 0xB8: 'lddr', 0xA3: 'outi', 0xB3: 'otir', 0xAB: 'outd', 0xBB: 'otdr', 0xA1: 'cpi', 0xB1: 'cpir', 0xA2: 'ini', 0xB2: 'inir'}
        if sub in names:
            text = names[sub]
        elif x == 1 and z == 0:
            text = f'in {R[y]},(c)'
        elif x == 1 and z == 1:
            text = f'out (c),{R[y]}'
        elif x == 1 and z == 2:
            text = f"{'adc' if q else 'sbc'} hl,{RP[p]}"
        elif x == 1 and z == 3:
            address = u16()
            text = f'ld {RP[p]},(${address:04X})' if q else f'ld (${address:04X}),{RP[p]}'
        elif x == 1 and z == 4:
            text = 'neg'
        elif x == 1 and z == 5:
            text = 'reti' if q else 'retn'
        elif sub == 0x5F:
            text = 'ld a,r'
        elif sub == 0x57:
            text = 'ld a,i'
        else:
            text = f'ed {sub:02x}'
    else:
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 0:
            if z == 0:
                if y == 0:
                    text = 'nop'
                elif y == 1:
                    text = "ex af,af'"
                elif y == 2:
                    d = s8()
                    text = f'djnz ${(pc + d) & 0xFFFF:04X}'
                elif y == 3:
                    d = s8()
                    text = f'jr ${(pc + d) & 0xFFFF:04X}'
                else:
                    d = s8()
                    text = f'jr {CC[y - 4]},${(pc + d) & 0xFFFF:04X}'
            elif z == 1:
                if q == 0:
                    text = f'ld {pair(p)},${u16():04X}'
                else:
                    text = f'add {pair(2)},{pair(p)}'
            elif z == 2:
                forms = ['ld (bc),a', 'ld a,(bc)', 'ld (de),a', 'ld a,(de)']
                if y < 4:
                    text = forms[y]
                elif y == 4:
                    text = f'ld (${u16():04X}),{pair(2)}'
                elif y == 5:
                    text = f'ld {pair(2)},(${u16():04X})'
                elif y == 6:
                    text = f'ld (${u16():04X}),a'
                else:
                    text = f'ld a,(${u16():04X})'
            elif z == 3:
                text = f"{'dec' if q else 'inc'} {pair(p)}"
            elif z == 4:
                text = f'inc {reg(y)}'
            elif z == 5:
                text = f'dec {reg(y)}'
            elif z == 6:
                target = reg(y)
                text = f'ld {target},${u8():02X}'
            else:
                text = ['rlca', 'rrca', 'rla', 'rra', 'daa', 'cpl', 'scf', 'ccf'][y]
        elif x == 1:
            if op == 0x76:
                text = 'halt'
            else:
                if prefix and (y == 6 or z == 6):
                    left = reg(y) if y == 6 else R[y]
                    right = reg(z) if z == 6 else R[z]
                else:
                    left, right = reg(y), reg(z)
                text = f'ld {left},{right}'
        elif x == 2:
            text = f'{ALU[y]}{reg(z)}'
        else:
            if z == 0:
                text = f'ret {CC[y]}'
            elif z == 1:
                if q == 0:
                    text = f'pop {pair(p, RP2)}'
                else:
                    text = ['ret', 'exx', f'jp ({pair(2)})', f'ld sp,{pair(2)}'][p]
            elif z == 2:
                text = f'jp {CC[y]},${u16():04X}'
            elif z == 3:
                if y == 0:
                    text = f'jp ${u16():04X}'
                elif y == 2:
                    text = f'out (${u8():02X}),a'
                elif y == 3:
                    text = f'in a,(${u8():02X})'
                elif y == 4:
                    text = f'ex (sp),{pair(2)}'
                elif y == 5:
                    text = 'ex de,hl'
                elif y == 6:
                    text = 'di'
                else:
                    text = 'ei'
            elif z == 4:
                text = f'call {CC[y]},${u16():04X}'
            elif z == 5:
                if q == 0:
                    text = f'push {pair(p, RP2)}'
                else:
                    text = f'call ${u16():04X}'
            elif z == 6:
                text = f'{ALU[y]}${u8():02X}'
            else:
                text = f'rst ${y * 8:02X}'
    return pc, text


def main():
    rom = open(sys.argv[1], 'rb').read()
    pc, end = int(sys.argv[2], 16), int(sys.argv[3], 16)
    while pc < end:
        next_pc, text = dis(rom, pc)
        print(f'{pc:05X}  {rom[pc:next_pc].hex():<10} {text}')
        pc = next_pc


if __name__ == '__main__':
    main()
