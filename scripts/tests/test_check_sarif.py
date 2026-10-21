import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_sarif', ROOT/'scripts/check_sarif.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class SecurityGateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def report(self, scores, results=None, **changes):
        rules = [{'id': str(index), 'properties': {'security-severity': score}} for index, score in enumerate(scores)]
        run = {'tool': {'driver': {'rules': rules}}, 'results': results if results is not None else [{'ruleId': str(i)} for i in range(len(scores))]}
        run.update(changes)
        (self.root/'python.sarif').write_text(json.dumps({'version': '2.1.0', 'runs': [run]}))

    def test_empty_successful_analysis_passes(self):
        self.report([])
        self.assertEqual(gate.check(self.root), 0)

    def test_high_and_critical_findings_fail_including_exact_boundary(self):
        self.report(['6.9', '7.0', '9.8'])
        self.assertEqual(gate.check(self.root), 2)

    def test_error_level_without_security_score_and_indexed_rule_are_checked(self):
        self.report([None], [{'ruleIndex': 0, 'level': 'error'}])
        self.assertEqual(gate.check(self.root), 1)

    def test_extension_rule_severity_is_checked(self):
        self.report([])
        path = self.root/'python.sarif'
        document = json.loads(path.read_text())
        run = document['runs'][0]
        run['tool']['extensions'] = [{'name': 'query-pack', 'rules': [
            {'id': 'external/high', 'properties': {'security-severity': '8.1'}},
        ]}]
        run['results'] = [{'ruleId': 'external/high'}]
        path.write_text(json.dumps(document))
        self.assertEqual(gate.check(self.root), 1)

    def test_rule_default_error_level_is_checked(self):
        self.report([])
        path = self.root/'python.sarif'
        document = json.loads(path.read_text())
        run = document['runs'][0]
        run['tool']['driver']['rules'] = [{'id': 'error', 'defaultConfiguration': {'level': 'error'}}]
        run['results'] = [{'ruleId': 'error'}]
        path.write_text(json.dumps(document))
        self.assertEqual(gate.check(self.root), 1)

    def test_missing_reports_and_failed_analysis_cannot_pass(self):
        with self.assertRaises(ValueError):
            gate.check(self.root)
        self.report([], invocations=[{'executionSuccessful': False}])
        with self.assertRaises(ValueError):
            gate.check(self.root)

    def test_unknown_rule_and_invalid_score_cannot_pass(self):
        self.report([], [{'ruleId': 'missing'}])
        with self.assertRaises(ValueError):
            gate.check(self.root)
        for score in ['NaN', 'Infinity', '-1', '11', 'invalid']:
            self.report([score])
            with self.subTest(score=score), self.assertRaises(ValueError):
                gate.check(self.root)


if __name__ == '__main__':
    unittest.main()
