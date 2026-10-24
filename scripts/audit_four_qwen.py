"""Reproduce explicitly reviewed embedded Qwen snippets; never runs installers.

The original document is preserved. Only the four named Python blocks are
selected after AST import/syntax inspection. Run locally, offline.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dis_oracle.contracts import validate_cards, validate_event, ContractError
from dis_oracle.adapters.audited_inputs import maya_model, name_arithmetic

DOCUMENT=ROOT/'research/qwen/four_cores_UNVERIFIED/originals/ADAPTERS_SPECIFICATION.md'


def build():
    canonical=DOCUMENT.read_bytes().replace(b'\r\n', b'\n')
    source_sha256=hashlib.sha256(canonical).hexdigest()
    if source_sha256 != '17a78dbf751fcdbccaf2086a009193b5c7d5a004a4f97b4d1717f62bf436951b':
        raise ValueError("embedded code changed: review the new document before execution")
    original=canonical.decode('utf-8')
    blocks=re.findall(r'```python\n(.*?)```',original,re.S)
    modules={}
    for block in blocks:
        first=block.splitlines()[0]
        if first not in ('# maya_calendar.py','# shakuna.py','# slavic.py','# name_grids.py'):continue
        tree=ast.parse(block)
        imports=[n.module if isinstance(n,ast.ImportFrom) else a.name for n in ast.walk(tree)
                 if isinstance(n,(ast.Import,ast.ImportFrom)) for a in (n.names if isinstance(n,ast.Import) else [None])]
        if set(imports)-{'datetime','secrets'}:raise ValueError('unreviewed import')
        # These exact blocks have been inspected: pure definitions, literal dictionaries, no I/O/installers.
        namespace={};exec(compile(tree,str(DOCUMENT)+':'+first,'exec'),namespace)
        modules[first[2:]]=namespace
    axes=validate_event(json.loads((ROOT/'examples/v0_3/manifest.json').read_text())['event'])
    findings=[]
    def record(label,fn):
        try:result=fn();return {'case':label,'result':result}
        except Exception as exc:return {'case':label,'error_type':type(exc).__name__,'error':str(exc)}
    for year,month,day,expected in [(2000,1,1,[3,"Kib'"]),(2012,12,21,[4,'Ajaw']),(2026,10,17,[8,'Ben'])]:
        reported=modules['maya_calendar.py']['date_to_tzolkin'](year,month,day)
        conditional=maya_model(year,month,day)
        findings.append({'case':f'maya-{year}-{month}-{day}','qwen_claimed':expected,'qwen_code':reported,
                         'conditional_corrected_model':conditional,
                         'historical_source_status':'BLOCKED_SOURCE; corrected model arithmetic only'})
    observations=modules['shakuna.py']
    findings.append(record('shakuna-incomplete-cat-still-OK',lambda:observations['shakuna_card']('audit',{'object':'cat','action':'crosses_path'})))
    with patch('secrets.SystemRandom') as rng:
        rng.return_value.choice.side_effect=lambda sequence:sequence[0]
        findings.append(record('slavic-digital-dict-choice-error',lambda:modules['slavic.py']['slavic_digital']('s','e',['p1','p2'],{'i1':'p1','i2':'p2'})))
    findings.append(record('name-01-original-dictionary',lambda:modules['name_grids.py']['name_grids_card']('e','田中','太郎')))
    findings.append(record('name-multiple-character-formula',lambda:modules['name_grids.py']['calculate_grids']('山田','一二')))
    findings.append({'case':'name-conditional-arithmetic-counterexample','manual_per_character':[[3,5],[1,2]],
                     'conditional_corrected_model':name_arithmetic([3,5],[1,2]),'historical_profile':'UNVERIFIED'})
    cards=[modules['maya_calendar.py']['maya_card']('e',2012,12,21), observations['shakuna_card']('e',{'object':'crow','action':'caws','direction':'left'}),
           modules['slavic.py']['slavic_manual']('s','e','SL03','i','p'),modules['name_grids.py']['name_grids_card']('e','山','一')]
    for card in cards:
        try:validate_cards([card],axes);result='ACCEPTED'
        except ContractError as exc:result=str(exc)
        findings.append({'case':'contract-'+card['core_id'],'validator_result':result})
    return {'schema_version':'qwen-four-audit-v1','source_sha256':source_sha256,
            'execution_scope':'only four reviewed embedded definitions; no archive .git, JavaScript, npm or installers executed',
            'findings':findings}


if __name__=='__main__':
    result=json.dumps(build(),ensure_ascii=False,indent=2)+'\n'
    path=ROOT/'research/audit/four_cores/recalculated.json'
    if sys.argv[1:]==['--check']:
        if path.read_text(encoding='utf-8')!=result:raise SystemExit('FAIL: stale audit')
        print('MATCH: Qwen four-core discrepancies reproduced')
    elif sys.argv[1:]:raise SystemExit('usage: audit_four_qwen.py [--check]')
    else:
        path.write_text(result,encoding='utf-8');print('WRITTEN: separate audit; original unchanged')
