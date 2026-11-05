#!/usr/bin/env python3
"""Small 65816 disassembler for finding a game's tile-loading code.

usage: snes_disasm.py ROM BANK:ADDR [--count N] [--m8] [--x8] [--lorom|--hirom]
"""
import argparse

OPS = {}
MODES = {
    'imp': 0, 'imm8': 1, 'immm': -1, 'immx': -2, 'dp': 1, 'dpx': 1, 'dpy': 1, 'idp': 1, 'idpx': 1, 'idpy': 1,
    'idpl': 1, 'idply': 1, 'sr': 1, 'isry': 1, 'abs': 2, 'absx': 2, 'absy': 2, 'iabs': 2, 'iabsx': 2, 'iabsl': 2,
    'long': 3, 'longx': 3, 'rel': 1, 'rell': 2, 'mv': 2,
}
TABLE = """
00 BRK imm8|01 ORA idpx|02 COP imm8|03 ORA sr|04 TSB dp|05 ORA dp|06 ASL dp|07 ORA idpl|08 PHP imp|09 ORA immm|0A ASL imp|0B PHD imp|0C TSB abs|0D ORA abs|0E ASL abs|0F ORA long
10 BPL rel|11 ORA idpy|12 ORA idp|13 ORA isry|14 TRB dp|15 ORA dpx|16 ASL dpx|17 ORA idply|18 CLC imp|19 ORA absy|1A INC imp|1B TCS imp|1C TRB abs|1D ORA absx|1E ASL absx|1F ORA longx
20 JSR abs|21 AND idpx|22 JSL long|23 AND sr|24 BIT dp|25 AND dp|26 ROL dp|27 AND idpl|28 PLP imp|29 AND immm|2A ROL imp|2B PLD imp|2C BIT abs|2D AND abs|2E ROL abs|2F AND long
30 BMI rel|31 AND idpy|32 AND idp|33 AND isry|34 BIT dpx|35 AND dpx|36 ROL dpx|37 AND idply|38 SEC imp|39 AND absy|3A DEC imp|3B TSC imp|3C BIT absx|3D AND absx|3E ROL absx|3F AND longx
40 RTI imp|41 EOR idpx|42 WDM imm8|43 EOR sr|44 MVP mv|45 EOR dp|46 LSR dp|47 EOR idpl|48 PHA imp|49 EOR immm|4A LSR imp|4B PHK imp|4C JMP abs|4D EOR abs|4E LSR abs|4F EOR long
50 BVC rel|51 EOR idpy|52 EOR idp|53 EOR isry|54 MVN mv|55 EOR dpx|56 LSR dpx|57 EOR idply|58 CLI imp|59 EOR absy|5A PHY imp|5B TCD imp|5C JML long|5D EOR absx|5E LSR absx|5F EOR longx
60 RTS imp|61 ADC idpx|62 PER rell|63 ADC sr|64 STZ dp|65 ADC dp|66 ROR dp|67 ADC idpl|68 PLA imp|69 ADC immm|6A ROR imp|6B RTL imp|6C JMP iabs|6D ADC abs|6E ROR abs|6F ADC long
70 BVS rel|71 ADC idpy|72 ADC idp|73 ADC isry|74 STZ dpx|75 ADC dpx|76 ROR dpx|77 ADC idply|78 SEI imp|79 ADC absy|7A PLY imp|7B TDC imp|7C JMP iabsx|7D ADC absx|7E ROR absx|7F ADC longx
80 BRA rel|81 STA idpx|82 BRL rell|83 STA sr|84 STY dp|85 STA dp|86 STX dp|87 STA idpl|88 DEY imp|89 BIT immm|8A TXA imp|8B PHB imp|8C STY abs|8D STA abs|8E STX abs|8F STA long
90 BCC rel|91 STA idpy|92 STA idp|93 STA isry|94 STY dpx|95 STA dpx|96 STX dpy|97 STA idply|98 TYA imp|99 STA absy|9A TXS imp|9B TXY imp|9C STZ abs|9D STA absx|9E STZ absx|9F STA longx
A0 LDY immx|A1 LDA idpx|A2 LDX immx|A3 LDA sr|A4 LDY dp|A5 LDA dp|A6 LDX dp|A7 LDA idpl|A8 TAY imp|A9 LDA immm|AA TAX imp|AB PLB imp|AC LDY abs|AD LDA abs|AE LDX abs|AF LDA long
B0 BCS rel|B1 LDA idpy|B2 LDA idp|B3 LDA isry|B4 LDY dpx|B5 LDA dpx|B6 LDX dpy|B7 LDA idply|B8 CLV imp|B9 LDA absy|BA TSX imp|BB TYX imp|BC LDY absx|BD LDA absx|BE LDX absy|BF LDA longx
C0 CPY immx|C1 CMP idpx|C2 REP imm8|C3 CMP sr|C4 CPY dp|C5 CMP dp|C6 DEC dp|C7 CMP idpl|C8 INY imp|C9 CMP immm|CA DEX imp|CB WAI imp|CC CPY abs|CD CMP abs|CE DEC abs|CF CMP long
D0 BNE rel|D1 CMP idpy|D2 CMP idp|D3 CMP isry|D4 PEI dp|D5 CMP dpx|D6 DEC dpx|D7 CMP idply|D8 CLD imp|D9 CMP absy|DA PHX imp|DB STP imp|DC JML iabsl|DD CMP absx|DE DEC absx|DF CMP longx
E0 CPX immx|E1 SBC idpx|E2 SEP imm8|E3 SBC sr|E4 CPX dp|E5 SBC dp|E6 INC dp|E7 SBC idpl|E8 INX imp|E9 SBC immm|EA NOP imp|EB XBA imp|EC CPX abs|ED SBC abs|EE INC abs|EF SBC long
F0 BEQ rel|F1 SBC idpy|F2 SBC idp|F3 SBC isry|F4 PEA abs|F5 SBC dpx|F6 INC dpx|F7 SBC idply|F8 SED imp|F9 SBC absy|FA PLX imp|FB XCE imp|FC JSR iabsx|FD SBC absx|FE INC absx|FF SBC longx
"""
for row in TABLE.strip().split('\n'):
    for item in row.split('|'):
        code, name, mode = item.split()
        OPS[int(code, 16)] = (name, mode)
FORMATS = dict(imm8='#${0:02X}', immm='#${0:X}', immx='#${0:X}', dp='${0:02X}', dpx='${0:02X},X', dpy='${0:02X},Y',
               idp='(${0:02X})', idpx='(${0:02X},X)', idpy='(${0:02X}),Y', idpl='[${0:02X}]', idply='[${0:02X}],Y',
               sr='${0:02X},S', isry='(${0:02X},S),Y', abs='${0:04X}', absx='${0:04X},X', absy='${0:04X},Y',
               iabs='(${0:04X})', iabsx='(${0:04X},X)', iabsl='[${0:04X}]', long='${0:06X}', longx='${0:06X},X')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom')
    parser.add_argument('start')
    parser.add_argument('--count', type=int, default=40)
    parser.add_argument('--m8', action='store_true')
    parser.add_argument('--x8', action='store_true')
    parser.add_argument('--hirom', action='store_true')
    args = parser.parse_args()
    rom = open(args.rom, 'rb').read()
    rom = rom[len(rom) & 0x3FF:] if len(rom) & 0x3FF == 512 else rom
    pc = int(args.start.replace(':', ''), 16)
    m8, x8 = args.m8, args.x8

    def offset(address):
        bank, low = address >> 16 & 0x7F, address & 0xFFFF
        if args.hirom:
            return ((bank & 0x3F) << 16 | low) % len(rom)
        return ((bank << 15) | (low & 0x7FFF)) % len(rom)

    for _ in range(args.count):
        where = offset(pc)
        code = rom[where]
        name, mode = OPS[code]
        size = MODES[mode]
        if mode == 'immm':
            size = 1 if m8 else 2
        elif mode == 'immx':
            size = 1 if x8 else 2
        data = rom[where + 1:where + 1 + size]
        value = int.from_bytes(data, 'little')
        text = ' '.join(f'{b:02X}' for b in rom[where:where + 1 + size])
        if mode == 'imp':
            operand = ''
        elif mode == 'rel':
            target = (pc & 0xFF0000) | ((pc + 2 + (value - 256 if value > 127 else value)) & 0xFFFF)
            operand = f'${target & 0xFFFF:04X}'
        elif mode == 'rell':
            target = (pc & 0xFF0000) | ((pc + 3 + (value - 65536 if value > 32767 else value)) & 0xFFFF)
            operand = f'${target & 0xFFFF:04X}'
        elif mode == 'mv':
            operand = f'${data[1]:02X},${data[0]:02X}'
        else:
            operand = FORMATS[mode].format(value)
        print(f'{pc >> 16:02X}:{pc & 0xFFFF:04X}  {text:<12} {name} {operand}')
        if name == 'REP':
            if value & 0x20: m8 = False
            if value & 0x10: x8 = False
        elif name == 'SEP':
            if value & 0x20: m8 = True
            if value & 0x10: x8 = True
        pc = (pc & 0xFF0000) | ((pc + 1 + size) & 0xFFFF)


if __name__ == '__main__':
    main()
