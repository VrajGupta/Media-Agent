"""Unit tests for assembler.normalize — pure filter-chain strings."""

from src.assembler.normalize import normalize_input_chain


def test_normalize_input_chain_exact_filter_string():
    chain = normalize_input_chain(0, width=1080, height=1920, fps=30)
    assert chain == (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,fps=30,format=yuv420p,settb=AVTB[vn0]"
    )


def test_normalize_input_chain_uses_index_in_input_and_output_labels():
    chain = normalize_input_chain(2, width=720, height=1280, fps=24)
    assert chain.startswith("[2:v]")
    assert chain.endswith("[vn2]")


def test_normalize_input_chain_custom_out_label():
    chain = normalize_input_chain(1, width=1080, height=1920, fps=30, out_label="custom")
    assert chain.endswith("[custom]")
