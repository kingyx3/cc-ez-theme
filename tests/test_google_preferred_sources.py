from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNIPPET = REPOSITORY_ROOT / "theme" / "snippets" / "google-preferred-sources.liquid"


def test_preferred_sources_uses_manual_google_flow_with_tracking() -> None:
    content = SNIPPET.read_text(encoding="utf-8")

    assert 'preferred-sources-control="manual"' in content
    assert "self.PREFERRED_SOURCE = self.PREFERRED_SOURCE || []" in content
    assert "preferredSource.addPreferredSource();" in content
    assert "'preferred_source_start'" in content
    assert "source: 'footer'" in content
    assert "domain: 'cardboard.sg'" in content


def test_preferred_sources_reuses_existing_analytics_only() -> None:
    content = SNIPPET.read_text(encoding="utf-8")

    assert "typeof window.gtag === 'function'" in content
    assert "Array.isArray(window.dataLayer)" in content
    assert "googletagmanager.com/gtag/js" not in content
    assert "google-add-preferred-source-btn" not in content


def test_preferred_sources_cta_is_recognizably_google_branded() -> None:
    content = SNIPPET.read_text(encoding="utf-8")

    assert "https://www.gstatic.com/images/branding/product/2x/googleg_48dp.png" in content
    assert "Add us as a Preferred Source on Google" in content
    assert 'aria-label="Add Cardboard Collective as a preferred source on Google"' in content
    assert 'class="google-preferred-source__icon"' in content
