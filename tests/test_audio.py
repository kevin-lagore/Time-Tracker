"""Tests for audio utilities."""

import os
import tempfile

from app.audio import sha256_file, validate_audio

import pytest


class TestSha256:
    def test_hash_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(b"fake audio data")
            f.flush()
            path = f.name

        try:
            h = sha256_file(path)
            assert len(h) == 64
            assert h == sha256_file(path)  # deterministic
        finally:
            os.unlink(path)

    def test_different_content_different_hash(self):
        paths = []
        for content in [b"content_a", b"content_b"]:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                f.write(content)
                f.flush()
                paths.append(f.name)

        try:
            assert sha256_file(paths[0]) != sha256_file(paths[1])
        finally:
            for p in paths:
                os.unlink(p)


class TestValidateAudio:
    def test_valid_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(b"some audio bytes")
            f.flush()
            path = f.name

        try:
            result = validate_audio(path)
            assert result.exists()
        finally:
            os.unlink(path)

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            validate_audio("/nonexistent/file.wav")

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            path = f.name

        try:
            with pytest.raises(ValueError, match="empty"):
                validate_audio(path)
        finally:
            os.unlink(path)
