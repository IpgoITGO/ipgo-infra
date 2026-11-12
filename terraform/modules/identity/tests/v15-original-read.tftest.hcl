# All runs are local plans. IAM policy-document data is rendered by the real
# provider; credentials/account/metadata lookups and resource writes are disabled.
provider "aws" {
  region                      = "ap-northeast-2"
  access_key                  = "offline-test-only"
  secret_key                  = "offline-test-only"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

variables {
  name_prefix       = "fixture"
  upload_bucket_arn = "arn:aws:s3:::fixture-uploads"
  jobs_queue_arn    = "arn:aws:sqs:ap-northeast-2:111111111111:fixture-jobs"
  results_queue_arn = "arn:aws:sqs:ap-northeast-2:111111111111:fixture-results"
  ai_secret_arns = [
    "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-ai-db-AbCd12",
    "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-openai-AbCd12",
  ]
  database_bootstrap_secret_arns = [
    "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-master-AbCd12",
    "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-migrator-AbCd12",
    "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-server-db-AbCd12",
    "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-ai-db-AbCd12",
  ]
  database_migrate_secret_arns = ["arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-migrator-AbCd12"]
  database_verify_secret_arns  = ["arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-server-db-AbCd12"]
}

run "no_original_secret_preserves_existing_policy" {
  command = plan

  assert {
    condition = alltrue([
      length(jsondecode(data.aws_iam_policy_document.ai_secrets[0].json).Statement) == 1,
      length(jsondecode(data.aws_iam_policy_document.database_secrets["database-bootstrap"].json).Statement) == 1,
      toset(flatten([jsondecode(data.aws_iam_policy_document.ai_secrets[0].json).Statement[0].Resource])) == toset(var.ai_secret_arns),
      toset(flatten([jsondecode(data.aws_iam_policy_document.database_secrets["database-bootstrap"].json).Statement[0].Resource])) == toset(var.database_bootstrap_secret_arns),
    ])
    error_message = "An unset V15 Secret must leave existing execution read policies unchanged."
  }
}

run "preserves_only_two_approved_v15_statements" {
  command = plan
  variables {
    original_database_secret_arn = "arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:fixture-original-AbCd12"
  }

  assert {
    condition = alltrue([for doc in [data.aws_iam_policy_document.ai_secrets[0].json, data.aws_iam_policy_document.database_secrets["database-bootstrap"].json] :
      length(jsondecode(doc).Statement) == 2 && length([for s in jsondecode(doc).Statement : s
        if try(s.Sid, "") == "V15OriginalDatabaseRead" && s.Effect == "Allow" &&
        toset(flatten([s.Action])) == toset(["secretsmanager:GetSecretValue"]) &&
        toset(flatten([s.Resource])) == toset([var.original_database_secret_arn]) &&
        !contains(keys(s), "Condition")
      ]) == 1
    ])
    error_message = "Both policies must preserve the exact approved Sid/action/Secret ARN without widening access."
  }

  assert {
    condition = alltrue([
      toset(flatten([one([for s in jsondecode(data.aws_iam_policy_document.ai_secrets[0].json).Statement : s if try(s.Sid, "") != "V15OriginalDatabaseRead"]).Resource])) == toset(var.ai_secret_arns),
      toset(flatten([one([for s in jsondecode(data.aws_iam_policy_document.database_secrets["database-bootstrap"].json).Statement : s if try(s.Sid, "") != "V15OriginalDatabaseRead"]).Resource])) == toset(var.database_bootstrap_secret_arns),
    ])
    error_message = "V15 preservation must not change the original base resource allowlists."
  }

  assert {
    condition = alltrue([for key in ["database-migrate", "database-verify"] :
      alltrue([for s in jsondecode(data.aws_iam_policy_document.database_secrets[key].json).Statement :
        try(s.Sid, "") != "V15OriginalDatabaseRead" && !contains(flatten([s.Resource]), var.original_database_secret_arn)
      ])
    ])
    error_message = "Migration and verification execution roles must not gain original-database Secret access."
  }
}
