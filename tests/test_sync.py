"""Tests for sync module — merge logic, security filtering."""

from __future__ import annotations

import json


from entirecontext.sync.merge import merge_manifests, merge_transcripts, merge_checkpoint_files
from entirecontext.sync.security import filter_export_data, get_security_config


class TestMergeManifests:
    def test_merge_empty(self):
        result = merge_manifests(
            {"version": 1, "checkpoints": {}, "sessions": {}},
            {"version": 1, "checkpoints": {}, "sessions": {}},
        )
        assert result["version"] == 1
        assert result["checkpoints"] == {}
        assert result["sessions"] == {}

    def test_merge_union_checkpoints(self):
        local = {
            "version": 1,
            "checkpoints": {"cp1": {"commit_hash": "aaa"}},
            "sessions": {},
        }
        remote = {
            "version": 1,
            "checkpoints": {"cp2": {"commit_hash": "bbb"}},
            "sessions": {},
        }
        result = merge_manifests(local, remote)
        assert "cp1" in result["checkpoints"]
        assert "cp2" in result["checkpoints"]

    def test_merge_session_takes_higher_turn_count(self):
        local = {
            "version": 1,
            "checkpoints": {},
            "sessions": {"s1": {"total_turns": 5}},
        }
        remote = {
            "version": 1,
            "checkpoints": {},
            "sessions": {"s1": {"total_turns": 10}},
        }
        result = merge_manifests(local, remote)
        assert result["sessions"]["s1"]["total_turns"] == 10

    def test_merge_version_takes_max(self):
        local = {"version": 1, "checkpoints": {}, "sessions": {}}
        remote = {"version": 2, "checkpoints": {}, "sessions": {}}
        result = merge_manifests(local, remote)
        assert result["version"] == 2


class TestMergeTranscripts:
    def test_merge_dedup_by_turn_id(self):
        local = json.dumps({"id": "t1", "content": "a"}) + "\n" + json.dumps({"id": "t2", "content": "b"}) + "\n"
        remote = json.dumps({"id": "t2", "content": "b"}) + "\n" + json.dumps({"id": "t3", "content": "c"}) + "\n"

        result = merge_transcripts(local, remote)
        lines = [line for line in result.strip().split("\n") if line]
        ids = [json.loads(line)["id"] for line in lines]
        assert ids == ["t1", "t2", "t3"]

    def test_merge_empty(self):
        result = merge_transcripts("", "")
        assert result == ""

    def test_merge_one_empty(self):
        local = json.dumps({"id": "t1"}) + "\n"
        result = merge_transcripts(local, "")
        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 1


class TestMergeCheckpointFiles:
    def test_merge_files(self, tmp_path):
        local_dir = tmp_path / "local"
        remote_dir = tmp_path / "remote"
        output_dir = tmp_path / "output"

        local_dir.mkdir()
        remote_dir.mkdir()

        (local_dir / "cp1.json").write_text('{"id":"cp1"}')
        (remote_dir / "cp2.json").write_text('{"id":"cp2"}')

        merge_checkpoint_files(local_dir, remote_dir, output_dir)

        assert (output_dir / "cp1.json").exists()
        assert (output_dir / "cp2.json").exists()

    def test_merge_skip_existing(self, tmp_path):
        local_dir = tmp_path / "local"
        remote_dir = tmp_path / "remote"
        output_dir = tmp_path / "output"

        local_dir.mkdir()
        remote_dir.mkdir()

        (local_dir / "cp1.json").write_text('{"id":"cp1","source":"local"}')
        (remote_dir / "cp1.json").write_text('{"id":"cp1","source":"remote"}')

        merge_checkpoint_files(local_dir, remote_dir, output_dir)

        content = json.loads((output_dir / "cp1.json").read_text())
        assert content["source"] == "local"


class TestSecurityFilter:
    def test_filter_enabled(self):
        text = "api_key=secret123"
        result = filter_export_data(text, enabled=True)
        assert "secret123" not in result

    def test_filter_disabled(self):
        text = "api_key=secret123"
        result = filter_export_data(text, enabled=False)
        assert result == text

    def test_get_security_config_defaults(self):
        config = {}
        enabled, patterns = get_security_config(config)
        assert enabled is True
        assert len(patterns) > 0

    def test_get_security_config_custom(self):
        config = {"security": {"filter_secrets": False, "patterns": ["custom"]}}
        enabled, patterns = get_security_config(config)
        assert enabled is False
        assert patterns == ["custom"]
