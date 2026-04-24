"""Tests for tools/pipeline_tool.py — 3-stage pipeline manifest."""

import json

import pytest

from agents.coder import CODER_SYSTEM_PROMPT, CODER_TOOLS
from agents.hunter import HUNTER_SYSTEM_PROMPT, HUNTER_TOOLS
from agents.tester import TESTER_SYSTEM_PROMPT, TESTER_TOOLS
from tools.pipeline_tool import _handle_get_pipeline_stages
from tools.registry import registry


class TestPipelineManifestValidation:
    def test_empty_task_returns_tool_error(self):
        result = json.loads(_handle_get_pipeline_stages({}))
        assert "error" in result
        assert "task" in result["error"].lower()

    def test_whitespace_only_task_returns_tool_error(self):
        result = json.loads(_handle_get_pipeline_stages({"task": "   \n\t  "}))
        assert "error" in result

    def test_missing_task_key_returns_tool_error(self):
        result = json.loads(_handle_get_pipeline_stages({"other": "value"}))
        assert "error" in result


class TestPipelineManifestShape:
    @pytest.fixture
    def manifest(self):
        task = "Add reverse_str(s: str) -> str to utils.py."
        return json.loads(_handle_get_pipeline_stages({"task": task}))

    def test_top_level_keys(self, manifest):
        assert set(manifest.keys()) >= {
            "pipeline",
            "task",
            "stages",
            "remediation",
            "execution_guide",
        }

    def test_pipeline_label(self, manifest):
        # ASCII-only on purpose: avoids Windows cp1252 print/log surprises
        # when the manifest is rendered outside the MCP UTF-8 transport.
        assert manifest["pipeline"] == "Coder -> Tester -> Hunter"
        assert "→" not in manifest["pipeline"]

    def test_stage3_requires_structured_findings_block(self, manifest):
        # Hunter must emit a fenced JSON findings block so the executor
        # can count HIGH/CRITICAL deterministically instead of prose-parsing.
        ctx = manifest["stages"][2]["context"]
        assert "```json" in ctx
        assert '"findings"' in ctx
        assert '"severity"' in ctx
        assert "CRITICAL|HIGH|MEDIUM|LOW" in ctx
        assert '{"findings": []}' in ctx  # empty-findings sentinel

    def test_task_echoed_verbatim(self, manifest):
        assert manifest["task"] == "Add reverse_str(s: str) -> str to utils.py."

    def test_three_stages_in_order(self, manifest):
        stages = manifest["stages"]
        assert len(stages) == 3
        assert [s["name"] for s in stages] == ["Coder", "Tester", "Hunter"]
        assert [s["stage"] for s in stages] == [1, 2, 3]

    def test_stage_prompts_match_agents(self, manifest):
        coder, tester, hunter = manifest["stages"]
        assert coder["system_prompt"] == CODER_SYSTEM_PROMPT
        assert tester["system_prompt"] == TESTER_SYSTEM_PROMPT
        assert hunter["system_prompt"] == HUNTER_SYSTEM_PROMPT

    def test_stage_tools_match_agents(self, manifest):
        coder, tester, hunter = manifest["stages"]
        assert coder["gabru_tools"] == CODER_TOOLS
        assert tester["gabru_tools"] == TESTER_TOOLS
        assert hunter["gabru_tools"] == HUNTER_TOOLS

    def test_coder_has_no_audit_tools(self, manifest):
        # Role isolation: Coder must not see osv_check / tirith_security.
        coder_tools = manifest["stages"][0]["gabru_tools"]
        assert "osv_check" not in coder_tools
        assert "tirith_security" not in coder_tools

    def test_hunter_cannot_write(self, manifest):
        # Role isolation: Hunter must not see write_file / patch.
        hunter_tools = manifest["stages"][2]["gabru_tools"]
        assert "write_file" not in hunter_tools
        assert "patch" not in hunter_tools

    def test_stage2_context_has_coder_output_placeholder(self, manifest):
        assert "{coder_output}" in manifest["stages"][1]["context"]

    def test_stage3_context_has_both_placeholders(self, manifest):
        ctx = manifest["stages"][2]["context"]
        assert "{coder_output}" in ctx
        assert "{tester_output}" in ctx


class TestRemediationBlock:
    @pytest.fixture
    def remediation(self):
        manifest = json.loads(_handle_get_pipeline_stages({"task": "any task"}))
        return manifest["remediation"]

    def test_has_required_fields(self, remediation):
        assert set(remediation.keys()) >= {
            "context_template",
            "max_loops",
            "loop_trigger_severity",
        }

    def test_max_loops_is_two(self, remediation):
        assert remediation["max_loops"] == 2

    def test_trigger_severity_is_high(self, remediation):
        assert remediation["loop_trigger_severity"] == "HIGH"

    def test_context_template_has_hunter_findings_placeholder(self, remediation):
        assert "{hunter_findings}" in remediation["context_template"]

    def test_context_template_has_task_and_coder_placeholders(self, remediation):
        template = remediation["context_template"]
        assert "{task}" in template
        assert "{coder_output}" in template


class TestExecutionGuide:
    @pytest.fixture
    def guide(self):
        manifest = json.loads(_handle_get_pipeline_stages({"task": "x"}))
        return manifest["execution_guide"]

    def test_mentions_h2_stage_banner(self, guide):
        assert "## Stage N" in guide or "Stage N:" in guide

    def test_mentions_wall_clock_timing(self, guide):
        assert "wall-clock" in guide.lower() or "seconds" in guide.lower()

    def test_mentions_high_severity_loop_trigger(self, guide):
        assert "HIGH" in guide

    def test_guide_tells_executor_to_parse_json_block(self, guide):
        # Executor must parse Hunter's JSON block, not prose-eyeball severity.
        lowered = guide.lower()
        assert "json" in lowered and "parse" in lowered
        assert "CRITICAL" in guide  # both HIGH and CRITICAL trigger the loop

    def test_mentions_halt_on_failure(self, guide):
        assert "halt" in guide.lower() or "HALT" in guide

    def test_mentions_non_code_task_bypass(self, guide):
        lowered = guide.lower()
        assert "read-only" in lowered or "do not call this" in lowered


class TestRegistryIntegration:
    def test_tool_is_registered(self):
        # Ensures AST-scan discovery picked up the module.
        import model_tools  # noqa: F401 — triggers discovery

        schema = registry.get_schema("get_pipeline_stages")
        assert schema is not None
        assert schema["name"] == "get_pipeline_stages"

    def test_tool_belongs_to_pipeline_toolset(self):
        import model_tools  # noqa: F401

        assert registry.get_toolset_for_tool("get_pipeline_stages") == "pipeline"

    def test_required_parameter_is_task(self):
        import model_tools  # noqa: F401

        schema = registry.get_schema("get_pipeline_stages")
        assert schema["parameters"]["required"] == ["task"]
