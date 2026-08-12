from __future__ import annotations

import json
from pathlib import Path
import unittest

from pia_bazzite import public_network


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
OPTIONS = ROOT / "pia_bazzite" / "options_dialog.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage3CProviderOptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gui = GUI.read_text(encoding="utf-8")
        self.options = OPTIONS.read_text(encoding="utf-8")
        self.de = json.loads(DE.read_text(encoding="utf-8"))
        self.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_only_maintained_online_candidates_are_selectable(self) -> None:
        self.assertEqual(
            public_network.SELECTABLE_ONLINE_PUBLIC_NETWORK_PROVIDER_IDS,
            (
                public_network.FREEIPAPI_PROVIDER,
                public_network.GEOJS_PROVIDER,
                public_network.IPWHOIS_PROVIDER,
            ),
        )
        self.assertNotIn(
            public_network.COUNTRY_IS_PROVIDER,
            public_network.SELECTABLE_ONLINE_PUBLIC_NETWORK_PROVIDER_IDS,
        )
        self.assertNotIn(
            public_network.CLOUDFLARE_PROVIDER,
            public_network.SELECTABLE_ONLINE_PUBLIC_NETWORK_PROVIDER_IDS,
        )

    def test_stage3c_default_is_geojs(self) -> None:
        self.assertEqual(
            public_network.DEFAULT_ONLINE_PUBLIC_NETWORK_PROVIDER,
            public_network.GEOJS_PROVIDER,
        )
        self.assertEqual(
            public_network.normalize_online_public_network_provider(None),
            public_network.GEOJS_PROVIDER,
        )
        self.assertEqual(
            public_network.normalize_online_public_network_provider("garbage"),
            public_network.GEOJS_PROVIDER,
        )
        self.assertEqual(
            public_network.normalize_online_public_network_provider(" GEOJS "),
            public_network.GEOJS_PROVIDER,
        )

    def test_options_dialog_exposes_one_network_provider_selector(self) -> None:
        self.assertIn('QGroupBox(tr("options.network"))', self.options)
        self.assertIn('tr("options.public_info_provider")', self.options)
        self.assertIn('tr("options.provider.freeipapi")', self.options)
        self.assertIn('tr("options.provider.geojs")', self.options)
        self.assertIn('tr("options.provider.ipwhois")', self.options)
        self.assertNotIn('tr("options.provider.country_is")', self.options)
        self.assertNotIn('tr("options.provider.cloudflare")', self.options)
        self.assertIn(
            'DEFAULT_ONLINE_PUBLIC_NETWORK_PROVIDER',
            self.options,
        )
        self.assertNotIn(
            'settings.value("network/public_info_provider", FREEIPAPI_PROVIDER)',
            self.options,
        )
        self.assertIn("public_network_provider: str", self.options)
        self.assertIn("public_network_provider=normalize_online_public_network_provider(", self.options)

    def test_provider_selector_keeps_stage3a_visual_grid(self) -> None:
        self.assertIn(
            "self._configure_combo(self.public_network_provider_combo)",
            self.options,
        )
        self.assertIn(
            'self._form_label(tr("options.public_info_provider"))',
            self.options,
        )
        self.assertIn("OPTIONS_LABEL_COLUMN_WIDTH = 230", self.options)
        self.assertIn("OPTIONS_FIELD_WIDTH = 250", self.options)
        self.assertIn("OPTIONS_DIALOG_HEIGHT = 410", self.options)

    def test_saving_provider_is_persistent_and_refreshes_public_info(self) -> None:
        show_start = self.gui.index("    def show_options")
        change_start = self.gui.index("    def change_public_network_provider", show_start)
        language_start = self.gui.index("    def change_language", change_start)
        show = self.gui[show_start:change_start]
        change = self.gui[change_start:language_start]

        self.assertIn(
            "values.public_network_provider != current_public_network_provider",
            show,
        )
        self.assertIn(
            "self.change_public_network_provider(values.public_network_provider)",
            show,
        )
        self.assertIn(
            'self.settings.setValue("network/public_info_provider", normalized)',
            change,
        )
        self.assertIn("self.settings.sync()", change)
        self.assertIn("self.refresh_public_info(show_errors=False)", change)

    def test_public_info_refresh_uses_selected_provider(self) -> None:
        start = self.gui.index("    def refresh_public_info")
        end = self.gui.index("    def _rebuild_tray_menu", start)
        refresh = self.gui[start:end]
        self.assertIn('"network/public_info_provider"', refresh)
        self.assertIn("DEFAULT_ONLINE_PUBLIC_NETWORK_PROVIDER", refresh)
        self.assertIn("normalize_online_public_network_provider(", refresh)
        self.assertIn(
            "lambda: fetch_public_network_info(provider_id=provider_id)",
            refresh,
        )

    def test_provider_privacy_tooltip_and_bilingual_key_sets_exist(self) -> None:
        for key in (
            "options.network",
            "options.public_info_provider",
            "options.public_info_provider_tooltip",
            "options.provider.freeipapi",
            "options.provider.geojs",
            "options.provider.ipwhois",
        ):
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertIn("öffentlichen IP-Adresse", self.de["options.public_info_provider_tooltip"])
        self.assertIn("public IP address", self.en["options.public_info_provider_tooltip"])
        self.assertEqual(self.de["options.provider.geojs"], "GeoJS (Standard)")
        self.assertEqual(self.en["options.provider.geojs"], "GeoJS (Default)")
        self.assertEqual(set(self.en), set(self.de))


if __name__ == "__main__":
    unittest.main()
