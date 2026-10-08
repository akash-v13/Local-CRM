"""The CDK app: which stacks exist, per stage.

    npx cdk synth -c stage=dev                      # check it builds (no AWS needed)
    npx cdk deploy LocalCrmGithubDeploy-dev -c stage=dev --profile localcrm-dev   # once
    npx cdk deploy LocalCrmRelay-dev -c stage=dev --profile localcrm-dev          # CI does this

The account comes from the AWS profile in use (or GitHub's role in CI); the region is
us-east-1 (CloudFront certificates must live there anyway).
"""

import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from relay_infra.github_deploy import GithubDeployStack
from relay_infra.relay_stack import RelayStack

app = cdk.App()
stage = app.node.try_get_context("stage") or "dev"
if stage not in ("dev", "prod"):
    raise ValueError(f"stage must be dev or prod, not {stage!r}")
github_repo = app.node.try_get_context("github_repo") or "akash-v13/Local-CRM"
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-1")
tags = {"project": "local-crm", "stage": stage}

deploy = GithubDeployStack(
    app, f"LocalCrmGithubDeploy-{stage}", stage=stage, github_repo=github_repo, env=env
)
relay = RelayStack(app, f"LocalCrmRelay-{stage}", stage=stage, env=env)
for stack in (deploy, relay):
    for key, value in tags.items():
        cdk.Tags.of(stack).add(key, value)

# AWS security best-practice checks (cdk-nag) on every synth; findings fail the build.
cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app))
acknowledged: dict[cdk.Stack, dict[str, str]] = {
    relay: {
        "AwsSolutions::AwsSolutions-APIG4": "/health is public on purpose; real routes get "
        "device-token auth.",
        "AwsSolutions::AwsSolutions-APIG1": "Access logging arrives with CloudFront + WAF "
        "(architecture-v1 §5).",
    },
    deploy: {
        "AwsSolutions::AwsSolutions-IAM5[Resource::arn:aws:iam::<AWS::AccountId>:role/"
        "cdk-hnb659fds-*-<AWS::AccountId>-us-east-1]": "Only the CDK bootstrap roles of this "
        "account and region (AWS's recommended GitHub OIDC pattern).",
    },
}
for target, rules in acknowledged.items():
    for rule, reason in rules.items():
        cdk.Validations.of(target).acknowledge(cdk.Acknowledgment(id=rule, reason=reason))

app.synth()
