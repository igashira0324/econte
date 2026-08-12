"""Tests for econte.runners.template: ${token} placeholder substitution."""

from __future__ import annotations

import copy

import pytest

from econte.runners import TemplateError, build_graph, render_template_string


def test_whole_string_match_returns_raw_typed_value() -> None:
    graph = {"10": {"class_type": "KSampler", "inputs": {"seed": "${seed}"}}}
    context = {"seed": 1001}
    result = build_graph(graph, context, profile_id="p", variant_name="v")
    assert result["10"]["inputs"]["seed"] == 1001
    assert type(result["10"]["inputs"]["seed"]) is int


def test_whole_string_match_preserves_bool_and_float() -> None:
    graph = {
        "1": {"class_type": "X", "inputs": {"verbose": "${verbose}", "shift": "${shift}"}},
    }
    context = {"verbose": False, "shift": 3.0}
    result = build_graph(graph, context, profile_id="p", variant_name="v")
    assert result["1"]["inputs"]["verbose"] is False
    assert result["1"]["inputs"]["shift"] == 3.0
    assert type(result["1"]["inputs"]["shift"]) is float


def test_partial_string_match_is_stringified() -> None:
    graph = {"1": {"class_type": "X", "inputs": {"filename_prefix": "prefix_${id}"}}}
    context = {"id": "S01-A"}
    result = build_graph(graph, context, profile_id="p", variant_name="v")
    assert result["1"]["inputs"]["filename_prefix"] == "prefix_S01-A"
    assert isinstance(result["1"]["inputs"]["filename_prefix"], str)


def test_partial_string_with_int_value_is_stringified_not_raw() -> None:
    graph = {"1": {"class_type": "X", "inputs": {"note": "clip index: ${job_index}"}}}
    context = {"job_index": 3}
    result = build_graph(graph, context, profile_id="p", variant_name="v")
    assert result["1"]["inputs"]["note"] == "clip index: 3"


def test_multiple_occurrences_in_one_string_all_replaced() -> None:
    graph = {"1": {"class_type": "X", "inputs": {"path": "${latent_folder}/${latent_folder}"}}}
    context = {"latent_folder": "chain"}
    result = build_graph(graph, context, profile_id="p", variant_name="v")
    assert result["1"]["inputs"]["path"] == "chain/chain"


def test_literal_string_with_no_placeholder_is_left_unchanged() -> None:
    literal_path = "qwen\\qwen_image.safetensors"
    graph = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": literal_path}}}
    result = build_graph(graph, {}, profile_id="p", variant_name="v")
    assert result["1"]["inputs"]["unet_name"] == literal_path


def test_missing_token_raises_template_error_naming_everything() -> None:
    graph = {"6": {"class_type": "LoadImage", "inputs": {"image": "${ref_image}"}}}
    with pytest.raises(TemplateError) as excinfo:
        build_graph(graph, {}, profile_id="my-profile", variant_name="with_ref")
    message = str(excinfo.value)
    assert "my-profile" in message
    assert "with_ref" in message
    assert "6" in message
    assert "image" in message
    assert "ref_image" in message


def test_missing_token_in_partial_string_also_raises() -> None:
    graph = {"1": {"class_type": "X", "inputs": {"path": "${latent_folder}/chain"}}}
    with pytest.raises(TemplateError, match="latent_folder"):
        build_graph(graph, {}, profile_id="p", variant_name="v")


def test_node_reference_arrays_left_untouched() -> None:
    graph = {
        "7": {
            "class_type": "TextEncode",
            "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": "${prompt}"},
        }
    }
    context = {"prompt": "hello"}
    result = build_graph(graph, context, profile_id="p", variant_name="v")
    assert result["7"]["inputs"]["clip"] == ["2", 0]
    assert result["7"]["inputs"]["vae"] == ["3", 0]
    assert type(result["7"]["inputs"]["clip"][1]) is int
    assert type(result["7"]["inputs"]["clip"][0]) is str


def test_non_string_leaves_left_untouched() -> None:
    graph = {
        "9": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 720, "height": None, "batch_size": 1, "flag": True},
        }
    }
    result = build_graph(graph, {}, profile_id="p", variant_name="v")
    assert result["9"]["inputs"] == {"width": 720, "height": None, "batch_size": 1, "flag": True}


def test_build_graph_does_not_mutate_or_alias_input() -> None:
    original = {"1": {"class_type": "X", "inputs": {"seed": "${seed}"}}}
    snapshot = copy.deepcopy(original)
    result = build_graph(original, {"seed": 5}, profile_id="p", variant_name="v")
    assert original == snapshot  # input untouched
    assert result is not original
    assert result["1"] is not original["1"]


def test_nested_dict_leaves_are_walked() -> None:
    graph = {"1": {"class_type": "X", "inputs": {"nested": {"deep": "${seed}"}}}}
    result = build_graph(graph, {"seed": 7}, profile_id="p", variant_name="v")
    assert result["1"]["inputs"]["nested"]["deep"] == 7


# --- render_template_string (used for output.glob, outside a graph) --------


def test_render_template_string_whole_match() -> None:
    result = render_template_string(
        "${job_index}", {"job_index": 3}, profile_id="p", location="x"
    )
    assert result == 3


def test_render_template_string_partial_match() -> None:
    result = render_template_string(
        "${filename_prefix}_*.png",
        {"filename_prefix": "SBdemo/S01-A"},
        profile_id="p",
        location="output.glob",
    )
    assert result == "SBdemo/S01-A_*.png"


def test_render_template_string_missing_token_raises() -> None:
    with pytest.raises(TemplateError, match="output.glob"):
        render_template_string(
            "${missing}_*.png", {}, profile_id="my-profile", location="output.glob"
        )
