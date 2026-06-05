variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "ap-northeast-1"
}

variable "project_name" {
  description = "Project name used as a prefix for resource names"
  type        = string
  default     = "karia-ai-digest-bot"
}

variable "bedrock_model_id" {
  description = "Amazon Bedrock inference profile ID for the digest agent (Opus 4.8 requires an inference profile, not on-demand)"
  type        = string
  default     = "jp.anthropic.claude-opus-4-8"
}
