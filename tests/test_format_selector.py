from src.downloader.ytdlp_runner import format_selector


def test_default_band():
    assert format_selector(720, 1080) == "bv*[height>=720][height<=1080]+ba/b[height>=720][height<=1080]"


def test_other_band():
    # Sanity: function actually substitutes both bounds.
    assert format_selector(1080, 2160) == "bv*[height>=1080][height<=2160]+ba/b[height>=1080][height<=2160]"
