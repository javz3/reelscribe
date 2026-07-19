from pathlib import Path

from reelscribe.library import Library, extract_urls, safe_component, slugify


def make_lib(tmp_path: Path) -> Library:
    lib = Library(tmp_path / "lib")
    lib.ensure_dirs()
    return lib


def test_next_number_empty(tmp_path):
    assert make_lib(tmp_path).next_number() == 1


def test_next_number_continues(tmp_path):
    lib = make_lib(tmp_path)
    (lib.videos / "141_Some One_123.mp4").touch()
    (lib.videos / "007_Old_9.mp4").touch()
    assert lib.next_number() == 142
    assert lib.width() == 3


def test_find_by_video_id(tmp_path):
    lib = make_lib(tmp_path)
    f = lib.videos / "141_Some One_9876543210.mp4"
    f.touch()
    assert lib.find_by_video_id("9876543210") == f
    assert lib.find_by_video_id("543") is None  # substring must not match


def test_safe_component():
    assert safe_component('Dr. Josh, PT') == "Dr. Josh, PT"
    assert safe_component('a/b:c*d?"e"') == "abcde"
    assert safe_component("") == "unknown"


def test_slugify():
    assert slugify("Why + How you should train YOUR Neck!") == \
        "why_how_should_train_neck"
    assert slugify("") == "untitled"


def test_extract_urls():
    text = """1. https://www.facebook.com/share/r/abc123/
    - [reel](https://youtu.be/xyz?si=1), and https://www.facebook.com/share/r/abc123/ again"""
    urls = extract_urls(text)
    assert urls == ["https://www.facebook.com/share/r/abc123/", "https://youtu.be/xyz?si=1"]


def test_categories(tmp_path):
    lib = make_lib(tmp_path)
    lib.readme.write_text(
        "# T\n## Quick Navigation by Topic\n## Neck stuff\n## Library Stats\n## Created / Updated\n",
        encoding="utf-8")
    assert lib.categories() == ["Neck stuff"]


def test_stats(tmp_path):
    lib = make_lib(tmp_path)
    (lib.videos / "001_A_1.mp4").touch()
    (lib.audio / "001_A_1.m4a").touch()
    (lib.transcripts / "001_A_1.txt").touch()
    s = lib.stats()
    assert (s["videos"], s["audio"], s["transcripts"]) == (1, 1, 1)
    assert s["next_number"] == 2


def test_clean_title():
    from reelscribe.docgen import clean_title
    info = {"title": "392K views · 5.3K reactions | This exercise looks dumb, "
                     "but it helps neck stiffness #neckpainrelief #headaches"}
    assert clean_title(info) == "This exercise looks dumb, but it helps neck stiffness"
    assert clean_title({"title": ""}) == "Untitled reel"
