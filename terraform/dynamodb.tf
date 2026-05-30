resource "aws_dynamodb_table" "feeds" {
  name         = "${var.project_name}-feeds"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "feed_url"

  attribute {
    name = "feed_url"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
