"""Verify diagnostic-only bytecode changes before any package installation."""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/qa/submission-overlay-2026-09-15'


def canonical(text):
    result=[];labels={}
    for line in text.splitlines():
        line=line.strip()
        if not line:continue
        if line.startswith('.method '):labels={}
        line=re.sub(r'^(?P<value>(?:const-wide/high16 v\d+, )?-?0x[0-9a-fA-F]+L?)\s+# .*$',r'\g<value>',line)
        # Preserve every string literal, including embedded shader source.
        if '"' not in line:
            def label(match):
                name=match[0]
                if name not in labels:labels[name]=':label'+str(len(labels))
                return labels[name]
            line=re.sub(r':[A-Za-z0-9_]+',label,line)
        result.append(line)
    return result


def main():
    def tree(path):return {p.relative_to(path):p.read_text() for p in path.rglob('*.smali')}
    old=tree(ROOT/'docs/qa/smoothing-apk-2026-09-15/check/smali')
    entered=tree(OUT/'input/smali');built=tree(OUT/'check/smali');helpers=tree(OUT/'helper-check/smali')
    assert len(old)==2183 and len(helpers)==4
    assert not(old.keys()&helpers.keys())
    assert entered.keys()==built.keys()==old.keys()|helpers.keys()
    target=Path('com/thorium/preview/game/DisplayFrameGenerator.smali')
    hooks=[
        'invoke-static {v0, v1}, Lcom/thorium/preview/game/SubmissionTimingOverlay;->gap(Ljava/lang/Object;Ljava/lang/Object;)V',
        'invoke-static {v1, v12, v13, v4}, Lcom/thorium/preview/game/SubmissionTimingOverlay;->before(Ljava/lang/Object;JZ)V',
        'invoke-static {v1}, Lcom/thorium/preview/game/SubmissionTimingOverlay;->after(Ljava/lang/Object;)V',
        'invoke-static/range {v26 .. v37}, Lcom/thorium/preview/game/SubmissionTimingOverlay;->committed(JJJJJJ)V',
        'if-eqz v0, :submission_history_not_bound',':submission_history_not_bound']
    lines=entered[target].splitlines()
    for hook in hooks:assert sum(line.strip()==hook for line in lines)==1,hook
    reverted='\n'.join(line for line in lines if line.strip() not in hooks)
    assert canonical(reverted)==canonical(old[target]),'Unrelated renderer modification'
    for name in old:
        if name!=target:assert canonical(old[name])==canonical(entered[name]),str(name)
    for name in helpers:assert canonical(helpers[name])==canonical(entered[name]),str(name)
    for name in entered:assert canonical(entered[name])==canonical(built[name]),str(name)
    result={'existing_classes':len(old),'added_helper_classes':len(helpers),
        'changed_existing_class':str(target),'audited_hooks':4,'register_counts_changed':False,
        'assembled_instructions_match':True,'installed':False}
    (OUT/'bytecode-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
