"""Execute production pyramid orchestration, recording actual requested draws."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, SOURCE, method


class PyramidResolutionTest(unittest.TestCase):
    def test_no_destructive_downsample_then_upscale(self):
        body = method(SOURCE.read_text(), 'private void buildDensePyramid(')
        fixture = '''
import java.util.*;
public class Pyramid {
    int historyWidth,historyHeight;
    int[][] denseBoxTextures={{11,12},{21,22}},densePyramidTextures={{13,14},{23,24}};
    int[] denseBoxWidths=new int[2],denseBoxHeights=new int[2];
    int[] denseLevelWidths=new int[3],denseLevelHeights=new int[3];
    List<Integer> targets=new ArrayList<>();
    void drawDensePyramid(int src,int sw,int sh,int dst,int dw,int dh,float tap){
        if(dw>sw || dh>sh)throw new AssertionError("Lost detail then upscaled");
        targets.add(dst);
    }
''' + body + '''
    static void check(int w,int h,int stages){
        Pyramid p=new Pyramid();p.historyWidth=w;p.historyHeight=h;
        float scale=Math.min(1f,Math.min(192f/w,144f/h));
        p.denseLevelWidths[0]=Math.max(4,Math.round(w*scale));
        p.denseLevelHeights[0]=Math.max(4,Math.round(h*scale));
        for(int i=1;i<3;i++){
            p.denseLevelWidths[i]=Math.max(1,p.denseLevelWidths[i-1]/2);
            p.denseLevelHeights[i]=Math.max(1,p.denseLevelHeights[i-1]/2);
        }
        p.denseBoxWidths[0]=Math.max(1,w/4);p.denseBoxHeights[0]=Math.max(1,h/4);
        p.denseBoxWidths[1]=Math.max(1,p.denseBoxWidths[0]/4);
        p.denseBoxHeights[1]=Math.max(1,p.denseBoxHeights[0]/4);
        for(int endpoint=0;endpoint<2;endpoint++){
            p.targets.clear();p.buildDensePyramid(99,endpoint);
            if(p.targets.size()!=stages+2)throw new AssertionError(w+"x"+h+" "+p.targets);
            if(p.targets.get(p.targets.size()-1)!=p.densePyramidTextures[endpoint][1])
                throw new AssertionError("Wrong endpoint");
        }
    }
    public static void main(String[] args){
        check(256,192,0);check(240,160,0);check(160,144,0);
        check(320,240,0);check(640,480,1);check(1920,1080,2);
        check(3840,2160,2);check(641,479,1);
    }
}'''
        with tempfile.TemporaryDirectory(prefix='pyramid-resolution-') as d:
            unit=Path(d)/'Pyramid.java';unit.write_text(fixture)
            subprocess.run([str(JAVA/'javac'),'-d',d,str(unit)],check=True)
            subprocess.run([str(JAVA/'java'),'-ea','-cp',d,'Pyramid'],check=True)
