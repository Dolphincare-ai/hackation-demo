"""AWS Secrets Manager access, ported from dc-backend-pipeline (src/utils/aws_secrets_utils.py).

Reads with the local `dc-test` profile when it exists, otherwise the default boto3 session
(instance role, env credentials). Never log or print a fetched value.
"""
import json

REGION = "us-east-1"
TEST_PROFILE = "dc-test"
OPENAI_SECRET = "credentials/llm/openai"
OPENAI_SECRET_KEY = "api_key"


def get_secret(secret_name: str, key: str | None = None, region: str = REGION,
               profile: str | None = None) -> dict | str | None:
    import boto3  # imported lazily so cache-mode runs and tests do not need it
    if profile and profile in boto3.Session().available_profiles:
        sm = boto3.Session(profile_name=profile).client("secretsmanager", region_name=region)
    else:
        sm = boto3.client("secretsmanager", region_name=region)
    data = json.loads(sm.get_secret_value(SecretId=secret_name)["SecretString"])
    return data.get(key) if key else data


def openai_api_key() -> str | None:
    return get_secret(OPENAI_SECRET, OPENAI_SECRET_KEY, profile=TEST_PROFILE)
