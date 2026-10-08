"""The role GitHub Actions uses to deploy, in one AWS account. Deployed once, by hand.

GitHub proves who it is with a short-lived OpenID Connect token, so no AWS keys are
ever stored in GitHub. The role trusts only this repository, and only:

- dev:  the `main` branch (merging deploys dev)
- prod: the `prod` GitHub environment (a deploy you approve in GitHub)

All the role can do is hand over to the CDK bootstrap roles (`cdk bootstrap` created
them), which hold the actual deploy permissions. That's the pattern AWS recommends.
"""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
CDK_QUALIFIER = "hnb659fds"  # the default `cdk bootstrap` qualifier


class GithubDeployStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, stage: str, github_repo: str, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        provider = iam.CfnOIDCProvider(
            self,
            "GithubOidc",
            url=GITHUB_OIDC_URL,
            client_id_list=["sts.amazonaws.com"],
        )
        subject = (
            f"repo:{github_repo}:ref:refs/heads/main"
            if stage == "dev"
            else f"repo:{github_repo}:environment:prod"
        )
        role = iam.Role(
            self,
            "DeployRole",
            role_name=f"local-crm-github-deploy-{stage}",
            description=f"GitHub Actions deploys the Local CRM relay ({stage}).",
            assumed_by=iam.FederatedPrincipal(
                provider.attr_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {"token.actions.githubusercontent.com:sub": subject},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::{self.account}:role/cdk-{CDK_QUALIFIER}-*-{self.account}-{self.region}"
                ],
            )
        )
        CfnOutput(self, "DeployRoleArn", value=role.role_arn)
