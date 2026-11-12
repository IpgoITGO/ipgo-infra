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
    def test_isolated_d0_has_no_legacy_aws_plan_but_mixed_change_still_does(self):
        paths=['terraform/environments/d0-validation/main.tf','terraform/modules/d0-validation/main.tf',
               '.github/workflows/d0-infrastructure.yml','.github/workflows/terraform-check.yml']
        self.assertFalse(module.needs_legacy_dev(paths))
        self.assertTrue(module.needs_legacy_dev(paths+['terraform/modules/database/main.tf']))

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

    def test_dependency_input_rejects_nonmanual_and_nonsha_before_git(self):
        for source,event in [('main','workflow_dispatch'),('f'*40,'pull_request'),
                             ('f'*39,'workflow_dispatch'),('f'*40+'\n','workflow_dispatch')]:
            with self.subTest(source=source,event=event), self.assertRaises(ValueError):
                module.prepare_dependency(source,event)

    def test_dependency_only_prepares_reviewed_lockfile_and_rejects_stale_or_code_changes(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            def git(*args):
                return subprocess.check_output(['git',*args],cwd=folder,stderr=subprocess.DEVNULL).decode().strip()
            git('init','-q','-b','main')
            git('config','user.email','ci@example.invalid');git('config','user.name','Local fixture')
            lock=folder/module.DEV_LOCKFILE;lock.parent.mkdir(parents=True)
            lock.write_text('original lock')
            main=lock.with_name('main.tf');main.write_text('# base')
            git('add','.');git('commit','-qm','base')
            base=git('rev-parse','HEAD');git('update-ref','refs/remotes/origin/dev',base)
            git('checkout','-qb','dependency')
            lock.write_text('reviewed lock');git('commit','-qam','lock only')
            source=git('rev-parse','HEAD')
            git('checkout','-q','main')
            module.prepare_dependency(source,'workflow_dispatch',folder)
            self.assertEqual(lock.read_text(),'reviewed lock')
            self.assertEqual(main.read_text(),'# base')
            git('restore',module.DEV_LOCKFILE)
            main.write_text('# updated dev');git('commit','-qam','dev advance')
            git('update-ref','refs/remotes/origin/dev',git('rev-parse','HEAD'))
            with self.assertRaisesRegex(ValueError,'current_dev_terraform'):
                module.prepare_dependency(source,'workflow_dispatch',folder)
            git('update-ref','refs/remotes/origin/dev',base)
            with self.assertRaisesRegex(ValueError,'dev_terraform_baseline'):
                module.prepare_dependency(source,'workflow_dispatch',folder)
            git('checkout','-q','dependency')
            (folder/'untrusted.py').write_text('raise RuntimeError("must not run")')
            git('add','.');git('commit','-qm','untrusted code')
            code_source=git('rev-parse','HEAD')
            git('checkout','-q','main')
            with self.assertRaisesRegex(ValueError,'only_dev_lockfile'):
                module.prepare_dependency(code_source,'workflow_dispatch',folder)

    def test_workflow_prepares_source_before_credentials_without_changing_permission_boundary(self):
        text=(ROOT/'.github/workflows/terraform-plan.yml').read_text()
        plan=text.split('  plan:',1)[1]
        self.assertLess(plan.index('run: python3 scripts/ci-terraform-scope.py'),plan.index('uses: aws-actions/configure-aws-credentials'))
        self.assertIn('environment: dev-plan',plan)
        self.assertNotIn('pull_request_target:',text)
        self.assertIn('github.event.pull_request.number || inputs.dependency_sha || github.ref',text)
        self.assertEqual(text.count('id-token: write'),1)

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
