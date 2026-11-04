"""Synthetic regression cases; no private archive or real tickets in repository."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import zipfile

from dis_oracle.contracts import digest
from dis_oracle.workflow import Workflow, frequency, main

NOW = '2030-01-01T10:00:00Z'
TARGET = '2030-01-01T11:00:00Z'
NUMS = [[1, 2, 3, 4], [5, 6, 7, 8]]
OTHER = [[9, 10, 11, 12], [13, 14, 15, 16]]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'study.sqlite3'
        self.now = NOW
        self.w = Workflow(self.path, _clock=lambda: self.now)
        self.addCleanup(self.w.close)

    def seed(self, game='hunt', draw=99):
        return self.w.ingest(game, draw, NUMS, 'SYNTHETIC')

    def predict(self, **kw):
        return self.w.forecast('hunt', 100, TARGET, **kw)

    def test_replay_does_not_redraw_even_after_deadline(self):
        self.seed(); p = self.predict()
        self.now = '2030-01-01T12:00:00Z'
        self.assertEqual(p, self.predict())
        self.assertEqual(2, self.w.verify()['records'])
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            self.w.forecast('hunt', 100, '2030-01-01T13:00:00Z')

    def test_cancel_is_retained_and_blocks_regeneration(self):
        self.seed(); self.predict()
        self.w.cancel('hunt', 100, 'SYNTHETIC cancellation')
        self.w.cancel('hunt', 100, 'same command retry')
        with self.assertRaisesRegex(ValueError, 'cancelled'): self.predict()
        self.now = '2030-01-01T12:00:00Z'
        self.w.ingest('hunt', 100, NUMS, 'SYNTHETIC')
        r = self.w.report()
        self.assertEqual(['hunt:100'], r['cancelled'])
        self.assertEqual([], r['trials'])
        self.assertEqual(4, r['chain']['records'])

    def test_cannot_hide_a_resolved_failure_by_cancellation(self):
        self.seed(); self.predict()
        self.now = '2030-01-01T12:00:00Z'
        self.w.ingest('hunt', 100, OTHER, 'SYNTHETIC')
        with self.assertRaisesRegex(ValueError, 'resolved'): self.w.cancel('hunt', 100, 'hide')
        self.assertEqual(1, len(self.w.report()['trials']))

    def test_invalid_or_late_command_changes_nothing(self):
        for value in ([[1,1,2,3], [5,6,7,8]], [[0,1,2,3], [5,6,7,8]], [[True,2,3,4], [5,6,7,8]]):
            with self.assertRaises(ValueError): self.w.ingest('hunt', 99, value, 'synthetic')
        self.seed(); before = self.w.verify()
        with self.assertRaises(ValueError): self.w.forecast('hunt', 100, NOW)
        with self.assertRaises(ValueError): self.w.forecast('hunt', 107, TARGET)
        with self.assertRaises(ValueError): self.w.forecast('four_of_twenty', 100, TARGET)
        self.assertEqual(before, self.w.verify())

    def test_known_future_draw_blocks_past_prediction(self):
        self.seed(draw=101)
        with self.assertRaisesRegex(ValueError, 'already known'): self.predict()

    def test_correction_is_optimistic_and_append_only(self):
        old = self.seed()
        self.assertEqual(old, self.seed())
        with self.assertRaisesRegex(ValueError, 'conflicting'): self.w.ingest('hunt', 99, OTHER, 'SYNTHETIC')
        corrected = self.w.ingest('hunt', 99, OTHER, 'SYNTHETIC', correction_of=digest(old), reason='SYNTHETIC typo')
        self.assertEqual(digest(old), corrected['correction_of'])
        self.assertEqual(digest(corrected),self.w.lookup('hunt',99)['outcome_hash'])
        self.assertEqual(2, self.w.verify()['records'])
        with self.assertRaises(sqlite3.IntegrityError): self.w.db.execute('DELETE FROM workflow_events')
        with self.assertRaises(sqlite3.IntegrityError): self.w.db.execute("UPDATE workflow_events SET at='wrong'")

    def test_report_requires_exact_game_and_draw(self):
        self.seed(); self.predict()
        self.now='2030-01-01T12:00:00Z'
        self.w.ingest('four_of_twenty', 100, NUMS, 'SYNTHETIC')
        self.w.ingest('hunt', 101, NUMS, 'SYNTHETIC')
        self.assertEqual(['hunt:100'], self.w.report()['pending'])
        self.assertEqual([], self.w.report()['trials'])
        self.w.ingest('hunt', 100, NUMS, 'SYNTHETIC')
        r=self.w.report()
        f=next(g for g in r['groups'] if g['origin']=='LOCAL_FUTURE_UNATTESTED' and g['game']=='hunt' and g['method']=='frequency100-v1')
        self.assertEqual((1,8), (f['n'],f['method_hits']))

    def test_occurrence_time_cannot_precede_declared_target(self):
        self.seed(); self.predict()
        with self.assertRaisesRegex(ValueError, 'precedes'):
            self.w.ingest('hunt',100,NUMS,'SYNTHETIC',occurred_at=NOW)

    def test_failure_at_commit_deadline_rolls_back(self):
        self.seed(); times=iter([NOW, TARGET])
        self.w.clock=lambda: next(times)
        with self.assertRaisesRegex(ValueError, 'while computing'): self.predict()
        self.assertEqual(1,self.w.verify()['records'])

    def test_deadline_is_checked_at_append_too(self):
        self.seed(); times=iter([NOW, NOW, TARGET])
        self.w.clock=lambda: next(times)
        with self.assertRaisesRegex(ValueError,'journal commit'): self.predict()
        self.assertEqual(1,self.w.verify()['records'])

    def test_backup_includes_wal_and_never_overwrites(self):
        self.seed(); self.predict()
        backup=Path(self.tmp.name)/'backup.sqlite3'
        self.assertEqual(self.w.verify(), self.w.backup(backup))
        with Workflow(backup) as copy: self.assertEqual(self.w.state(),copy.state())
        with self.assertRaises(ValueError): self.w.backup(backup)

    def test_tampering_detected_before_any_mutation(self):
        self.seed()
        self.w.db.execute('DROP TRIGGER workflow_no_update')
        self.w.db.execute("UPDATE workflow_events SET at='2029-01-01T00:00:00Z'")
        with self.assertRaisesRegex(ValueError,'corrupted'): self.predict()

    def test_concurrent_commands_return_one_frozen_forecast(self):
        self.seed()
        def run(_):
            with Workflow(self.path,_clock=lambda:NOW) as w: return w.forecast('hunt',100,TARGET)
        with ThreadPoolExecutor(max_workers=2) as pool: a,b=list(pool.map(run, range(2)))
        self.assertEqual(a,b)
        self.assertEqual(2,self.w.verify()['records'])

    def test_protocol_separates_studies_and_keeps_cancelled_slots(self):
        self.now='2030-01-01T09:00:00Z'
        protocol={'study_id':'synthetic-1','hypothesis':'SYNTHETIC test', 'game':'hunt',
            'method':'frequency100-v1','metric':'within_field_hits','control':'random','sample_size':1,
            'starts_at':NOW,'ends_at':'2030-01-02T00:00:00Z'}
        self.w.register(protocol)
        self.assertEqual(1,self.w.verify()['records'])
        self.w.register(protocol)
        changed=deepcopy(protocol); changed['sample_size']=2
        with self.assertRaises(ValueError): self.w.register(changed)
        self.now=NOW; self.seed(); self.predict(study_id='synthetic-1')
        self.w.cancel('hunt',100,'SYNTHETIC')
        with self.assertRaisesRegex(ValueError,'cap'): self.w.forecast('hunt',101,TARGET,study_id='synthetic-1')
        summary=self.w.report()['study_summaries'][0]
        self.assertEqual((1,1,0,True),(summary['enrolled'],summary['cancelled'],summary['paired'],summary['enrollment_closed']))

    def test_symbolic_resume_keeps_original_and_rejects_template_substitution(self):
        self.w.clock = lambda: datetime.now(timezone.utc).isoformat()
        self.seed()
        template=json.loads(Path('examples/workflow/manifest.json').read_text())
        target=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        original_append=self.w._append
        def fail_after_freeze(kind,key,payload):
            if kind=='forecast': raise OSError('SYNTHETIC interruption after symbolic freeze')
            return original_append(kind,key,payload)
        with patch.object(self.w,'_append',side_effect=fail_after_freeze):
            with self.assertRaises(OSError): self.w.forecast('hunt',100,target,template=template)
        self.assertEqual(1,self.w.verify()['records'])
        changed=deepcopy(template); changed['source_refs'].append('changed input')
        with self.assertRaisesRegex(ValueError,'different template'):
            self.w.forecast('hunt',100,target,template=changed)
        first=self.w.forecast('hunt',100,target,template=template)
        again=self.w.forecast('hunt',100,target,template=template)
        self.assertEqual(first,again)
        self.assertEqual('PICK',first['methods']['lottery-rune-hash-v2']['state'])
        self.assertEqual(2,self.w.verify()['records'])

    def test_clock_rollback_rejected(self):
        self.seed(); before=self.w.verify()
        self.now='2029-12-31T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'clock'): self.w.ingest('hunt',98,NUMS,'SYNTHETIC')
        self.assertEqual(before,self.w.verify())

    def archive(self, duplicate=False):
        path=Path(self.tmp.name)/'old.zip'; root='Oracle_2026-10-22/'
        row={'game':'hunt','draw':99,'fields':NUMS}
        pred={'game':'hunt','draw':100,'fields':NUMS,'random_control':OTHER,'target_at_assumed':TARGET,'fixed_at':NOW}
        with zipfile.ZipFile(path,'w') as z:
            for name,obj in {
                'updates/20300101/latest-archive-state.json':{'observations_ref':'20300101/history.json','summary_refs':[],
                    'cancelled_forecasts':[{'game':'hunt','draw':100,'state':'CANCELLED_BY_USER'}]},
                'updates/20300101/history.json':[row,row] if duplicate else [row],
                'hunt-100/numeric-selection.json':pred}.items(): z.writestr(root+name,json.dumps(obj))
        return path

    def test_migration_preserves_unknown_availability_and_cancellation(self):
        archive=self.archive(); result=self.w.migrate(archive)
        self.assertEqual((1,1), (result['outcomes_added'],result['forecasts_added']))
        self.assertEqual('ALREADY_IMPORTED',self.w.migrate(archive)['state'])
        state=self.w.state(); old=state['outcomes']['hunt:99']
        self.assertIsNone(old['source_recorded_at'])
        self.assertEqual(NOW,old['received_at'])
        self.assertTrue(state['forecasts']['hunt:100']['target_time_assumed'])
        self.assertEqual(['hunt:100'],self.w.report()['cancelled'])
        with self.assertRaisesRegex(ValueError,'cancelled'): self.predict()

    def test_duplicate_migration_is_atomic(self):
        with self.assertRaisesRegex(ValueError,'duplicate'): self.w.migrate(self.archive(duplicate=True))
        self.assertEqual(0,self.w.verify()['records'])

    def test_frequency_uses_receipt_cutoff_and_only_eligible_game(self):
        rows=[{'game':'hunt','draw':n,'fields':NUMS,'received_at':NOW} for n in range(1,106)]
        rows.extend([{'game':'hunt','draw':106,'fields':OTHER,'received_at':TARGET},
                     {'game':'four_of_twenty','draw':106,'fields':OTHER,'received_at':NOW},
                     {'game':'hunt','draw':107,'fields':OTHER,'received_at':NOW,'numeric_eligible':False}])
        r=frequency(rows,'hunt',108,NOW)
        self.assertEqual((100,6,105),(r['n'],r['draws'][0],r['draws'][-1]))
        self.assertEqual(NUMS,r['fields'])
        with self.assertRaises(ValueError): frequency(rows,'hunt',108,NOW,limit=20)
        with self.assertRaises(ValueError): frequency(rows+[rows[0]],'hunt',108,NOW)
        with self.assertRaises(KeyError): frequency([{'game':'hunt','draw':1,'fields':NUMS}], 'hunt',108,NOW)

    def test_frequency_excludes_known_source_conflict(self):
        r=frequency([{'game':'hunt','draw':47129,'fields':NUMS,'received_at':NOW}], 'hunt',47130,NOW)
        self.assertEqual('ABSTAIN',r['state'])


if __name__=='__main__': unittest.main()
