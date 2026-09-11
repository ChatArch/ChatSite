from importlib import resources


def test_image_static_resources_are_packaged():
    static = resources.files("chatsite").joinpath("image_static")

    for name in ("index.html", "image.css", "image.js", "logo.png"):
        assert static.joinpath(name).is_file()

    assert static.joinpath("logo.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
