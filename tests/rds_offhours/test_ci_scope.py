import importlib.util
import unittest
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ci_scope', ROOT/'scripts/ci-terraform-scope.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ScopeTests(unittest.TestCase):
    def test_isolated_rds_and_check_only_do_not_read_legacy_aws(self):
        self.assertFalse(module.needs_legacy_dev([
            'terraform/environments/rds-offhours/main.tf', 'terraform/modules/rds-offhours/main.tf',
            '.github/workflows/terraform-check.yml', '.github/workflows/terraform-plan.yml',
            'scripts/ci-terraform-scope.py', 'tests/rds_offhours/test_ci_scope.py']))

    def test_shared_or_legacy_tf_always_requires_real_plan(self):
        for path in ['terraform/environments/dev/main.tf', 'terraform/modules/database/main.tf',
                     'terraform/bootstrap/main.tf', 'terraform/modules/rds-offhours-other/main.tf',
                     '.github/workflows/terraform-apply.yml']:
            with self.subTest(path=path):
                self.assertTrue(module.needs_legacy_dev([path]))

    def test_rename_out_of_legacy_keeps_deleted_source_in_scope(self):
        self.assertTrue(module.needs_legacy_dev(['terraform/modules/database/main.tf',
                                               'terraform/modules/rds-offhours/moved.tf']))

    def test_manual_dispatch_keeps_full_aws_plan(self):
        self.assertTrue(module.needs_legacy_dev([], manual=True))

    def test_base_advancement_does_not_add_another_pr_changes(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=folder, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.email', 'ci@example.invalid')
            git('config', 'user.name', 'Local CI fixture')
            (folder/'README').write_text('base')
            git('add', '.'); git('commit', '-qm', 'base')
            git('checkout', '-qb', 'rds')
            rds = folder/'terraform/modules/rds-offhours/main.tf';rds.parent.mkdir(parents=True)
            rds.write_text('# isolated')
            git('add', '.');git('commit', '-qm', 'rds')
            head = git('rev-parse', 'HEAD')
            git('checkout', '-q', 'main')
            dev = folder/'terraform/environments/dev/main.tf';dev.parent.mkdir(parents=True)
            dev.write_text('# another PR')
            git('add', '.');git('commit', '-qm', 'base advance')
            paths = module.changed_paths(git('rev-parse', 'HEAD'), head, cwd=folder)
            self.assertEqual(paths, ['terraform/modules/rds-offhours/main.tf'])
            self.assertFalse(module.needs_legacy_dev(paths))
