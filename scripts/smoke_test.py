"""Connectivity check for the Anthropic SDK.

Not part of Quack itself — this just proves the SDK, the credentials, and the
network path all work before we build anything on top of them.

    python smoke_test.py
"""

import os
import sys

import anthropic
from dotenv import load_dotenv

MODEL = "claude-opus-5-5"

# Windows consoles default to cp1252, which mangles emoji in model output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()


def build_client() -> anthropic.Anthropic:
    """Create the client, pinning a workspace if one is configured.

    Identity-linked API keys must state which workspace each request acts in.
    The SDK only sends this header automatically on the Bedrock and
    workload-identity paths, so for a plain API key we set it ourselves.
    """
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        return anthropic.Anthropic(
            default_headers={"anthropic-workspace-id": workspace_id}
        )
    return anthropic.Anthropic()


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.\n")
        print("  1. Get a key: https://console.anthropic.com/settings/keys")
        print("  2. cp .env.example .env")
        print("  3. Put the key in .env as ANTHROPIC_API_KEY=sk-ant-...")
        return 1

    client = build_client()

    print(f"Calling {MODEL} ...\n")
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system="You are Quack. Keep replies to a single short sentence.",
        messages=[
            {
                "role": "user",
                "content": "Say hello and confirm you are reachable.",
            }
        ],
    )

    # stop_details is only populated when the model declines a request.
    if response.stop_reason == "refusal":
        print(f"Model refused: {response.stop_details}")
        return 1

    # content is a list of typed blocks -- always check .type before .text.
    for block in response.content:
        if block.type == "text":
            print(block.text)

    usage = response.usage
    print(
        f"\nOK  model={response.model}  "
        f"in={usage.input_tokens} out={usage.output_tokens} "
        f"stop={response.stop_reason}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except anthropic.AuthenticationError:
        print("Auth failed - the API key was rejected. Check ANTHROPIC_API_KEY in .env.")
        sys.exit(1)
    except anthropic.RateLimitError:
        print("Rate limited. Wait a moment and retry.")
        sys.exit(1)
    except anthropic.APIStatusError as err:
        print(f"API error {err.status_code}: {err.message}")
        if "anthropic-workspace-id" in str(err.message):
            print(
                "\nThis key is identity-linked and must name a workspace.\n"
                "Add ANTHROPIC_WORKSPACE_ID=wrkspc_... to .env.\n"
                "Find it at https://console.anthropic.com/settings/workspaces "
                "- open the workspace and copy the id from the URL."
            )
        sys.exit(1)
    except anthropic.APIConnectionError as err:
        print(f"Could not reach the API: {err}")
        sys.exit(1)
