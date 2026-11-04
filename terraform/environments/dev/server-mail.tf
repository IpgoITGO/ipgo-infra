resource "aws_secretsmanager_secret" "server_mail_password" {
  name                    = "/ipgo/dev/server-mail-password"
  description             = "Development Gmail SMTP app password; value is provisioned out of band"
  recovery_window_in_days = 7

  tags = local.common_tags
}
