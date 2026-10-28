import copy
import unittest
from company_x2.quality_office import report


class QualityOfficeTests(unittest.TestCase):
    def test_engineering_evidence_cannot_complete_customer_validation(self):
        result=report()
        self.assertTrue(result['read_only'])
        self.assertFalse(result['release_authority'])
        company=result['projects'][0]
        self.assertEqual(company['verification']['customers']['state'],'pending')
        self.assertFalse(company['validation_complete'])
        self.assertGreater(company['open_issues'],0)
        self.assertEqual(company['issues'][-1]['status'],'resolved')

    def test_missing_evidence_and_duplicate_issues_fail_closed(self):
        baseline=report()
        for kind in ('stage','resolution','duplicate'):
            data=copy.deepcopy(baseline)
            company=data['projects'][0]
            if kind=='stage':company['verification']['code']['evidence']=[]
            elif kind=='resolution':company['issues'][-1]['evidence']=[]
            else:company['issues'].append(copy.deepcopy(company['issues'][0]))
            with self.subTest(kind=kind),self.assertRaises(ValueError):report(data)

    def test_report_does_not_modify_reviewed_input(self):
        data=report();before=copy.deepcopy(data)
        data['projects'][0]['issues'].reverse()
        snapshot=copy.deepcopy(data)
        self.assertEqual(report(data)['projects'][0]['issues'],before['projects'][0]['issues'])
        self.assertEqual(data,snapshot)
