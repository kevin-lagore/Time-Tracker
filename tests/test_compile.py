"""Tests for compile formatting."""

import os
import tempfile

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_tmpdir, "test_compile.db"))

from app.compile import _format_duration, _parse_week, _md_to_html


class TestFormatDuration:
    def test_minutes_only(self):
        assert _format_duration(300) == "5m"
        assert _format_duration(60) == "1m"
        assert _format_duration(0) == "0m"

    def test_hours_and_minutes(self):
        assert _format_duration(3600) == "1h 0m"
        assert _format_duration(3900) == "1h 5m"
        assert _format_duration(7260) == "2h 1m"


class TestParseWeek:
    def test_parse_week(self):
        start, end = _parse_week("2025-W01")
        assert start is not None
        assert end is not None
        # Week should be 7 days
        from datetime import datetime
        d_start = datetime.strptime(start, "%Y-%m-%d")
        d_end = datetime.strptime(end, "%Y-%m-%d")
        assert (d_end - d_start).days == 6

    def test_parse_week_format2(self):
        start, end = _parse_week("2025-W10")
        assert start is not None


class TestMdToHtml:
    def test_basic_conversion(self):
        md = "# Title\n## Section\n- bullet one\n- **bold item**"
        html = _md_to_html(md)
        assert "<h1>Title</h1>" in html
        assert "<h2>Section</h2>" in html
        assert "<li>bullet one</li>" in html
        assert "<!DOCTYPE html>" in html
