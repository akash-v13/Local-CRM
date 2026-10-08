# Local CRM relay (AWS)

The thin cloud piece of Local CRM v1 ([docs/dev/architecture-v1.md](../docs/dev/architecture-v1.md)): it takes in webform messages while the owner's laptop is closed, acknowledges them, and later proxies AI calls. Everything here is **infrastructure as code** (AWS CDK in Python). Nothing is created by clicking in the console.

**Today it's a walking skeleton:** one `GET /health` endpoint, deployed exactly the way every later piece will be. Next: intake, pickup and acknowledge (DynamoDB, S3), SES acknowledgements, the AI proxy, then CloudFront + WAF.

## What's here

| Path | What |
|---|---|
| `app.py` | The CDK app: two stacks per stage (`dev`, `prod`), tags, and AWS security checks (cdk-nag) that fail the build on any finding that hasn't been acknowledged with a reason |
| `relay_infra/github_deploy.py` | `LocalCrmGithubDeploy-<stage>`: the role GitHub Actions deploys with (OIDC, no stored keys). Deployed **once, by hand** |
| `relay_infra/relay_stack.py` | `LocalCrmRelay-<stage>`: the relay. Lambda on arm64 with Python 3.14, its own minimal role, logs kept 30 days, at most 5 at once; HTTP API throttled to 20 req/s |
| `handlers/` | Lambda code (`health.py`) |
| `tests/` | Checks on the synthesized templates and handlers (no AWS account needed) |
| `../.github/workflows/relay.yml` | PR: lint, types, tests, synth. Merge to main: deploy dev. By hand with approval: deploy prod |

## Commands

```bash
cd relay
uv sync                                    # Python deps (CDK, cdk-nag)
uv run pytest -q                           # tests
npx aws-cdk@2 synth -c stage=dev -q        # build the templates + security checks (no AWS needed)
npx aws-cdk@2 diff LocalCrmRelay-dev -c stage=dev --profile localcrm-dev   # what a deploy would change
```

## One-time setup (the founder does this, once per account)

You need: the dev and prod account IDs, and your IAM Identity Center sign-in URL.

**1. Install the AWS CLI and sign in with single sign-on**

```bash
brew install awscli
aws configure sso          # profile name: localcrm-dev  (pick the dev account, AdministratorAccess)
aws configure sso          # profile name: localcrm-prod (pick the prod account)
aws sts get-caller-identity --profile localcrm-dev    # shows the dev account id
```

Later sessions: `aws sso login --profile localcrm-dev`.

**2. Bootstrap CDK in both accounts** (creates the CDK deploy roles and an assets bucket)

```bash
cd relay
npx aws-cdk@2 bootstrap aws://<DEV_ACCOUNT_ID>/us-east-1  --profile localcrm-dev
npx aws-cdk@2 bootstrap aws://<PROD_ACCOUNT_ID>/us-east-1 --profile localcrm-prod
```

**3. Create the GitHub deploy role in each account**

```bash
npx aws-cdk@2 deploy LocalCrmGithubDeploy-dev  -c stage=dev  --profile localcrm-dev
npx aws-cdk@2 deploy LocalCrmGithubDeploy-prod -c stage=prod --profile localcrm-prod
```

Each prints `DeployRoleArn = arn:aws:iam::<account>:role/local-crm-github-deploy-<stage>`. The dev role trusts only this repository's `main` branch; the prod role only its `prod` GitHub environment.

**4. Tell GitHub** (repository → Settings)

- **Secrets and variables → Actions → Variables:** `AWS_DEV_ROLE_ARN` and `AWS_PROD_ROLE_ARN` = the two ARNs. They're variables, not secrets: an ARN isn't sensitive, and without the matching GitHub token it's useless.
- **Environments → New environment `prod`:** add yourself as a **required reviewer** and allow only the `main` branch.

**5. First deploy of dev**

Merge a change under `relay/` (or this PR) and the **Relay** workflow deploys `LocalCrmRelay-dev`. To deploy by hand instead:

```bash
npx aws-cdk@2 deploy LocalCrmRelay-dev -c stage=dev --profile localcrm-dev
curl "$(aws cloudformation describe-stacks --stack-name LocalCrmRelay-dev --profile localcrm-dev \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)/health"
# {"status": "ok", "stage": "dev"}
```

**6. Prod**, when there's something worth releasing: Actions → **Relay** → **Run workflow** on `main`, then approve it.

## Rules

- **Never change relay resources in the console.** Change the code; the next deploy would undo hand-made changes anyway.
- **Acknowledge a cdk-nag finding only with a reason**, in the narrowest place (the construct, not the app).
- **Every Lambda gets** its own role with only what it needs, a log group with retention, and reserved concurrency (a cost cap).
- **No secrets in code or in GitHub.** AI provider keys go in SSM Parameter Store / Secrets Manager, read at run time.
