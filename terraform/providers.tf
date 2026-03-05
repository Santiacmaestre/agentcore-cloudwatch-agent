#######################################################################
# File: providers.tf
#
# Description:
#   Declares the Terraform version constraint and configures the AWS
#   provider with the deployment region. No backend is configured;
#   state is stored locally for this proof-of-concept.
#
# Notes:
#   - AWS provider >= 6.17.0 is required for the
#     aws_bedrockagentcore_agent_runtime resource type.
#######################################################################

# Pins Terraform and provider versions to ensure reproducible applies
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.17.0"
    }
  }
}

# Targets all resources to the region defined by the region variable
provider "aws" {
  region = var.region
}