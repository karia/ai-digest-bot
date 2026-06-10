# Drop the legacy feeds table from state WITHOUT destroying it, so existing
# deployments keep their data until `make migrate` copies it into sources.
# Delete the table manually after verifying the migration.
removed {
  from = aws_dynamodb_table.feeds

  lifecycle {
    destroy = false
  }
}

resource "aws_dynamodb_table" "sources" {
  name         = "${var.project_name}-sources"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "title"

  attribute {
    name = "title"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
