from infra.observability import scrub, tag_alpha, _MAX_STR_LEN, _MAX_COLLECTION


def test_redacts_api_key_at_top_level():
    result = scrub({"api_key": "sk-abc", "model": "claude"})
    assert result["api_key"] == "[REDACTED]"
    assert result["model"] == "claude"


def test_redacts_authorization_nested():
    result = scrub({"config": {"authorization": "Bearer xyz", "timeout": 30}})
    assert result["config"]["authorization"] == "[REDACTED]"
    assert result["config"]["timeout"] == 30


def test_redacts_token_inside_list():
    result = scrub([{"token": "s3cr3t", "name": "tool1"}])
    assert result[0]["token"] == "[REDACTED]"
    assert result[0]["name"] == "tool1"


def test_truncates_long_string():
    long_str = "x" * (_MAX_STR_LEN + 100)
    result = scrub(long_str)
    assert isinstance(result, str)
    assert len(result) < len(long_str)
    assert "chars" in result


def test_truncates_large_dict():
    big = {str(i): i for i in range(_MAX_COLLECTION + 10)}
    result = scrub(big)
    assert result.get("__truncated__") is True
    assert len(result) <= _MAX_COLLECTION + 1


def test_truncates_large_list():
    big = list(range(_MAX_COLLECTION + 10))
    result = scrub(big)
    assert "[truncated]" in result
    assert len(result) <= _MAX_COLLECTION + 1


def test_preserves_normal_metadata():
    meta = {"session_id": "s_abc", "job_id": "j_xyz", "depth": 2,
            "model": "claude-sonnet-4-6", "goal": "Research ML trends"}
    assert scrub(meta) == meta


def test_handles_excessive_nesting_without_recursion_error():
    nested = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "deep"}}}}}}}}}
    assert isinstance(scrub(nested), dict)


def test_tag_alpha_sets_prefixed_keys_and_skips_none():
    recorded: dict[str, str] = {}

    class FakeSpan:
        def set_tag(self, k, v):
            recorded[k] = v

    tag_alpha(FakeSpan(), session_id="s_1", job_id="j_1", depth=0,
              parent_job_id=None, model="claude-sonnet-4-6", tool="dispatch")
    assert recorded["alpha.session_id"] == "s_1"
    assert recorded["alpha.job_id"] == "j_1"
    assert recorded["alpha.depth"] == "0"
    assert recorded["ai.model"] == "claude-sonnet-4-6"
    assert recorded["ai.tool.name"] == "dispatch"
    assert "alpha.parent_job_id" not in recorded  # None skipped
