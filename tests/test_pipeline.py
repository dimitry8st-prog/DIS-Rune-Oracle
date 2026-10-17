"""Real v0.3 integration: independent stores, restart, audit and legacy replay."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.contracts import ContractError, digest, validate_cards, validate_event
from dis_oracle.engine import freeze as legacy_freeze
from dis_oracle.journal import Journal, JournalError
from dis_oracle.pipeline import Cycle
from research_stats.core import report as statistics_report

FIXTURE = Path(__file__).parents[1] / 'examples/v0_3/manifest.json'
BEFORE = '2098-12-30T00:00:00Z'
AFTER = '2099-01-01T00:00:02Z'


def fixture():
    return json.loads(FIXTURE.read_text())


def outcome():
    return {'event_id': fixture()['event']['event_id'], 'axis_id': 'target', 'scenario_id': 'A',
            'source': 'SYNTHETIC fixture', 'observed_at': '2099-01-01T00:00:00Z'}


def numeric_outcome():
    return {'event_id': outcome()['event_id'], 'occurred_at': outcome()['observed_at'],
            'recorded_at': '2099-01-01T00:00:01Z', 'confirmation': 'CONFIRMED',
            'source_ref': 'SYNTHETIC fixture', 'fields': [[1,2,3,4], [5,6,7,8]]}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'cycle'

    def test_end_to_end_restart_all_four_and_exact_stats_bridge(self):
        with Cycle(self.root, 'full') as c:
            state = c.start(fixture())
            cards = state['cards']
            self.assertEqual(len(cards), 4)
            validate_cards(cards, validate_event(fixture()['event']))
            for card in cards:
                self.assertEqual(card['input_hash'], digest(card['inputs']))
                self.assertEqual(card['claims'], [])
            self.assertEqual(cards[-1]['raw_result']['final_state'], 'pending')
            c.step({'request_id':'refusal','operation':'confirm','confirmation_result':'yin_bei'})
        with Cycle(self.root, 'full') as c:
            c.start(fixture())
            self.assertEqual(len(c.status()['cards'][-1]['raw_result']['attempts']), 1)
            c.step({'request_id':'no-redraw','operation':'finish'})
            c.review({'claims_by_core':{}})
            original = c.freeze(at=BEFORE)
            comparison = original['frozen']['comparison']
            self.assertEqual(comparison['core_weight'], '0.10')
            self.assertEqual(len(comparison['cores']), 10)
            self.assertEqual(comparison['axes']['target']['prediction'], None)
            self.assertEqual(comparison['axes']['target']['comparison_coverage_percent'], 0)
            self.assertEqual(sum(v['status']=='UNAVAILABLE' for v in comparison['cores'].values()), 6)
            before = c.science({'report_id':'pre-v1','reason':'Before outcome'})
            self.assertEqual(before['numeric_external_method']['paired_total']['n'], 0)
            self.assertEqual(before['trials'][0]['state'], 'AWAITING_OUTCOME')
            c.evaluate(outcome(), at=AFTER)
            request = {'report_id':'post-v1','reason':'Synthetic outcome added','supersedes':'pre-v1','numeric_outcomes':[numeric_outcome()]}
            after = c.science(request)
            data = fixture()['numeric_study']; data.update(analysis_at=AFTER, outcomes=[numeric_outcome()])
            self.assertEqual(after['numeric_external_method'], statistics_report(data))
            self.assertEqual(after['categorical_paired']['n'], 0)
            self.assertEqual(after['numeric_external_method']['paired_total']['n'], 1)
            self.assertEqual(after['numeric_external_method']['matched_brier_pairs'], [])
            self.assertEqual(c.freeze(), original)
            with self.assertRaises(JournalError): c.freeze(at=AFTER)
        with Cycle(self.root, 'full') as c:
            with patch('dis_oracle.adapters.mo.secrets.SystemRandom', side_effect=AssertionError('redraw')):
                c.start(fixture())
            self.assertEqual(c.science(request), after)
            self.assertEqual(c.evaluate(outcome(), at=AFTER), after['trials'][0]['evaluation'])
            self.assertEqual(c.freeze(), original)
            self.assertGreater(c.journal.verify()['records'], 8)

    def test_digital_replay_does_not_draw_after_restart(self):
        m = fixture(); m['adapters'] = {'yijing':{'mode':'digital'},'mo':{'mode':'digital'},'qiuqian':{'mode':'digital','max_attempts':1}}
        with Cycle(self.root, 'digital') as c:
            first = c.start(m)['cards']
            with patch('dis_oracle.adapters.qiuqian.secrets.SystemRandom') as rng:
                rng.return_value.choice.side_effect = [0,1]
                confirmed = c.step({'request_id':'draw1','operation':'advance'})
            self.assertEqual(confirmed['card']['raw_result']['final_state'], 'confirmed')
        with Cycle(self.root, 'digital') as c:
            with patch('dis_oracle.adapters.yijing.secrets.SystemRandom', side_effect=AssertionError('redraw')):
                state = c.start(m)
                self.assertEqual(c.step({'request_id':'draw1','operation':'advance'}), confirmed)
            self.assertEqual(state['cards'][:2], first[:2])
            self.assertEqual(state['cards'][2], confirmed['card'])

    def test_preflight_rejects_bool_floats_missing_conflicting_and_historical(self):
        configs = [
            ('mo',{'mode':'manual','first_throw':True,'second_throw':2}),
            ('mo',{'mode':'manual','first_throw':1.0,'second_throw':2}),
            ('mo',{'mode':'manual','first_throw':1}),
            ('mo',{'mode':'digital','first_throw':None}),
            ('mo',{'mode':'historical'}),
            ('qiuqian',{'mode':'manual','max_attempts':True,'stick_number':4}),
            ('qiuqian',{'mode':'manual','max_attempts':0,'stick_number':4,'confirmation_result':'yin_bei'}),
            ('yijing',{'mode':'manual','throws':[[True,2,3]]*6}),
            ('yijing',{'mode':'digital','throws':None}),
            ('rune',{'choices':[{'slot':True,'rotation':0}]*3}),
        ]
        for i,(core,config) in enumerate(configs):
            with self.subTest(config=config), Cycle(self.root, str(i)) as c:
                m = fixture(); m['adapters'][core] = config
                with self.assertRaises(ContractError):
                    c.start(m)
                self.assertIsNone(c._get('registered'))
                self.assertEqual(list(c.private.glob('*.sqlite3')), [])

    def test_changed_manifest_event_id_and_types_rejected_without_dispatch(self):
        m = fixture()
        with Cycle(self.root,'fixed') as c:
            c.start(m)
            for mutate in ('event','float','mode','source'):
                altered = deepcopy(m)
                if mutate == 'event': altered['event']['event_id'] = 'OTHER'
                if mutate == 'float': altered['adapters']['mo']['first_throw'] = 1.0
                if mutate == 'mode': altered['adapters']['mo'] = {'mode':'digital'}
                if mutate == 'source': altered['source_refs'].append('later')
                with self.subTest(mutate=mutate), self.assertRaises(JournalError): c.start(altered)
            self.assertEqual(c.start(m)['registration']['manifest'], m)

    def test_resume_after_interrupted_adapter_collection(self):
        with Cycle(self.root,'interrupted') as c:
            with patch('dis_oracle.pipeline.yijing_run', side_effect=RuntimeError('process interrupted')):
                with self.assertRaises(RuntimeError): c.start(fixture())
            self.assertIsNotNone(c._get('registered'))
            self.assertIsNone(c._get('collected'))
            from dis_oracle.adapters.runes import RuneSessions
            store = RuneSessions(c.private/'rune.sqlite3')
            sid = 'v03-'+digest(['interrupted','rune'])
            first = store.status(sid); store.close()
        with Cycle(self.root,'interrupted') as c:
            with patch('dis_oracle.adapters.runes.secrets.token_hex', side_effect=AssertionError('new manifest')):
                cards = c.start(fixture())['cards']
            self.assertEqual(cards[0], first['card'])

    def test_qiuqian_manual_refusal_and_exact_limit(self):
        m=fixture(); m['adapters']={'qiuqian':{'mode':'manual','max_attempts':2,'stick_number':12}}
        with Cycle(self.root,'limits') as c:
            c.start(m)
            one = c.step({'request_id':'1','operation':'confirm','confirmation_result':'yin_bei'})
            self.assertEqual(one['card']['raw_result']['final_state'],'pending')
            two = c.step({'request_id':'2','operation':'confirm','confirmation_result':'xiao_bei'})
            self.assertEqual(two['card']['raw_result']['final_state'],'no_confirmation')
            self.assertEqual(two['card']['raw_result']['stick_number'],12)
            self.assertEqual(len(two['card']['raw_result']['attempts']),2)
            with self.assertRaises(ContractError): c.step({'request_id':'3','operation':'confirm','confirmation_result':'sheng_bei'})
            with self.assertRaises(JournalError): c.step({'request_id':'2','operation':'confirm','confirmation_result':'yin_bei'})
            self.assertEqual(c.step({'request_id':'1','operation':'confirm','confirmation_result':'yin_bei'}),one)

    def test_zero_limit_pending_freeze_and_no_automatic_confirmation(self):
        for limit in (0,1):
            with Cycle(self.root/str(limit),str(limit)) as c:
                m=fixture(); m['adapters']={'qiuqian':{'mode':'digital','max_attempts':limit}}
                cards=c.start(m)['cards']
                self.assertEqual(cards[0]['raw_result']['final_state'],'pending' if limit else 'no_confirmation')
                c.review({'claims_by_core':{}})
                result=c.freeze(at=BEFORE)
                self.assertIsNone(result['frozen']['comparison']['axes']['target']['prediction'])
                self.assertEqual(result['frozen']['raw_cards'][0]['raw_result']['attempts'],[])

    def test_manual_claim_is_only_source_of_router_forecast(self):
        with Cycle(self.root,'review') as c:
            cards=c.start(fixture())['cards']
            with self.assertRaises(ContractError): c.freeze()
            claim={'claim_id':'human-1','type':'FORECAST','text':'Explicit human hypothesis A, not a traditional rule',
                   'source_fragment':cards[0]['interpretation'].split(' → ')[0], 'axis_id':'target','scenario_id':'A',
                   'polarity':'SUPPORT','review_status':'ACCEPTED','reviewed_by':'SYNTHETIC-reviewer','reviewed_at':BEFORE}
            review={'claims_by_core':{'rune':[claim]}}
            c.review(review)
            result=c.freeze(at=BEFORE)
            self.assertEqual(result['frozen']['comparison']['axes']['target']['prediction'],'A')
            self.assertEqual(result['frozen']['comparison']['axes']['target']['support_percent']['A'],10)
            self.assertEqual(c._get('collected')['cards'][0]['claims'],[])
            c.evaluate(outcome(),at=AFTER)
            science=c.science({'report_id':'v1','reason':'paired evaluation'})
            self.assertEqual(science['categorical_paired']['n'],1)
            self.assertEqual(science['categorical_paired']['mean_ci'],[-1,1])
            with self.assertRaises(JournalError): c.review({'claims_by_core':{}})
            with self.assertRaises(ContractError): c.step({'request_id':'late','operation':'finish'})

    def test_cannot_promote_mechanical_abstention_or_forge_fragment(self):
        with Cycle(self.root,'no-invention') as c:
            cards=c.start(fixture())['cards']
            claim={'claim_id':'x','type':'FORECAST','text':'A','source_fragment':cards[2]['interpretation'],
                   'axis_id':'target','scenario_id':'A','polarity':'SUPPORT','review_status':'PENDING'}
            with self.assertRaises(ContractError): c.review({'claims_by_core':{'mo':[claim]}})
            claim['source_fragment']='invented text absent from reading'
            with self.assertRaises(ContractError): c.review({'claims_by_core':{'rune':[claim]}})
            with self.assertRaises(ContractError): c.review({'claims_by_core':{'maya':[]}})
            c.review({'claims_by_core':{}})
            # An out-of-band private-store command cannot silently change what was reviewed.
            from dis_oracle.adapters.qiuqian import QiuqianSessions
            with QiuqianSessions(c.private/'qiuqian.sqlite3') as store:
                store.finish('v03-'+digest(['no-invention','qiuqian']), fixture()['event']['event_id'], 'external-finish')
            with self.assertRaises(ContractError): c.freeze(at=BEFORE)

    def test_reports_append_only_and_correction_version_is_separate(self):
        with Cycle(self.root,'audit') as c:
            c.start(fixture()); c.review({'claims_by_core':{}}); original=c.freeze(at=BEFORE)
            first=c.science({'report_id':'v1','reason':'initial'})
            second=c.science({'report_id':'v2','reason':'clarification','supersedes':'v1'})
            self.assertEqual(first['original_report_hash'],second['original_report_hash'])
            self.assertEqual(c.freeze(),original)
            with self.assertRaises(JournalError): c.science({'report_id':'v1','reason':'overwritten'})
            with self.assertRaises(ContractError): c.science({'report_id':'v3','reason':'bad reference','supersedes':'missing'})
            with self.assertRaises(sqlite3.IntegrityError):
                c.journal.connection.execute("UPDATE entries SET payload='{}'")
            c.journal.connection.execute('DROP TRIGGER immutable_update')
            c.journal.connection.execute("UPDATE entries SET payload='{}' WHERE seq=1")
            c.journal.connection.commit()
            with self.assertRaises(JournalError): c.status()
            with self.assertRaises(JournalError): c.freeze()

    def test_retro_missing_data_and_numeric_no_forced_mapping(self):
        m=fixture();m['event']['mode']='retrospective';m['adapters']={};del m['numeric_study']
        with Cycle(self.root,'retro') as c:
            c.start(m);c.review({'claims_by_core':{}});c.freeze(at=BEFORE)
            result=c.evaluate(outcome(),at=AFTER)
            self.assertFalse(result['eligible_prospective']);self.assertIsNone(result['baseline_error'])
            report=c.science({'report_id':'v1','reason':'retrospective audit'})
            self.assertEqual(report['trials'][0]['classification'],'RETROSPECTIVE')
            self.assertEqual(report['categorical_paired']['n'],0)
            self.assertEqual(report['lottery-rune-hash-v2']['status'],'UNAVAILABLE')
            with self.assertRaises(ContractError): c.science({'report_id':'v2','reason':'invention','numeric_outcomes':[numeric_outcome()]})

    def test_late_registration_wrong_outcome_and_clock_override(self):
        m=fixture()
        with Cycle(self.root,'time') as c:
            with self.assertRaises(ContractError): c.start(m,at=AFTER)
            c.start(m);c.review({'claims_by_core':{}})
            with self.assertRaises(ContractError): c.freeze(at=AFTER)
            c.freeze(at=BEFORE)
            bad=outcome();bad['event_id']='OTHER'
            with self.assertRaises(ContractError): c.evaluate(bad,at=AFTER)
            with self.assertRaises(ContractError): c.evaluate(outcome(),at=BEFORE)
            with self.assertRaises(ContractError): c.science({'report_id':'bad','reason':'before outcome','numeric_outcomes':[numeric_outcome()]})
        with Cycle(self.root/'imported','imported') as c:
            m['provenance']='IMPORTED';del m['numeric_study']
            with self.assertRaises(ContractError): c.start(m,at=BEFORE)
            c.start(m)
            with self.assertRaises(ContractError): c.freeze(at=BEFORE)

    def test_numeric_registration_cannot_contain_known_outcome_or_unbound_event(self):
        for variant in ('outcome','event','futurepick','retro'):
            m=fixture()
            if variant=='outcome':m['numeric_study']['outcomes']=[numeric_outcome()]
            if variant=='event':m['numeric_study']['events'][0]['event_id']='OTHER'
            if variant=='futurepick':m['numeric_study']['predictions'][0]['fixed_at']=AFTER
            if variant=='retro':m['event']['mode']='retrospective'
            with self.subTest(variant=variant),Cycle(self.root,variant) as c:
                with self.assertRaises(ValueError):c.start(m)
                self.assertIsNone(c._get('registered'))

    def test_legacy_v02_freeze_replay_survives_version_upgrade(self):
        with JournalContext(self.root/'old.sqlite3') as j:
            m=fixture()
            with patch('dis_oracle.engine.__version__','0.2.0'):
                old=legacy_freeze(j,'old',m['event'],[],frozen_at=BEFORE)
            self.assertEqual(legacy_freeze(j,'old',m['event'],[]),old)
            self.assertEqual(old['engine_version'],'0.2.0')

    def test_event_cannot_be_redrawn_under_another_run_id(self):
        with Cycle(self.root, 'first') as c:
            c.start(fixture())
        with Cycle(self.root, 'second') as c:
            with self.assertRaises(JournalError): c.start(fixture())
            self.assertEqual(list(c.private.glob('*.sqlite3')), [])

    def test_pending_and_conflicting_manual_claims_never_force_a_prediction(self):
        for kind in ('pending', 'conflict'):
            with Cycle(self.root/kind, kind) as c:
                cards=c.start(fixture())['cards']
                claim={'claim_id':'a','type':'FORECAST','text':'Human hypothesis',
                       'source_fragment':cards[0]['interpretation'], 'axis_id':'target','scenario_id':'A',
                       'polarity':'SUPPORT','review_status':'ACCEPTED','reviewed_by':'SYNTHETIC-reviewer','reviewed_at':BEFORE}
                other=deepcopy(claim);other.update(claim_id='b',scenario_id='B')
                if kind=='pending':other['review_status']='PENDING'
                c.review({'claims_by_core':{'rune':[claim,other]}})
                axis=c.freeze(at=BEFORE)['frozen']['comparison']['axes']['target']
                self.assertIsNone(axis['prediction'])
                self.assertTrue(axis['pending_claims'] if kind=='pending' else axis['internal_conflicts'])

    def test_digital_boundary_all_confirmation_branches(self):
        for sides, expected in (([0,1],'confirmed'),([0,0],'no_confirmation'),([1,1],'no_confirmation')):
            name=str(sides)
            with Cycle(self.root/name, name) as c:
                m=fixture();m['adapters']={'qiuqian':{'mode':'digital','max_attempts':1}}
                c.start(m)
                with patch('dis_oracle.adapters.qiuqian.secrets.SystemRandom') as rng:
                    rng.return_value.choice.side_effect=sides
                    result=c.step({'request_id':'draw','operation':'advance'})
                self.assertEqual(result['card']['raw_result']['final_state'],expected)
                self.assertEqual(len(result['card']['raw_result']['attempts']),1)
                with self.assertRaises(ContractError):c.step({'request_id':'extra','operation':'advance'})

    def test_interrupted_step_is_recovered_from_private_store(self):
        with Cycle(self.root,'step-crash') as c:
            c.start(fixture())
            command={'request_id':'observation','operation':'confirm','confirmation_result':'sheng_bei'}
            original_save=c._save
            def interrupt(suffix,value):
                if suffix.startswith('step:'):raise RuntimeError('interrupted after private commit')
                return original_save(suffix,value)
            with patch.object(c,'_save',side_effect=interrupt):
                with self.assertRaises(RuntimeError):c.step(command)
        with Cycle(self.root,'step-crash') as c:
            self.assertEqual(c.status()['cards'][-1]['raw_result']['final_state'],'confirmed')
            replay=c.step(command)
            self.assertEqual(len(replay['card']['raw_result']['attempts']),1)

    def test_duplicate_json_input_is_rejected_by_unified_cli(self):
        path=Path(self.tmp.name)/'duplicate.json'
        path.write_text('{"claims_by_core":{},"claims_by_core":{}}')
        result=subprocess.run([sys.executable,'-m','dis_oracle','cycle-review',str(path),
                               '--directory',str(self.root),'--run-id','duplicate'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('duplicate JSON key',result.stderr)

    def test_cli_full_demo_and_repeat_refuses_overwriting(self):
        path=Path(self.tmp.name)/'demo'
        cmd=[sys.executable,'-m','dis_oracle','cycle-demo','--directory',str(path)]
        result=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['numeric_explicit_external_method_pairs'],1)
        original=(path/'original-report.json').read_bytes()
        again=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(again.returncode,2)
        self.assertEqual((path/'original-report.json').read_bytes(),original)
        chain=subprocess.run([sys.executable,'-m','dis_oracle','verify','--db',str(path/'state/cycle-v03.sqlite3')],capture_output=True,text=True)
        self.assertEqual(chain.returncode,0,chain.stderr)
        self.assertGreater(json.loads(chain.stdout)['records'],8)


class JournalContext(Journal):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


if __name__=='__main__':unittest.main()
