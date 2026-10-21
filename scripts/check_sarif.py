#!/usr/bin/env python3
"""Fail CI on high-severity security findings or unsuccessful SARIF analysis."""
import argparse
import json
import math
from pathlib import Path
import sys


def check(directory):
    files = sorted(Path(directory).glob('*.sarif'))
    if not files:
        raise ValueError('No SARIF reports were produced.')
    findings = 0
    for path in files:
        document = json.loads(path.read_text())
        runs = document.get('runs')
        if document.get('version') != '2.1.0' or not isinstance(runs, list) or not runs:
            raise ValueError('Expected a complete SARIF 2.1.0 report.')
        for run in runs:
            if any(not invocation.get('executionSuccessful', True) for invocation in run.get('invocations', [])):
                raise ValueError('Code analysis did not finish successfully.')
            tool = run['tool']
            driver = tool['driver']
            components = [driver, *tool.get('extensions', [])]
            rules = {
                rule['id']: rule
                for component in components
                for rule in component.get('rules', [])
            }
            results = run.get('results', [])
            if not isinstance(results, list):
                raise ValueError('Invalid analysis results.')
            for result in results:
                if result.get('kind', 'fail') in ('pass', 'notApplicable'):
                    continue
                rule_id = result.get('ruleId')
                if not rule_id and 'ruleIndex' in result:
                    rule_id = driver['rules'][result['ruleIndex']]['id']
                if rule_id not in rules:
                    raise ValueError(f'A finding references unknown analysis rule {rule_id!r}.')
                rule = rules[rule_id]
                raw_score = rule.get('properties', {}).get('security-severity')
                score = float(raw_score) if raw_score is not None else 0
                if not math.isfinite(score) or not 0 <= score <= 10:
                    raise ValueError('Invalid security severity score.')
                level = result.get('level', rule.get('defaultConfiguration', {}).get('level', 'warning'))
                if score >= 7 or level == 'error':
                    findings += 1
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        count = check(args.directory)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print('FAIL: invalid or incomplete static analysis report: '+str(error), file=sys.stderr)
        return 2
    if count:
        print(f'FAIL: {count} high-severity/error finding(s). See GitHub code scanning.', file=sys.stderr)
        return 1
    print('PASS: no high-severity/error findings in the static analysis reports.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
