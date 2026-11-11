import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location('guard', pathlib.Path(__file__).with_name('check-billing-test-plan.py'))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def resource(address, actions, before=None, after=None, unknown=None):
    return dict(address=address, mode='managed', change=dict(actions=actions, before=before, after=after, after_unknown=unknown))


class BillingPlanTests(unittest.TestCase):
    def test_dedicated_container_and_computed_policy_are_allowed(self):
        guard.validate({'resource_changes': [resource(guard.SECRET, ['create'], after=dict(name='/ipgo/dev/server-billing-test', recovery_window_in_days=30)), resource(guard.POLICY, ['update'], before=dict(role='ipgo-dev-server-execution', name='secrets', policy='old'), after=dict(role='ipgo-dev-server-execution', name='secrets'), unknown=dict(policy=True))]})

    def test_other_resources_and_deletion_or_replacement_are_rejected(self):
        for address, actions in [(guard.SECRET, ['delete']), (guard.SECRET, ['delete', 'create']), ('module.identity.aws_iam_role_policy.ai_secrets[0]', ['update']), ('aws_db_instance.main', ['update'])]:
            with self.subTest(address=address, actions=actions), self.assertRaises(ValueError):
                guard.validate({'resource_changes': [resource(address, actions)]})

    def test_live_secret_and_other_role_are_rejected(self):
        for value in [resource(guard.SECRET, ['create'], after=dict(name='/ipgo/prod/billing', recovery_window_in_days=30)), resource(guard.POLICY, ['update'], before=dict(role='ipgo-dev-server-execution'), after=dict(role='ipgo-dev-ai-execution'), unknown=dict(policy=True))]:
            with self.assertRaises(ValueError):
                guard.validate({'resource_changes': [value]})


if __name__ == '__main__':
    unittest.main()
