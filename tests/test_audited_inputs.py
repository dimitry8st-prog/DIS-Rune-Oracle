"""Arithmetic is independently checked; historical validation is NOT asserted."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.adapters import audited_inputs as a
from dis_oracle.contracts import ContractError, digest, validate_cards, validate_event
from dis_oracle.pipeline import Cycle
from tests.test_pipeline import BEFORE, AFTER, outcome, numeric_outcome

ROOT=Path(__file__).resolve().parents[1]


def fixture():return json.loads((ROOT/'examples/four_cores/manifest.json').read_text())


class AuditedInputTests(unittest.TestCase):
    def test_calendar_jdn_independent_python_ordinal_and_boundaries(self):
        for value in (date(1,1,1),date(1582,10,4),date(1582,10,15),date(1900,2,28),date(2000,2,29),date(9999,12,31)):
            with self.subTest(value=value):
                self.assertEqual(a.gregorian_jdn(value.year,value.month,value.day),value.toordinal()+1721425)
        for args in ((1900,2,29),(2026,4,31),(0,1,1),(True,1,1),(2000,True,1),(2000,1,1.0)):
            with self.subTest(args=args),self.assertRaises(ContractError):a.gregorian_jdn(*args)

    def test_conditional_calendar_anchor_sequence_and_260_unique_days(self):
        # Independent oracle: chosen 2012-12-21 = 4 Ajaw assumption + civil date differences.
        anchor=date(2012,12,21);pairs=set()
        for offset in range(-260,261):
            day=anchor+timedelta(days=offset);result=a.maya_model(day.year,day.month,day.day)
            self.assertEqual(result['number'],(3+offset)%13+1)
            self.assertEqual(result['sign_index'],(19+offset)%20)
            if 0<=offset<260:pairs.add((result['number'],result['sign_index']))
        self.assertEqual(len(pairs),260)
        self.assertEqual(a.maya_model(2000,1,1)['number'],11)
        self.assertEqual(a.maya_model(2026,10,17)['sign_label'],'Lamat')

    def test_calendar_requires_explicit_model_and_day_boundary(self):
        config=fixture()['adapters']['maya']
        for key,value in (('mode','pajooneem'),('profile','traditional'),('day_boundary','sunrise')):
            wrong=deepcopy(config);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):a.card('maya','e',wrong)
        card=a.card('maya','e',config)
        self.assertEqual(card['status'],'ABSTAIN')
        self.assertEqual(card['raw_result']['assumptions']['historical_verification'],'UNVERIFIED')

    def test_five_grid_conditional_arithmetic_multi_and_single_cases(self):
        self.assertEqual(a.name_arithmetic([3,5],[1,2]),{'tenkaku':8,'jinkaku':6,'chikaku':3,'gaikaku':5,'sokaku':11})
        self.assertEqual(a.name_arithmetic([3],[1]),{'tenkaku':4,'jinkaku':4,'chikaku':2,'gaikaku':2,'sokaku':4})
        self.assertEqual(a.name_arithmetic([3],[1,2])['gaikaku'],3)
        self.assertEqual(a.name_arithmetic([3,5],[1])['gaikaku'],4)
        for counts in ([],[True],[1.0],[0],[65]):
            with self.subTest(counts=counts),self.assertRaises(ContractError):a.name_arithmetic(counts,[1])

    def test_names_manual_auto_conflict_variants_and_no_cyrillic_guess(self):
        config=fixture()['adapters']['name_grids']
        for key,value in (('surname','Иванов'),('surname','山々'),('surname_strokes',[3]),('mode','automatic'),('profile','kumazaki-verified')):
            wrong=deepcopy(config);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):a.card('name_grids','e',wrong)
        auto=a.card('name_grids','e',{'mode':'automatic','surname':'田中','given_name':'太郎'})
        self.assertEqual(auto['status'],'UNAVAILABLE')
        self.assertNotIn('grids',auto['raw_result'])
        self.assertEqual(auto['raw_result']['dictionary_license'],'UNAVAILABLE')

    def test_shakuna_requires_every_observed_attribute_and_never_draws(self):
        config=fixture()['adapters']['shakuna']
        with patch('secrets.SystemRandom',side_effect=AssertionError('RNG forbidden')):
            card=a.card('shakuna','e',config)
        self.assertEqual(card['claims'],[]);self.assertEqual(card['raw_result']['matched_rules'],[])
        for field in config['observation']:
            wrong=deepcopy(config);del wrong['observation'][field]
            with self.subTest(field=field),self.assertRaises(ContractError):a.card('shakuna','e',wrong)
        config['mode']='digital'
        with self.assertRaises(ContractError):a.card('shakuna','e',config)

    def test_slavic_binding_song_order_return_policy_and_completion(self):
        original=fixture()['adapters']['slavic']
        for case in ('owner','order','duplicate','chronology','completion','mode'):
            config=deepcopy(original)
            if case=='owner':config['rounds'][0]['participant_id']='p2'
            if case=='order':config['rounds'][0]['song_id']='other'
            if case=='duplicate':config['rounds'][1].update(item_id='i1',participant_id='p1')
            if case=='chronology':config['rounds'][0]['returned_at']='2020-01-01T00:00:00Z'
            if case=='completion':config['rounds']=config['rounds'][:1]
            if case=='mode':config['mode']='digital_adaptation'
            with self.subTest(case=case),self.assertRaises(ContractError):a.card('slavic','e',config)
        pending=deepcopy(original);pending['rounds']=pending['rounds'][:1];pending['completion']='ongoing'
        self.assertEqual(a.card('slavic','e',pending)['raw_result']['procedure_status'],'PENDING')
        repeated=deepcopy(original);repeated['return_policy']='with_replacement';repeated['completion']='songs_finished'
        repeated['rounds'][1].update(item_id='i1',participant_id='p1')
        with patch('secrets.SystemRandom',side_effect=AssertionError('RNG forbidden')):
            card=a.card('slavic','e',repeated)
        self.assertEqual(card['raw_result']['matched_song_interpretations'],[])
        self.assertEqual(card['status'],'ABSTAIN')

    def test_all_cards_full_hash_contract_and_no_automatic_forecasts(self):
        manifest=fixture()
        for core in ('maya','shakuna','slavic','name_grids'):
            card=a.card(core,manifest['event']['event_id'],manifest['adapters'][core])
            validate_cards([card],validate_event(manifest['event']))
            self.assertEqual(card['input_hash'],digest(card['inputs']))
            self.assertEqual(card['claims'],[])
            self.assertNotEqual(card['status'],'OK')

    def test_complete_eight_card_cycle_science_restart_and_original_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            with Cycle(directory,'eight') as c:
                state=c.start(fixture());self.assertEqual(len(state['cards']),8)
                c.review({'claims_by_core':{}});original=c.freeze(at=BEFORE)
                report=c.science({'report_id':'before','reason':'First audit'})
                self.assertEqual(sum(v['status']=='UNAVAILABLE' for v in original['frozen']['comparison']['cores'].values()),2)
                self.assertIsNone(original['frozen']['comparison']['axes']['target']['prediction'])
                c.evaluate(outcome(),at=AFTER)
                after=c.science({'report_id':'after','reason':'Synthetic outcome','supersedes':'before','numeric_outcomes':[numeric_outcome()]})
                self.assertEqual(report['original_report_hash'],after['original_report_hash'])
                self.assertEqual(after['numeric_external_method']['paired_total']['n'],1)
            with Cycle(directory,'eight') as c:
                with patch('secrets.SystemRandom',side_effect=AssertionError('new draw')):
                    restored=c.start(fixture())
                self.assertEqual(restored['cards'],state['cards'])
                self.assertEqual(c.freeze(),original);c.journal.verify()

    def test_concurrent_same_cycle_and_command_returns_same_cards(self):
        import concurrent.futures
        with tempfile.TemporaryDirectory() as directory:
            input_path=ROOT/'examples/four_cores/manifest.json'
            command=[sys.executable,'-m','dis_oracle','cycle-start',str(input_path),'--directory',directory,'--run-id','parallel']
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                responses=list(pool.map(lambda _:subprocess.run(command,capture_output=True,text=True),range(2)))
            for response in responses:self.assertEqual(response.returncode,0,response.stderr)
            self.assertEqual(json.loads(responses[0].stdout)['cards'],json.loads(responses[1].stdout)['cards'])
            with Cycle(directory,'parallel') as c:self.assertEqual(len(c.status()['cards']),8);c.journal.verify()

    def test_original_documents_hashes_and_separate_audit_reproduce(self):
        original=ROOT/'research/qwen/four_cores_UNVERIFIED'
        for relative,expected in json.loads((original/'SHA256SUMS.json').read_text()).items():
            self.assertEqual(hashlib.sha256((original/relative).read_bytes()).hexdigest(),expected)
        result=subprocess.run([sys.executable,str(ROOT/'scripts/audit_four_qwen.py'),'--check'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_independent_cli_import_works_when_fcntl_missing(self):
        script='''import sys
sys.modules['fcntl']=None
from dis_oracle.cli import main
raise SystemExit(main(['compare','examples/mixed.json']))
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        script="import sys; sys.modules['fcntl']=None; from dis_oracle.pipeline import Cycle; Cycle(sys.argv[1],'no-posix')"
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-c',script,directory],cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('Windows cycles are not supported',result.stderr)

    def test_safe_archive_inspection_rejects_traversal_links_and_duplicates(self):
        import io,tarfile
        from scripts.inspect_qwen_tar import inspect
        for case in ('traversal','absolute','symlink','hardlink','duplicate'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                archive=Path(directory)/'unsafe.tar'
                with tarfile.open(archive,'w') as tf:
                    name='../escape' if case=='traversal' else '/escape' if case=='absolute' else 'file'
                    row=tarfile.TarInfo(name)
                    if case in ('symlink','hardlink'):
                        row.type=tarfile.SYMTYPE if case=='symlink' else tarfile.LNKTYPE;row.linkname='/tmp/escape'
                    tf.addfile(row)
                    if case=='duplicate':tf.addfile(tarfile.TarInfo(name))
                destination=Path(directory)/'out'
                with self.assertRaises(ValueError):inspect(archive,destination)
                self.assertFalse(destination.exists())

    def test_observation_after_fact_cutoff_is_rejected_before_random_adapters(self):
        with tempfile.TemporaryDirectory() as directory, Cycle(directory,'leak') as c:
            m=fixture();m['adapters']['shakuna']['observation']['observed_at']='2026-06-01T00:00:00Z'
            with patch('secrets.SystemRandom',side_effect=AssertionError('preflight must precede RNG')):
                with self.assertRaises(ContractError):c.start(m)
            self.assertIsNone(c._get('registered'))
