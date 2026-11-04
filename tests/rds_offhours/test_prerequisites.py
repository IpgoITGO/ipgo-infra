import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prerequisites', ROOT/'scripts/prepare-rds-prerequisites.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrerequisiteTests(unittest.TestCase):
    def fixture(self, folder, seconds=86400):
        state = folder/'stability.json'
        state.write_text(json.dumps({'status': 'complete', 'credited_seconds': seconds,
            'llm_enabled': False, 'issues': [], 'server_sha': 'server', 'ai_sha': 'ai'}))
        for phase in ('hold', 'resume'):
            p = folder/phase
            p.mkdir()
            (p/'state.json').write_text(json.dumps({'status': 'scheduled', 'phase': phase}))
        return state

    def test_scheduled_files_and_partial_seconds_do_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            state = self.fixture(p, seconds=86399)
            result = module.summarize(state, p)
            self.assertFalse(result['stability_complete'])
            self.assertFalse(result['night_test_passed'])
            self.assertFalse(result['night_cleanup_verified'])
            self.assertFalse(result['apply_approved'])
            self.assertFalse(result['stop_enabled'])

    def test_state_passed_without_verification_cannot_complete(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            state = self.fixture(p)
            (p/'hold/state.json').write_text(json.dumps({'status': 'passed', 'phase': 'hold'}))
            with self.assertRaises(FileNotFoundError):
                module.summarize(state, p)
