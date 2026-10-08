"""The relay itself. For now a walking skeleton: one `/health` endpoint, deployed the way
every later piece will be (Lambda on arm64, an HTTP API, logs kept 30 days, a cap on
concurrency so a bug or an attack can't run up a bill).

Next pieces (docs/dev/architecture-v1.md §5): intake, pickup and acknowledge with
DynamoDB and S3, then SES acknowledgements, then the AI proxy, then CloudFront + WAF.
"""

from pathlib import Path

from aws_cdk import Acknowledgment, CfnOutput, Duration, Stack, Validations
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

HANDLERS = Path(__file__).resolve().parents[1] / "handlers"


class RelayStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, stage: str, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        health_logs = logs.LogGroup(
            self,
            "HealthLogs",
            log_group_name=f"/local-crm/relay/{stage}/health",
            retention=logs.RetentionDays.ONE_MONTH,
        )
        # Least privilege: write to its own log group, nothing else (instead of the broader
        # AWS-managed AWSLambdaBasicExecutionRole).
        health_role = iam.Role(
            self, "HealthRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )
        health_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[health_logs.log_group_arn, f"{health_logs.log_group_arn}:*"],
            )
        )
        log_group_id = self.get_logical_id(health_logs.node.default_child)  # type: ignore[arg-type]
        Validations.of(health_role).acknowledge(
            Acknowledgment(
                id=f"AwsSolutions::AwsSolutions-IAM5[Resource::<{log_group_id}.Arn>:*]",
                reason="Log streams inside the function's own log group only.",
            )
        )
        health = lambda_.Function(
            self,
            "Health",
            function_name=f"local-crm-relay-health-{stage}",
            role=health_role,
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,  # Graviton: cheaper per request
            handler="health.handler",
            code=lambda_.Code.from_asset(str(HANDLERS)),
            memory_size=128,
            timeout=Duration.seconds(5),
            reserved_concurrent_executions=5,  # cost guardrail
            environment={"STAGE": stage},
            log_group=health_logs,
        )
        api = apigw.HttpApi(
            self,
            "Api",
            api_name=f"local-crm-relay-{stage}",
            description="Local CRM relay: intake, pickup, AI proxy (docs/dev/architecture-v1.md).",
        )
        api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("HealthIntegration", health),
        )
        # Throttle the whole API (requests per second / burst) until per-route limits exist.
        default_stage = api.default_stage.node.default_child  # type: ignore[union-attr]
        default_stage.add_property_override("DefaultRouteSettings.ThrottlingRateLimit", 20)  # type: ignore[union-attr]
        default_stage.add_property_override("DefaultRouteSettings.ThrottlingBurstLimit", 40)  # type: ignore[union-attr]
        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
