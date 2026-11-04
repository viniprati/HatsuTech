import io
import unittest

from PIL import Image, ImageChops

from cogs.engagement.profile_renderer import BADGE_SPECS, BADGE_DIR, FONT_DIR, SIZE, _avatar, _fit, _number, _progress, render_profile


class ProfileRendererTests(unittest.TestCase):
    def test_render_is_png_and_has_expected_size(self):
        data = render_profile({"display_name": "Pessoa", "achievements": []})
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, SIZE)
        self.assertEqual(image.format, "PNG")

    def test_all_ten_badges_and_missing_data_do_not_become_zero(self):
        data = render_profile({"display_name": "\x00Pessoa"})
        self.assertGreater(len(data), 10_000)
        self.assertEqual(len(BADGE_SPECS), 10)

    def test_malformed_avatar_falls_back(self):
        data = render_profile({"display_name": "Pessoa"}, b"not-an-image")
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_assets_fonts_and_license_are_packaged(self):
        for aid in BADGE_SPECS:
            self.assertTrue((BADGE_DIR / f"{aid}.svg").is_file())
            with Image.open(BADGE_DIR / f"{aid}.png") as icon:
                self.assertEqual(icon.mode, "RGBA")
                self.assertEqual(icon.size, (256, 256))
                self.assertEqual(icon.getchannel("A").getextrema(), (0, 255))
        self.assertTrue((FONT_DIR / "Montserrat-Regular.otf").is_file())
        self.assertTrue((FONT_DIR / "Montserrat-SemiBold.otf").is_file())
        self.assertIn("OPEN FONT LICENSE", (FONT_DIR / "OFL.txt").read_text())

    def test_numeric_unknowns_and_weighted_voice_precision(self):
        self.assertEqual(_number(None), "Indisponível")
        self.assertEqual(_number(float("inf")), "Indisponível")
        self.assertEqual(_number(-1), "Indisponível")
        self.assertEqual(_number(770.5, " h", 1), "770,5 h")
        self.assertEqual(_progress(float("nan")), 0)
        self.assertEqual(_progress(9), 1)

    def test_long_names_fit_actual_pixel_width(self):
        text, font = _fit("W" * 64, 42, 575, True)
        self.assertLessEqual(font.getlength(text), 575)

    def test_avatar_dimensions_checked_before_decoding(self):
        source = Image.new("RGB", (2100, 2100), "red")
        raw = io.BytesIO()
        source.save(raw, format="PNG")
        actual = _avatar(raw.getvalue(), "#94dcc7")
        expected = _avatar(None, "#94dcc7")
        self.assertIsNone(ImageChops.difference(actual, expected).getbbox())

    def test_saved_award_remains_visible_when_source_unavailable(self):
        source = {"id": "cafeinado", "available": False, "progress": 0}
        a = Image.open(io.BytesIO(render_profile({"achievements": [source]})))
        b = Image.open(io.BytesIO(render_profile({"achievements": [{**source, "unlocked": True}]})))
        self.assertIsNotNone(ImageChops.difference(a, b).getbbox())

    def test_bio_featured_and_theme_change_rendered_result(self):
        source = {"achievements": [{"id": "cafeinado", "unlocked": True}]}
        baseline = render_profile(source)
        self.assertNotEqual(baseline, render_profile({**source, "bio": "Uma história no Café"}))
        self.assertNotEqual(baseline, render_profile({**source, "featured": ["cafeinado"]}))
        self.assertNotEqual(baseline, render_profile({**source, "theme": "sakura"}))


if __name__ == "__main__":
    unittest.main()
