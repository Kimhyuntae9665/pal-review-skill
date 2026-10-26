"""Offline focused regression tests: no provider request and no real credentials."""
import argparse
import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pal_review.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("pal_review", SCRIPT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

QUALITY = {"id": "anthropic/reviewer", "family": "anthropic", "paid": True}
FREE = {"id": "qwen/reviewer:free", "family": "qwen", "paid": False}
GEMINI = {"id": "gemini-3.8-flash", "family": "google", "provider": "gemini", "key_env": "GEMINI_API_KEY", "paid": False}
GROQ = {"id": "qwen/qwen3.8-27b", "family": "qwen", "provider": "groq", "key_env": "GROQ_API_KEY", "paid": False}
GOOD = {"verdict": "no_material_issue", "summary": "No material issue in supplied text.", "findings": [], "limitations": ["Not executed."]}


def response(review=GOOD, model=QUALITY["id"], provider="openrouter", status="success"):
    return {"isError": False, "content": [{"type": "text", "text": json.dumps({"status": status,
        "content": json.dumps(review), "metadata": {"model_used": model, "provider_used": provider,
            "provider_reported_model": model, "finish_reason": "stop"}})}]}


class ReviewTests(unittest.TestCase):
    def test_v3_assessment_wire_derives_verdict_and_retains_evidence(self):
        finding = {'severity': 'medium', 'title': 'T', 'location': 'L', 'evidence': 'E',
                   'consequence': 'C', 'suggested_check': 'S'}
        for assessment, findings, expected in [('reviewed', [], 'no_material_issue'),
                                              ('reviewed', [finding], 'issues'),
                                              ('insufficient_evidence', [], 'insufficient_evidence')]:
            wire = {'assessment': assessment, 'summary': 'S', 'findings': findings, 'limitations': []}
            raw = response(wire, GROQ['id'], 'groq')
            envelope = json.loads(raw['content'][0]['text'])
            envelope['metadata']['review_contract'] = {'version': 'review-json-v3', 'json_mode': 'strict_assessment_schema'}
            raw['content'][0]['text'] = json.dumps(envelope)
            status, review, metadata, _ = client.parse_response(raw, GROQ['id'], 'groq')
            self.assertEqual(status, 'review_received')
            self.assertEqual(review['verdict'], expected)
            self.assertEqual(review['findings'], findings)
            self.assertEqual(metadata['provider_assessment'], assessment)

    def test_old_contradictory_verdict_is_still_rejected(self):
        finding = {'severity': 'medium', 'title': 'T', 'location': 'L', 'evidence': 'E',
                   'consequence': 'C', 'suggested_check': 'S'}
        raw = response({**GOOD, 'findings': [finding]})
        self.assertEqual(client.parse_response(raw, QUALITY['id'])[0], 'unstructured_response')

    def test_provider_503_diagnostic_is_preserved(self):
        raw = {'isError': True, 'content': [{'type': 'text', 'text':
            'Error in chat: Custom API error after 1 attempt: Error code: 503 UNAVAILABLE'}]}
        status, review, metadata, reason = client.parse_response(raw, GEMINI['id'], 'gemini')
        self.assertEqual(status, 'provider_error')
        self.assertIsNone(review)
        self.assertEqual(metadata['provider_error']['http_status'], 503)
        self.assertEqual(metadata['provider_error']['category'], 'temporary_unavailable')
        self.assertFalse(metadata['provider_error']['automatic_retry'])
        self.assertIn('503', reason)

    def test_output_policy_scales_with_route_budget(self):
        from review_contract import output_policy, system_prompt
        small = output_policy('groq', 'free', 768)
        normal = output_policy('openrouter', 'free', 4096)
        self.assertEqual(small['max_findings'], 1)
        self.assertEqual(normal['max_findings'], 2)
        self.assertLess(small['target_visible_characters'], normal['target_visible_characters'])
        self.assertIn('at most 1 findings', system_prompt(small))

    def test_one_leading_json_fence_allows_ignored_trailing_advice(self):
        raw = response()
        envelope = json.loads(raw['content'][0]['text'])
        envelope['content'] = '```json\n' + json.dumps(GOOD) + '\n```\nAdditional untrusted prose.'
        raw['content'][0]['text'] = json.dumps(envelope)
        status, review, metadata, _ = client.parse_response(raw, QUALITY['id'])
        self.assertEqual(status, 'review_received')
        self.assertEqual(review, GOOD)
        self.assertTrue(metadata['trailing_commentary_ignored'])
        envelope['content'] += '\n```json\n' + json.dumps(GOOD) + '\n```'
        raw['content'][0]['text'] = json.dumps(envelope)
        self.assertEqual(client.parse_response(raw, QUALITY['id'])[0], 'unstructured_response')

    def test_redaction_covers_untrusted_json_keys(self):
        fake_key = "test-provider-token-value-at-least-twenty"
        with patch.dict(os.environ, {"GEMINI_API_KEY": fake_key}):
            cleaned = client.redact({fake_key: {"value": fake_key}})
        self.assertNotIn(fake_key, json.dumps(cleaned))
        self.assertEqual(cleaned, {"[REDACTED]": {"value": "[REDACTED]"}})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = {"schema_version": 1, "pal_source": str(self.root), "pal_python": os.sys.executable,
            "limits": {"max_input_bytes": 48000, "max_file_bytes": 20000, "max_output_tokens": 3000, "timeout_seconds": 600},
            "profiles": {"quality": [QUALITY.copy()], "free": [FREE.copy()]}}
        self.config_path = self.root / "models.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.brief = self.root / "brief.txt"
        self.brief.write_text("Check correctness and unsupported claims.", encoding="utf-8")
        self.artifact = self.root / "artifact.py"
        self.artifact.write_text("answer = 42\n", encoding="utf-8")
        self.env = patch.dict(os.environ, {"OPENROUTER_API_KEY": "offline-test-key", "GEMINI_API_KEY": "", "GROQ_API_KEY": "",
                                          "PAL_GEMINI_FREE_TIER_CONFIRMED": "", "PAL_GROQ_FREE_TIER_CONFIRMED": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def args(self, **changes):
        args = dict(command="run", config=str(self.config_path), brief=str(self.brief), file=[str(self.artifact)],
            cwd=str(self.root), profile="quality", model=None, allow_paid=True, followup=None, output=str(self.root / "result.json"))
        args.update(changes)
        return argparse.Namespace(**args)

    def catalog(self):
        return {model["id"]: {"id": model["id"], "pricing": {"prompt": "0", "completion": "0"}}
                for model in (QUALITY, FREE)}

    def three_providers(self):
        self.config["profiles"]["free"] = [GEMINI.copy(), GROQ.copy(), FREE.copy()]
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def test_missing_auth_never_fetches_catalog_or_calls_pal(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args())
        self.assertEqual(error.exception.status, "auth_missing")
        catalog.assert_not_called()
        pal.assert_not_called()

    def test_paid_needs_explicit_authorization_before_network(self):
        with patch.object(client, "fetch_catalog") as catalog:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args(allow_paid=False))
        self.assertEqual(error.exception.status, "paid_not_authorized")
        catalog.assert_not_called()

    def test_all_openai_and_gpt_codex_routes_excluded(self):
        for name in ("openai/o3", "vendor/gpt-5", "vendor/codex-9", "vendor/OpenAI-oss"):
            self.assertFalse(client.non_openai({"id": name}))
        config = {**self.config, "profiles": {"quality": [{"id": "openai/o3", "paid": True}], "free": []}}
        with self.assertRaises(client.ReviewError):
            client.candidates(config, "quality")
        with self.assertRaises(client.ReviewError):
            client.candidates(self.config, "quality", "vendor/unlisted")

    def test_free_every_price_must_be_numeric_and_zero(self):
        for pricing in ({"prompt": "0", "completion": "0", "request": "0.001"},
                        {"prompt": "0", "completion": "NaN"}, {"prompt": "0"},
                        {"prompt": "0", "completion": "0", "extra": None}):
            self.assertFalse(client.free_pricing({"pricing": pricing}))
        self.assertTrue(client.free_pricing({"pricing": {"prompt": "0", "completion": "0.000", "request": 0}}))

    def test_catalog_priority_skips_absent_without_guessing(self):
        absent = {**QUALITY, "id": "anthropic/missing"}
        selected, skipped, _ = client.choose_route([absent, QUALITY], self.catalog(), "quality")
        self.assertEqual(selected, QUALITY)
        self.assertEqual(skipped, [{"model": absent["id"], "reason": "not_in_current_catalog"}])
        with self.assertRaises(client.ReviewError):
            client.choose_route([FREE], {FREE["id"]: {"id": FREE["id"], "pricing": {"prompt": "0", "completion": "1"}}}, "free")

    def test_boundaries_secret_files_and_content(self):
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "outside.txt"
            outside.write_text("ordinary text", encoding="utf-8")
            with self.assertRaises(client.ReviewError):
                client.checked_path(outside, self.root)
            link = self.root / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                pass
            else:
                with self.assertRaises(client.ReviewError):
                    client.checked_path(link, self.root)
        for name in (".env", ".env.local", "private.pem", "private.key", "auth.json", "credentials.json"):
            path = self.root / name
            path.write_text("ordinary text", encoding="utf-8")
            with self.assertRaises(client.ReviewError):
                client.read_input(path, self.root, self.config["limits"])
        self.artifact.write_text("-----BEGIN RSA PRIVATE KEY-----", encoding="utf-8")
        with self.assertRaises(client.ReviewError):
            client.read_input(self.artifact, self.root, self.config["limits"])

    def test_input_budgets_fail_without_truncation(self):
        self.artifact.write_text("x" * 20001, encoding="utf-8")
        with self.assertRaises(client.ReviewError) as error:
            client.build_packet(self.args(), self.config)
        self.assertEqual(error.exception.status, "input_too_large")
        self.artifact.write_text("x" * 19000, encoding="utf-8")
        self.config["limits"]["max_input_bytes"] = 19500
        with self.assertRaises(client.ReviewError) as error:
            client.build_packet(self.args(), self.config)
        self.assertEqual(error.exception.status, "input_too_large")

    def test_quoted_json_credentials_and_escaped_names_are_rejected(self):
        examples = (
            '{"password":"synthetic-password-123456789"}',
            '{"api_key":"synthetic-credential-123456789"}',
            '{"access_token":"synthetic-credential-123456789"}',
            '{"client_secret":"synthetic-credential-123456789"}',
            r'{"pass\u0077ord":"synthetic-password-123456789"}',
            r'"{\"api_key\":\"synthetic-credential-123456789\"}"',
        )
        for content in examples:
            with self.subTest(content=content):
                self.artifact.write_text(content, encoding="utf-8")
                with self.assertRaises(client.ReviewError) as error:
                    client.read_input(self.artifact, self.root, self.config["limits"])
                self.assertEqual(error.exception.status, "input_rejected")

    def test_redaction_preserves_json_structure_with_quoted_credentials(self):
        raw = {"content": [{"type": "text", "text": '{"password":"synthetic-password-123456789"}'}]}
        redacted = client.redact(raw)
        self.assertEqual(redacted["content"][0]["type"], "text")
        self.assertNotIn("synthetic-password", json.dumps(redacted))

    def test_hashes_match_exact_utf8_input_and_no_file_paths_sent(self):
        packet, manifest, _, _, _, size = client.build_packet(self.args(), self.config)
        self.assertEqual(manifest[1]["sha256"], client.hashlib.sha256(self.artifact.read_bytes()).hexdigest())
        self.assertNotIn(str(self.root), packet)
        self.assertEqual(size, len(packet.encode("utf-8")))
        self.assertIn("untrusted", packet.lower())

    def test_schema_malformed_is_not_a_no_issue_verdict(self):
        status, review, _, _ = client.parse_response(response({"answer": "looks good"}), QUALITY["id"])
        self.assertEqual(status, "unstructured_response")
        self.assertIsNone(review)
        status, review, _, _ = client.parse_response(response(), QUALITY["id"])
        self.assertEqual(status, "review_received")
        self.assertEqual(review["verdict"], "no_material_issue")
        malformed = {**GOOD, "findings": [{"title": "unsupported"}]}
        self.assertEqual(client.parse_response(response(malformed), QUALITY["id"])[0], "unstructured_response")

    def test_identity_requires_selected_non_openai_openrouter_metadata(self):
        for model, provider in (("openai/o3", "openrouter"), (QUALITY["id"], "openai"), ("anthropic/other", "openrouter")):
            self.assertEqual(client.parse_response(response(model=model, provider=provider), QUALITY["id"])[0], "identity_unverified")
        raw = response()
        envelope = json.loads(raw["content"][0]["text"])
        envelope["metadata"]["provider_reported_model"] = "openai/gpt-5"
        raw["content"][0]["text"] = json.dumps(envelope)
        self.assertEqual(client.parse_response(raw, QUALITY["id"])[0], "identity_unverified")

    def test_reported_identity_missing_or_different_model_is_not_verified(self):
        for reported in (None, "anthropic/other", "other/reviewer", "anthropic/reviewer-successor"):
            raw = response()
            envelope = json.loads(raw["content"][0]["text"])
            envelope["metadata"]["provider_reported_model"] = reported
            raw["content"][0]["text"] = json.dumps(envelope)
            self.assertEqual(client.parse_response(raw, QUALITY["id"])[0], "identity_unverified")
        self.assertTrue(client.same_reported_model("qwen/reviewer:free", "qwen/reviewer"))
        self.assertTrue(client.same_reported_model("anthropic/reviewer", "reviewer"))
        self.assertFalse(client.same_reported_model("anthropic/reviewer", "anthropic/reviewer-2"))

    def test_truncated_or_filtered_json_is_not_a_completed_review(self):
        for finish_reason in ("length", "content_filter"):
            raw = response()
            envelope = json.loads(raw["content"][0]["text"])
            envelope["metadata"]["finish_reason"] = finish_reason
            raw["content"][0]["text"] = json.dumps(envelope)
            status, review, _, _ = client.parse_response(raw, QUALITY["id"])
            self.assertEqual(status, "incomplete_response")
            self.assertIsNone(review)

    def test_run_one_request_and_saves_raw_plus_review(self):
        with patch.object(client, "fetch_catalog", return_value=self.catalog()), patch.object(client, "call_pal", new=AsyncMock(return_value=response())) as pal:
            result, code = client.execute(self.args())
        self.assertEqual(code, 0)
        pal.assert_awaited_once()
        self.assertEqual(result["inference_attempts"], 1)
        self.assertEqual(result["review_summary"]["inference_attempts"], 1)
        self.assertIn("raw_pal", result)
        self.assertEqual(json.loads(Path(self.args().output).read_text(encoding="utf-8")), result)
        self.assertFalse(Path(self.args().output + ".inflight").exists())

    def test_exclusive_output_reservation_blocks_duplicate_inference(self):
        reservation = Path(self.args().output + ".inflight")
        reservation.write_text("another run owns this output", encoding="utf-8")
        with patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args())
        self.assertEqual(error.exception.status, "output_rejected")
        catalog.assert_not_called()
        pal.assert_not_called()

    def test_reservation_race_after_catalog_still_blocks_inference(self):
        def catalog_race():
            Path(self.args().output + ".inflight").write_text("another process won", encoding="utf-8")
            return self.catalog()
        with patch.object(client, "fetch_catalog", side_effect=catalog_race), patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args())
        self.assertEqual(error.exception.status, "output_rejected")
        pal.assert_not_called()

    def test_completed_output_race_before_reservation_blocks_inference(self):
        completed = '{"status":"completed_by_another_run"}'
        def catalog_race():
            Path(self.args().output).write_text(completed, encoding="utf-8")
            return self.catalog()
        with patch.object(client, "fetch_catalog", side_effect=catalog_race), patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args())
        self.assertEqual(error.exception.status, "output_rejected")
        pal.assert_not_called()
        self.assertEqual(Path(self.args().output).read_text(encoding="utf-8"), completed)
        self.assertFalse(Path(self.args().output + ".inflight").exists())

    def test_followup_once_preserves_route_and_original(self):
        with patch.object(client, "fetch_catalog", return_value=self.catalog()), patch.object(client, "call_pal", new=AsyncMock(return_value=response())):
            client.execute(self.args())
            original = Path(self.args().output).read_bytes()
            follow = self.args(followup=self.args().output, output=str(self.root / "follow.json"))
            result, code = client.execute(follow)
            self.assertEqual(code, 0)
            self.assertEqual(result["followup_depth"], 1)
            self.assertEqual(Path(self.args().output).read_bytes(), original)
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args(followup=self.args().output, output=str(self.root / "duplicate.json")))
            self.assertEqual(error.exception.status, "followup_rejected")
            with self.assertRaises(client.ReviewError):
                client.execute(self.args(followup=follow.output, output=str(self.root / "third.json")))

    def test_timeout_marks_remote_ambiguity_and_never_retries(self):
        with patch.object(client, "fetch_catalog", return_value=self.catalog()), patch.object(client, "call_pal", new=AsyncMock(side_effect=TimeoutError)) as pal:
            result, code = client.execute(self.args())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["ambiguous_remote_state"])
        self.assertFalse(result["automatic_retry"])
        pal.assert_awaited_once()
        self.assertTrue(json.loads(Path(self.args().output + ".inflight").read_text(encoding="utf-8"))["ambiguous_remote_state"])

    def test_plan_and_doctor_no_network_or_inference(self):
        with patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            for command in ("plan", "doctor"):
                result, _ = client.execute(self.args(command=command))
                self.assertFalse(result.get("network_called", result.get("checks", {}).get("network_called")))
        catalog.assert_not_called()
        pal.assert_not_called()

    def test_environment_is_sanitized_and_key_is_redacted(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "other-secret", "OPENAI_API_KEY": "another-secret", "PAL_REVIEW_MOCK_URL": "http://bad"}):
            env = client.launcher_env(self.config, QUALITY["id"], profile="quality")
        self.assertNotIn("GOOGLE_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("PAL_REVIEW_MOCK_URL", env)
        self.assertEqual(client.redact({"message": "offline-test-key"}), {"message": "[REDACTED]"})

    def test_main_missing_auth_prints_json_without_secret(self):
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as out:
            code = client.main(["--config", str(self.config_path), "run", "--brief", str(self.brief),
                                "--cwd", str(self.root), "--output", str(self.root / "result.json")])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["status"], "auth_missing")

    def test_default_profile_is_free_and_plan_remains_offline(self):
        self.assertEqual(client.parser().parse_args(["plan"]).profile, "free")
        self.three_providers()
        with patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            result, code = client.execute(self.args(command="plan", profile="free"))
        self.assertEqual(code, 0)
        self.assertEqual([row["id"] for row in result["candidates"]], [GEMINI["id"], GROQ["id"], FREE["id"]])
        catalog.assert_not_called()
        pal.assert_not_called()

    def test_all_missing_keys_records_each_provider_without_network(self):
        self.three_providers()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args(profile="free", allow_paid=False))
        self.assertEqual(error.exception.status, "auth_missing")
        self.assertEqual([row["provider"] for row in error.exception.details["skipped"]], ["gemini", "groq", "openrouter"])
        catalog.assert_not_called()
        pal.assert_not_called()

    def test_direct_free_provider_requires_confirmed_entitlement(self):
        self.three_providers()
        for model, key_env in ((GEMINI, "GEMINI_API_KEY"), (GROQ, "GROQ_API_KEY")):
            with self.subTest(provider=model["provider"]), patch.dict(os.environ, {key_env: "synthetic-direct-key"}), patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
                with self.assertRaises(client.ReviewError) as error:
                    client.execute(self.args(profile="free", model=model["id"], allow_paid=False))
                self.assertEqual(error.exception.status, "free_tier_unconfirmed")
                catalog.assert_not_called()
                pal.assert_not_called()

    def test_gemini_first_ready_route_needs_no_openrouter_catalog(self):
        self.three_providers()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "synthetic-gemini-key", "PAL_GEMINI_FREE_TIER_CONFIRMED": "1"}), patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal", new=AsyncMock(return_value=response(model=GEMINI["id"], provider="gemini"))) as pal:
            result, code = client.execute(self.args(profile="free", allow_paid=False))
        self.assertEqual(code, 0)
        self.assertEqual(result["requested"]["provider"], "gemini")
        self.assertTrue(result["requested"]["free_tier_confirmed"])
        self.assertIsNone(result["catalog_pricing"])
        catalog.assert_not_called()
        pal.assert_awaited_once()

    def test_unconfirmed_first_provider_skips_to_confirmed_groq(self):
        self.three_providers()
        env = {"GEMINI_API_KEY": "synthetic-gemini-key", "GROQ_API_KEY": "synthetic-groq-key", "PAL_GROQ_FREE_TIER_CONFIRMED": "1"}
        with patch.dict(os.environ, env), patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal", new=AsyncMock(return_value=response(model=GROQ["id"], provider="groq"))) as pal:
            result, code = client.execute(self.args(profile="free", allow_paid=False))
        self.assertEqual(code, 0)
        self.assertEqual(result["requested"]["provider"], "groq")
        self.assertIn({"model": GEMINI["id"], "provider": "gemini", "reason": "free_tier_unconfirmed"}, result["skipped"])
        catalog.assert_not_called()
        pal.assert_awaited_once()

    def test_explicit_missing_model_key_never_switches_to_ready_provider(self):
        self.three_providers()
        with patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args(profile="free", model=GEMINI["id"], allow_paid=False))
        self.assertEqual(error.exception.status, "auth_missing")
        self.assertEqual(len(error.exception.details["skipped"]), 1)
        catalog.assert_not_called()
        pal.assert_not_called()

    def test_missing_direct_keys_skip_to_zero_price_openrouter(self):
        self.three_providers()
        with patch.object(client, "fetch_catalog", return_value=self.catalog()) as catalog, patch.object(client, "call_pal", new=AsyncMock(return_value=response(model=FREE["id"]))) as pal:
            result, code = client.execute(self.args(profile="free", allow_paid=False))
        self.assertEqual(code, 0)
        self.assertEqual(result["requested"]["provider"], "openrouter")
        self.assertEqual([row["reason"] for row in result["skipped"]], ["auth_missing", "auth_missing"])
        catalog.assert_called_once()
        pal.assert_awaited_once()

    def test_only_selected_credential_and_confirmation_reach_launcher(self):
        self.three_providers()
        env = {"GEMINI_API_KEY": "synthetic-gemini-key", "GROQ_API_KEY": "synthetic-groq-key",
               "PAL_GEMINI_FREE_TIER_CONFIRMED": "1", "PAL_GROQ_FREE_TIER_CONFIRMED": "1"}
        with patch.dict(os.environ, env):
            child = client.launcher_env(self.config, GROQ["id"], profile="free")
            redacted = client.redact(list(env.values()))
        self.assertEqual(child["PAL_REVIEW_PROVIDER"], "groq")
        self.assertEqual(child["GROQ_API_KEY"], env["GROQ_API_KEY"])
        self.assertEqual(child["PAL_GROQ_FREE_TIER_CONFIRMED"], "1")
        for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "PAL_GEMINI_FREE_TIER_CONFIRMED"):
            self.assertNotIn(name, child)
        self.assertNotIn("synthetic-gemini-key", redacted)
        self.assertNotIn("synthetic-groq-key", redacted)

    def test_provider_metadata_must_match_logical_route(self):
        self.assertEqual(client.parse_response(response(model=GEMINI["id"], provider="gemini"), GEMINI["id"], "gemini")[0], "review_received")
        self.assertEqual(client.parse_response(response(model=GEMINI["id"], provider="custom"), GEMINI["id"], "gemini")[0], "identity_unverified")
        self.assertEqual(client.parse_response(response(model=GROQ["id"], provider="openrouter"), GROQ["id"], "groq")[0], "identity_unverified")

    def test_provider_cannot_select_an_unrelated_credential_variable(self):
        self.three_providers()
        self.config["profiles"]["free"][0]["key_env"] = "OPENAI_API_KEY"
        with self.assertRaises(client.ReviewError) as error:
            client.candidates(self.config, "free")
        self.assertEqual(error.exception.status, "config_invalid")

    def test_direct_provider_key_shapes_are_rejected_from_artifacts(self):
        for content in ("AIza" + "x" * 35, "gsk_" + "x" * 40):
            self.artifact.write_text(content, encoding="utf-8")
            with self.assertRaises(client.ReviewError) as error:
                client.read_input(self.artifact, self.root, self.config["limits"])
            self.assertEqual(error.exception.status, "input_rejected")

    def test_followup_preserves_direct_provider_and_does_not_switch_when_key_lost(self):
        self.three_providers()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "synthetic-gemini-key", "PAL_GEMINI_FREE_TIER_CONFIRMED": "1"}), patch.object(client, "call_pal", new=AsyncMock(return_value=response(model=GEMINI["id"], provider="gemini"))):
            original, _ = client.execute(self.args(profile="free", allow_paid=False))
        self.assertEqual(original["requested"]["provider"], "gemini")
        with patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal") as pal:
            with self.assertRaises(client.ReviewError) as error:
                client.execute(self.args(profile="free", allow_paid=False, followup=self.args().output, output=str(self.root / "follow.json")))
        self.assertEqual(error.exception.status, "auth_missing")
        self.assertEqual(error.exception.details["skipped"][0]["provider"], "gemini")
        catalog.assert_not_called()
        pal.assert_not_called()
        self.assertFalse(Path(self.args().output + ".followup.lock").exists())

    def test_doctor_reports_all_provider_readiness_without_values(self):
        self.three_providers()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "synthetic-gemini-key"}):
            result = client.doctor(self.config)
        self.assertEqual(set(result["providers"]), {"gemini", "groq", "openrouter"})
        self.assertEqual(result["providers"]["gemini"]["status"], "free_tier_unconfirmed")
        self.assertEqual(result["providers"]["groq"]["status"], "auth_missing")
        self.assertNotIn("synthetic-gemini-key", json.dumps(result))

    def test_no_other_provider_is_attempted_after_request_starts(self):
        self.three_providers()
        env = {"GEMINI_API_KEY": "synthetic-gemini-key", "GROQ_API_KEY": "synthetic-groq-key",
               "PAL_GEMINI_FREE_TIER_CONFIRMED": "1", "PAL_GROQ_FREE_TIER_CONFIRMED": "1"}
        with patch.dict(os.environ, env), patch.object(client, "fetch_catalog") as catalog, patch.object(client, "call_pal", new=AsyncMock(side_effect=TimeoutError)) as pal:
            result, code = client.execute(self.args(profile="free", allow_paid=False))
        self.assertEqual(code, 1)
        self.assertEqual(result["requested"]["provider"], "gemini")
        self.assertTrue(result["ambiguous_remote_state"])
        catalog.assert_not_called()
        pal.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
