"""Render unmodified numerical RGB buffers side by side for diagnostic inspection."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from diagnose_rife_edge_profiles import evaluate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report,images=evaluate(args.case,'plateau',True)
    cubic_report,cubic=evaluate(args.case,'cubic',True)
    images['cubic']=cubic['candidate']
    order=('left','original','cubic','candidate','reference','right')
    h,w=images['left'].shape[:2]
    sheet=Image.new('RGB',(w*3,(h+24)*2))
    draw=ImageDraw.Draw(sheet)
    for i,name in enumerate(order):
        x=(i%3)*w;y=(i//3)*(h+24)
        draw.text((x+3,y+4),name,fill='white')
        sheet.paste(Image.fromarray(np.clip(np.rint(images[name][::-1]),0,255).astype('uint8')),(x,y+24))
    args.output.mkdir(exist_ok=False)
    sheet.save(args.output/'comparison.png')
    # Nearest-neighbor magnification preserves buffer values; no sharpening.
    for name in ('original','cubic','candidate','reference'):
        im=Image.fromarray(np.clip(np.rint(images[name][::-1]),0,255).astype('uint8'))
        im.resize((w*4,h*4),Image.Resampling.NEAREST).save(args.output/(name+'.png'))
    with (args.output/'evidence.json').open('x') as f:
        json.dump(dict(plateau=report,cubic=cubic_report,production_changed=False,
                       display_transform='All bottom-up capture buffers flipped vertically for display only'),f,indent=2)


if __name__=='__main__':main()
