mock_provider "aws" {}
mock_provider "archive" {}
run "no_resources_by_default" {
  command = plan
  assert {
    condition     = length(module.rds_offhours) == 0
    error_message = "기본 구성은 새 AWS 자원도 생성하지 않아야 합니다."
  }
}
