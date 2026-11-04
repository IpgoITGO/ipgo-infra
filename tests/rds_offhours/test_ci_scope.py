import importlib.util
import unittest
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
                     'terraform/bootstrap/main.tf', 'terraform/modules/rds-offhours-other/main.tf']:
            with self.subTest(path=path):
                self.assertTrue(module.needs_legacy_dev([path]))

    def test_rename_out_of_legacy_keeps_deleted_source_in_scope(self):
        self.assertTrue(module.needs_legacy_dev(['terraform/modules/database/main.tf',
                                               'terraform/modules/rds-offhours/moved.tf']))

    def test_manual_dispatch_keeps_full_aws_plan(self):
        self.assertTrue(module.needs_legacy_dev([], manual=True))
