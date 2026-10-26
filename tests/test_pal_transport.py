"""Offline end-to-end tests: actual PAL MCP + provider + SDK, mocked HTTP only.

Run after bootstrap, or set PAL_TEST_CONFIG to a config with a verified external PAL checkout.
No model inference or account credentials.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
ROUTES = {"openrouter": MODEL, "gemini": "gemini-3.8-flash", "groq": "qwen/qwen3.8-27b"}
sys.path.insert(0, str(ROOT / "scripts"))


def serve_fake():
    import httpx
    from pal_server import configure_runtime

    mode = os.environ.get("PAL_TRANSPORT_CASE", "valid")
    record = Path(os.environ["PAL_TRANSPORT_RECORD"])
    selected_model = os.environ["PAL_REVIEW_MODEL"]

    def handler(request):
        body = json.loads(request.read())
        with record.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"model": body["model"], "max_tokens": body["max_tokens"],
                                     "provider": body.get("provider"), "url": str(request.url),
                                     "reasoning_effort": body.get("reasoning_effort"),
                                     "reasoning_format": body.get("reasoning_format"),
                                     "reasoning": body.get("reasoning"),
                                     "response_format": body.get("response_format"),
                                     "messages": body.get("messages"),
                                     "has_tools": bool(body.get("tools")),
                                     "timeout": request.extensions.get("timeout")}) + "\n")
        if mode == "rate_limit":
            return httpx.Response(429, json={"error": {"message": "offline quota fixture", "type": "rate_limit", "code": "rate_limit"}})
        content = "" if mode == "empty" else json.dumps({
            "verdict": "issues", "summary": "Offline transport fixture; no real model reviewed this.",
            "findings": [{"severity": "medium", "title": "Synthetic finding", "location": "example.py:1",
                          "evidence": "Synthetic evidence", "consequence": "Synthetic consequence", "suggested_check": "Run real tests"}],
            "limitations": ["HTTP response is mocked; this does not measure review quality."]})
        if os.environ.get('PAL_REVIEW_PROVIDER') == 'groq' and content:
            wire = json.loads(content)
            content = json.dumps({'assessment': 'reviewed', **{k: v for k, v in wire.items() if k != 'verdict'}})
        return httpx.Response(200, json={
            "id": "offline-transport-fixture", "object": "chat.completion", "created": 1, "model": selected_model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 18, "completion_tokens": 24, "total_tokens": 42},
        })

    runtime, _guard = configure_runtime(transport=httpx.MockTransport(handler))
    runtime.run()


async def mcp_roundtrip(mode, record, provider="openrouter", model=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = dict(os.environ)
    env["PAL_REVIEW_CONFIG_PATH"] = str(Path(os.environ.get("PAL_TEST_CONFIG", ROOT / "references" / "models.json")).resolve())
    model = model or ROUTES[provider]
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY", "CUSTOM_API_KEY", "CUSTOM_API_URL"):
        env.pop(name, None)
    env.update({"OPENROUTER_API_KEY": "offline-not-a-real-key", "PAL_REVIEW_MODEL": MODEL,
                "PAL_REVIEW_PROFILE": "free", "PAL_REVIEW_MAX_OUTPUT_TOKENS": "1024",
                "PAL_TRANSPORT_CASE": mode, "PAL_TRANSPORT_RECORD": str(record),
                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    env.pop("OPENROUTER_API_KEY", None)
    key_env = {"openrouter": "OPENROUTER_API_KEY", "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}[provider]
    env.update({key_env: "offline-not-a-real-key", "PAL_REVIEW_PROVIDER": provider, "PAL_REVIEW_MODEL": model,
                f"PAL_{provider.upper()}_FREE_TIER_CONFIRMED": "1"})
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve()), "--serve"], env=env)
    with open(os.devnull, "w") as errors:
        async with stdio_client(params, errlog=errors) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                assert {x.name for x in listing.tools} == {"chat", "version", "listmodels"}
                result = await session.call_tool("chat", {
                    "model": model, "prompt": "Review this SYNTHETIC fixture only.",
                    "working_directory_absolute_path": str(record.parent), "thinking_mode": "low", "temperature": 0.2,
                })
                return result.model_dump(mode="json")


class RealPalTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        from runtime_config import load_config
        config = load_config(os.environ.get("PAL_TEST_CONFIG", ROOT / "references" / "models.json"))
        if not (Path(config["pal_source"]) / "server.py").is_file() or importlib.util.find_spec("mcp") is None:
            raise unittest.SkipTest("Bootstrap the pinned PAL runtime to run actual-PAL mocked-HTTP integration tests.")

    def roundtrip(self, mode, provider="openrouter", model=None):
        with tempfile.TemporaryDirectory(prefix="pal-offline-") as folder:
            record = Path(folder) / "calls.jsonl"
            result = asyncio.run(asyncio.wait_for(mcp_roundtrip(mode, record, provider, model), timeout=45))
            requests = [json.loads(x) for x in record.read_text(encoding="utf-8").splitlines()]
            return result, requests

    def test_actual_mcp_provider_and_output_cap(self):
        from pal_review import parse_response
        raw, calls = self.roundtrip("valid")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["max_tokens"], 1024)
        self.assertEqual(calls[0]["model"], MODEL)
        self.assertEqual(calls[0]["provider"], {"allow_fallbacks": False})
        self.assertFalse(calls[0]["has_tools"])
        self.assertEqual(calls[0]["timeout"]["read"], 600)
        status, review, metadata, reason = parse_response(raw, MODEL)
        self.assertEqual(status, "review_received", (raw, reason))
        self.assertEqual(metadata["inference_http_requests"], 1)
        self.assertEqual(metadata["provider_reported_model"], MODEL)
        self.assertEqual(metadata["usage"]["total_tokens"], 42)
        self.assertIn("Offline", review["summary"])
        self.assertEqual(metadata['review_contract']['version'], 'review-json-v3')
        messages = calls[0]['messages']
        system = '\n'.join(row['content'] for row in messages if row['role'] == 'system')
        self.assertIn('bounded evidence reviewer', system)
        self.assertNotIn('IF MORE INFORMATION IS NEEDED', system)
        self.assertNotIn('mandatory_instructions', system)
        self.assertNotIn('=== USER REQUEST ===', messages[-1]['content'])
        self.assertIn('RESPONSE CONTRACT REMINDER', messages[-1]['content'])
        self.assertIn('at most 1 findings', messages[-1]['content'])
        self.assertEqual(calls[0]['reasoning'], {'effort': 'low', 'exclude': True})
        # These OpenRouter routes do not list response_format support.
        self.assertIsNone(calls[0]['response_format'])

    def test_cohere_exact_free_route_uses_actual_pal(self):
        from pal_review import parse_response
        model = "cohere/north-mini-code:free"
        raw, calls = self.roundtrip("valid", "openrouter", model)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], model)
        self.assertEqual(calls[0]["max_tokens"], 1024)
        self.assertEqual(calls[0]["provider"], {"allow_fallbacks": False})
        status, _, metadata, reason = parse_response(raw, model, "openrouter")
        self.assertEqual(status, "review_received", (raw, reason))
        self.assertEqual(metadata["provider_reported_model"], model)

    def test_gemini_actual_pal_custom_cloud_adapter(self):
        from pal_review import parse_response
        raw, calls = self.roundtrip("valid", "gemini")
        self.assertEqual(len(calls), 1, raw)
        self.assertEqual(calls[0]["url"], "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.assertEqual(calls[0]["reasoning_effort"], "low")
        self.assertIsNone(calls[0]["provider"])
        self.assertEqual(calls[0]["max_tokens"], 1024)
        status, review, metadata, reason = parse_response(raw, ROUTES["gemini"], "gemini")
        self.assertEqual(status, "review_received", (raw, reason))
        self.assertEqual(metadata["provider_used"], "gemini")

    def test_groq_actual_pal_custom_cloud_adapter(self):
        from pal_review import parse_response
        raw, calls = self.roundtrip("valid", "groq")
        self.assertEqual(len(calls), 1, raw)
        self.assertEqual(calls[0]["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(calls[0]["reasoning_effort"], "none")
        self.assertEqual(calls[0]["max_tokens"], 768)
        self.assertEqual(calls[0]["reasoning_format"], "hidden")
        self.assertIsNone(calls[0]["provider"])
        status, review, metadata, reason = parse_response(raw, ROUTES["groq"], "groq")
        self.assertEqual(status, "review_received", (raw, reason))
        self.assertEqual(metadata["provider_reported_model"], ROUTES["groq"])
        self.assertEqual(metadata["output_token_cap"], 768)
        self.assertEqual(metadata['review_contract']['max_findings'], 1)
        schema = calls[0]['response_format']['json_schema']
        self.assertTrue(schema['strict'])
        self.assertEqual(schema['schema']['required'], ['assessment', 'summary', 'findings', 'limitations'])
        self.assertFalse(schema['schema']['additionalProperties'])

    def test_429_does_not_retry(self):
        raw, calls = self.roundtrip("rate_limit")
        self.assertEqual(len(calls), 1, raw)
        self.assertIn("error", json.dumps(raw).lower())

    def test_empty_response_does_not_send_second_request(self):
        raw, calls = self.roundtrip("empty")
        self.assertEqual(len(calls), 1, raw)
        self.assertIn("error", json.dumps(raw).lower())


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve_fake()
    else:
        unittest.main()
