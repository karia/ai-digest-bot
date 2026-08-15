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

variable "bedrock_model_ids" {
  description = "Amazon Bedrock inference profile IDs the Lambda may invoke (Claude models require an inference profile, not on-demand). Index 0 drives the digest agents, index 1 the advice agent; both are granted."
  type        = list(string)
  default = [
    "global.anthropic.claude-sonnet-5",
    "global.anthropic.claude-fable-5",
  ]
}
