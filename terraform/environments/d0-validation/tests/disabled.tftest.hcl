mock_provider "aws" {}
run "default_is_disabled" {
  command = plan
  assert {
    condition     = length(module.d0) == 0 && output.runtime == null && output.installation == null
    error_message = "Default root must create no roles/tasks/secrets and export no runtime."
  }
}
