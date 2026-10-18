"""Regressions reproduce the three independently reported v0.3 defects."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dis_oracle.pipeline import Cycle
from dis_oracle.contracts import ContractError, digest
from dis_oracle.journal import JournalError
from tests.test_pipeline import fixture, outcome, numeric_outcome, BEFORE, AFTER


class V03Regressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.c=Cycle(Path(self.temp.name),'regression');self.addCleanup(self.c.close)
        self.c.start(fixture())

    def resolved(self):
        self.c.review({'claims_by_core':{}});self.c.freeze(at=BEFORE)
        self.c.evaluate(outcome(),at=AFTER)

    def test_report_accepts_outcome_recorded_after_categorical_evaluation(self):
        self.resolved()
        n=numeric_outcome();n['recorded_at']='2099-01-01T00:00:03Z'
        with patch('dis_oracle.pipeline.now_iso',return_value='2099-01-01T00:01:00Z'):
            report=self.c.science({'report_id':'later-record','reason':'Numeric record arrived later','numeric_outcomes':[n]})
        self.assertEqual(report['numeric_external_method']['paired_total']['n'],1)
        self.assertEqual(report['created_at'],'2099-01-01T00:01:00Z')
        self.assertEqual(report['analysis_at'],'2099-01-01T00:01:00Z')

    def test_numeric_correction_requires_link_to_published_outcome(self):
        self.resolved()
        first={'report_id':'original','reason':'First numeric outcome','numeric_outcomes':[numeric_outcome()]}
        self.c.science(first)
        changed=deepcopy(first);changed['report_id']='correction';changed['reason']='Source corrected numbers'
        changed['numeric_outcomes'][0]['fields'][0]=[17,18,19,20]
        with self.assertRaises((ContractError,JournalError)):
            self.c.science(changed)
        self.assertIsNone(self.c._get('science:'+digest('correction')))
        changed['supersedes']='original'
        revised=self.c.science(changed)
        self.assertEqual(revised['request']['supersedes'],'original')
        self.assertEqual(self.c.science(first)['request'],first)

    def test_impossible_review_rejected_without_locking_followup(self):
        cards=self.c.status()['cards']
        claim={'claim_id':'manual','type':'FORECAST','text':'Explicit human hypothesis A',
               'source_fragment':cards[0]['interpretation'],'axis_id':'target','scenario_id':'A',
               'polarity':'SUPPORT','review_status':'ACCEPTED','reviewed_by':'SYNTHETIC reviewer',
               'reviewed_at':'2099-01-01T00:00:01Z'}
        before=self.c.journal.verify()
        with self.assertRaises(ContractError):self.c.review({'claims_by_core':{'rune':[claim]}})
        self.assertEqual(self.c.journal.verify(),before)
        self.assertIsNone(self.c._get('review'))
        claim['reviewed_at']=BEFORE
        self.c.review({'claims_by_core':{'rune':[claim]}})
        self.assertEqual(self.c.freeze(at=BEFORE)['frozen']['comparison']['axes']['target']['prediction'],'A')

    def test_analysis_cutoff_and_creation_clock_are_separate_and_replayed(self):
        self.resolved()
        n=numeric_outcome();n['recorded_at']='2099-01-01T00:00:03Z'
        request={'report_id':'cutoff','reason':'Recorded before cutoff', 'analysis_at':'2099-01-01T00:00:04Z','numeric_outcomes':[n]}
        with patch('dis_oracle.pipeline.now_iso',return_value='2099-01-01T00:01:00Z'):
            report=self.c.science(request)
        self.assertEqual(report['analysis_at'],'2099-01-01T00:00:04Z')
        self.assertEqual(report['created_at'],'2099-01-01T00:01:00Z')
        self.assertEqual(self.c.science(request),report)
        for cutoff in ('2099-01-01T00:00:02Z','2100-01-01T00:00:00Z'):
            bad=deepcopy(request);bad.update(report_id=cutoff,analysis_at=cutoff)
            with patch('dis_oracle.pipeline.now_iso',return_value='2099-01-01T00:01:00Z'):
                with self.assertRaises(ValueError):self.c.science(bad)
        with self.assertRaises(JournalError):self.c.science(request,at='2100-01-01T00:00:00Z')

    def test_outcome_correction_rejects_stale_parent_and_removal(self):
        self.resolved()
        first={'report_id':'first','reason':'Original numeric result','numeric_outcomes':[numeric_outcome()]}
        self.c.science(first)
        second=deepcopy(first);second.update(report_id='second',supersedes='first',reason='Source revision')
        second['numeric_outcomes'][0]['fields'][0]=[2,3,4,5]
        self.c.science(second)
        third=deepcopy(first);third.update(report_id='third',supersedes='first',reason='Stale parent')
        with self.assertRaises(ContractError):self.c.science(third)
        with self.assertRaises(ContractError):self.c.science({'report_id':'remove','reason':'Removal without link'})
        third['supersedes']='second'
        self.assertEqual(self.c.science(third)['parent_report_hash'],digest(self.c.science(second)))
        with self.assertRaises(ContractError):self.c.science({'report_id':'other','reason':'Wrong parent','supersedes':'foreign-event-version'})
        removal={'report_id':'removed','reason':'Withdraw unverified numeric outcome','supersedes':'third','numeric_outcomes':[]}
        self.c.science(removal)
        readdition=deepcopy(first);readdition['report_id']='readded'
        with self.assertRaises(ContractError):self.c.science(readdition)
        readdition['supersedes']='removed'
        self.c.science(readdition)

    def test_imported_data_cannot_override_scientific_clock(self):
        # Registration provenance is immutable. Use another event/database for real-clock API checks.
        with tempfile.TemporaryDirectory() as directory:
            m=fixture();m['provenance']='IMPORTED';del m['numeric_study']
            with Cycle(directory,'imported') as c:
                c.start(m);c.review({'claims_by_core':{}});c.freeze()
                with self.assertRaises(ContractError):c.science({'report_id':'x','reason':'No clock override'},at=AFTER)
                with self.assertRaises(ContractError):c.science({'report_id':'future','reason':'No future cutoff','analysis_at':AFTER})

    def test_equal_deadline_review_is_rejected_before_any_write(self):
        card=self.c.status()['cards'][0]
        claim={'claim_id':'at-deadline','type':'FORECAST','text':'Explicit hypothesis', 'source_fragment':card['interpretation'],
               'axis_id':'target','scenario_id':'A','polarity':'SUPPORT','review_status':'ACCEPTED','reviewed_by':'SYNTHETIC',
               'reviewed_at':fixture()['event']['axes'][0]['deadline']}
        before=self.c.journal.verify()
        with self.assertRaises(ContractError):self.c.review({'claims_by_core':{'rune':[claim]}})
        self.assertEqual(self.c.journal.verify(),before)
        self.c.review({'claims_by_core':{}})
