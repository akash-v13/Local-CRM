"""What the relay's infrastructure must guarantee, checked on the synthesized templates
(no AWS account needed)."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from handlers.health import handler
from relay_infra.github_deploy import GithubDeployStack
from relay_infra.relay_stack import RelayStack

ENV = cdk.Environment(account="111111111111", region="us-east-1")


@pytest.mark.parametrize(
    ("stage", "subject"),
    [
        ("dev", "repo:akash-v13/Local-CRM:ref:refs/heads/main"),
        ("prod", "repo:akash-v13/Local-CRM:environment:prod"),
    ],
)
def test_deploy_role_trusts_only_this_repo(stage: str, subject: str) -> None:
    app = cdk.App()
    stack = GithubDeployStack(
        app, "Deploy", stage=stage, github_repo="akash-v13/Local-CRM", env=ENV
    )
    t = Template.from_stack(stack)
    t.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": f"local-crm-github-deploy-{stage}",
            "AssumeRolePolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Action": "sts:AssumeRoleWithWebIdentity",
                            "Condition": {
                                "StringEquals": {
                                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                                },
                                "StringLike": {"token.actions.githubusercontent.com:sub": subject},
                            },
                        }
                    )
                ]
            },
        },
    )
    # It can only hand over to the CDK bootstrap roles: no direct permissions.
    t.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Action": "sts:AssumeRole",
                            "Resource": "arn:aws:iam::111111111111:role/"
                            "cdk-hnb659fds-*-111111111111-us-east-1",
                        }
                    )
                ]
            }
        },
    )


def test_relay_lambda_guardrails() -> None:
    app = cdk.App()
    t = Template.from_stack(RelayStack(app, "Relay", stage="dev", env=ENV))
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.14",
            "Architectures": ["arm64"],
            "ReservedConcurrentExecutions": 5,
            "MemorySize": 128,
        },
    )
    t.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 30})
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {"DefaultRouteSettings": {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 40}},
    )
    t.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": "GET /health"})
    # No AWS-managed policies on the function's role.
    for role in t.find_resources("AWS::IAM::Role").values():
        assert "ManagedPolicyArns" not in role["Properties"]


def test_health_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGE", "dev")
    response: dict[str, Any] = handler({}, None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok", "stage": "dev"}
