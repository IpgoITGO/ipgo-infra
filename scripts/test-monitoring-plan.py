"""Safety cases for accidental deployments, replacements and hidden setting changes."""
import copy
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("guard", pathlib.Path(__file__).with_name("check-monitoring-plan.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
settings_spec = importlib.util.spec_from_file_location('monitoring_inputs', pathlib.Path(__file__).with_name('configure-monitoring.py'))
monitoring_inputs = importlib.util.module_from_spec(settings_spec)
settings_spec.loader.exec_module(monitoring_inputs)


class MonitoringInputTests(unittest.TestCase):
    def test_dependabot_missing_secret_fails_with_manual_route_without_fallback(self):
        with self.assertRaisesRegex(ValueError, 'reviewed lockfile-only manual plan'):
            monitoring_inputs.settings({'DEV_MONITORING_ENABLED':'true','GITHUB_ACTOR':'dependabot[bot]'})

    def test_missing_secret_for_normal_actor_still_fails(self):
        with self.assertRaisesRegex(ValueError, 'private AWS_ALERT_EMAIL'):
            monitoring_inputs.settings({'DEV_MONITORING_ENABLED':'true'})

    def test_valid_private_input_preserves_monitoring_for_both_actors(self):
        for actor in ['dependabot[bot]','reviewer']:
            result=monitoring_inputs.settings({'DEV_MONITORING_ENABLED':'true','GITHUB_ACTOR':actor,'ALERT_EMAIL':'fixture@example.invalid'})
            self.assertEqual(result['TF_VAR_enable_dev_monitoring'],'true')
            self.assertEqual(result['TF_VAR_alert_email'],'fixture@example.invalid')


def resource(address, actions, before=None, after=None):
    return {"address": address, "mode": "managed", "change": {"actions": actions, "before": before, "after": after}}


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.cluster = resource("module.compute.aws_ecs_cluster.this", ["update"],
                                {"name": "ipgo-dev-cluster", "setting": [{"name": "containerInsights", "value": "enhanced"}]},
                                {"name": "ipgo-dev-cluster", "setting": [{"name": "containerInsights", "value": "disabled"}]})

    def reject(self, change):
        with self.assertRaises(ValueError):
            guard.validate({"resource_changes": [change]})

    def test_approved_transition(self):
        guard.validate({"resource_changes": [self.cluster] + [resource(a, ["create"]) for a in guard.CREATES]})

    def test_task_deployment_rejected(self):
        self.reject(resource("module.compute.aws_ecs_service.server", ["update"]))

    def test_task_definition_creation_rejected(self):
        self.reject(resource("module.compute.aws_ecs_task_definition.server", ["create"]))

    def test_alarm_delete_rejected(self):
        self.reject(resource(next(iter(guard.CREATES)), ["delete"]))

    def test_alarm_replace_rejected(self):
        self.reject(resource(next(iter(guard.CREATES)), ["delete", "create"]))

    def test_unapproved_alarm_rejected(self):
        self.reject(resource('module.monitoring[0].aws_cloudwatch_metric_alarm.health["unexpected"]', ["create"]))

    def test_cluster_replacement_rejected(self):
        r = copy.deepcopy(self.cluster)
        r["change"]["actions"] = ["delete", "create"]
        self.reject(r)

    def test_other_cluster_changes_rejected(self):
        r = copy.deepcopy(self.cluster)
        r["change"]["after"]["name"] = "other-cluster"
        self.reject(r)

    def test_other_insights_mode_rejected(self):
        r = copy.deepcopy(self.cluster)
        r["change"]["after"]["setting"][0]["value"] = "enabled"
        self.reject(r)

    def test_unrelated_resources_rejected(self):
        for a in ["module.database.aws_db_instance.this", "module.compute.aws_lb_listener.https[0]", "module.identity.aws_iam_role.server_task"]:
            with self.subTest(address=a):
                self.reject(resource(a, ["update"]))


if __name__ == "__main__":
    unittest.main()
