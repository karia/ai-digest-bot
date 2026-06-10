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
