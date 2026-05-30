variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "ap-northeast-1"
}

variable "project_name" {
  description = "Project name used as a prefix for resource names"
  type        = string
  default     = "aws-blog-digest"
}

variable "bedrock_model_id" {
  description = "Amazon Bedrock model ID for the digest agent"
  type        = string
  default     = "anthropic.claude-sonnet-4-20250514-v1:0"
}
