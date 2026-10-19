"""Tests for the Cache class."""

from datetime import UTC, datetime
from pathlib import Path

from pazufa_corelib.cache import Value

from pazufa_scraper_be.cache import Cache, Key
from pazufa_scraper_be.constants import DOK_CACHE_HISTORY_SUB_DIR_PATH


class TestCacheInit:
    """Tests for Cache initialization."""

    def test_init_creates_backend_with_correct_directory(self, tmp_path: Path) -> None:
        """Test that initialization creates the correct directory structure."""
        cache_name = "test_cache"
        cache = Cache(base_dir=tmp_path, name=cache_name)

        expected_dir = tmp_path / cache_name
        assert cache.backend.directory == expected_dir
        assert cache.name == cache_name

    def test_init_creates_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that the cache directory is created if it doesn't exist."""
        cache_name = "new_cache"
        Cache(base_dir=tmp_path, name=cache_name)

        expected_dir = tmp_path / cache_name
        assert expected_dir.exists()


class TestLastChecked:
    """Tests for last_checked functionality."""

    def test_update_and_get_last_checked(self, tmp_path: Path) -> None:
        """Test updating and retrieving the last_checked timestamp."""
        cache = Cache(base_dir=tmp_path, name="test")

        # Initially should be None
        assert cache.get_last_checked() is None

        # Update and retrieve
        before_update = datetime.now(UTC)
        cache.update_last_checked()
        after_update = datetime.now(UTC)

        last_checked = cache.get_last_checked()
        assert last_checked is not None
        assert before_update <= last_checked <= after_update


class TestModelSpecificSummary:
    """Tests for model-specific summary functionality."""

    def test_model_specific_file_path_format(self, tmp_path: Path) -> None:
        """Test that model-specific file path is formatted correctly."""
        cache = Cache(base_dir=tmp_path, name="test")
        llm_model = "gpt-4o"
        expected_suffix = "_gpt-4o.txt"

        file_path = cache._get_model_specific_summary_file_path(llm_model_name=llm_model)
        assert file_path.name.endswith(expected_suffix)

    def test_model_specific_file_path_with_slash_in_model_name(self, tmp_path: Path) -> None:
        """Test that slashes in model names are replaced with underscores."""
        cache = Cache(base_dir=tmp_path, name="test")
        llm_model = "gpt-4o/2024-08-01"
        expected_suffix = "_gpt-4o__2024-08-01.txt"

        file_path = cache._get_model_specific_summary_file_path(llm_model_name=llm_model)
        assert file_path.name.endswith(expected_suffix)
        assert "/" not in file_path.name

    def test_exist_model_specific_summary_returns_false_when_not_exists(self, tmp_path: Path) -> None:
        """Test that exist_model_specific_summary returns False when file doesn't exist."""
        cache = Cache(base_dir=tmp_path, name="test")
        assert cache.exist_model_specific_summary(llm_model_name="gpt-4o") is False

    def test_set_and_exist_model_specific_summary(self, tmp_path: Path) -> None:
        """Test setting and checking existence of model-specific summary."""
        cache = Cache(base_dir=tmp_path, name="test")
        summary_content = "This is a test summary."
        model_name = "gpt-4o"

        # Should not exist initially
        assert cache.exist_model_specific_summary(model_name) is False

        # Set summary
        cache.set_model_specific_summary(model_name, summary_content)

        # Should exist now
        assert cache.exist_model_specific_summary(model_name) is True

    def test_set_model_specific_summary_writes_content(self, tmp_path: Path) -> None:
        """Test that set_model_specific_summary writes the correct content."""
        cache = Cache(base_dir=tmp_path, name="test")
        summary_content = "Test summary content with special chars: äöü"
        model_name = "claude-3"

        cache.set_model_specific_summary(model_name, summary_content)

        file_path = cache._get_model_specific_summary_file_path(model_name)
        assert file_path.read_text() == summary_content

    def test_multiple_model_specific_summaries(self, tmp_path: Path) -> None:
        """Test storing summaries for multiple models."""
        cache = Cache(base_dir=tmp_path, name="test")

        summaries = {
            "gpt-4o": "GPT-4o summary",
            "claude-3": "Claude-3 summary",
            "gemini-pro": "Gemini Pro summary",
        }

        for model, summary in summaries.items():
            cache.set_model_specific_summary(model, summary)

        for model, expected_summary in summaries.items():
            assert cache.exist_model_specific_summary(model) is True

            file_path = cache._get_model_specific_summary_file_path(model)
            assert file_path.read_text() == expected_summary


class TestLinkModelSpecificSummaryFile:
    """Tests for link_model_specific_summary_file functionality."""

    def test_link_creates_symlink(self, tmp_path: Path) -> None:
        """Test that link creates a symlink to the model-specific file."""
        cache = Cache(base_dir=tmp_path, name="test")
        model_name = "gpt-4o"
        summary_content = "Linked summary content"

        # Create the target file first
        cache.set_model_specific_summary(model_name, summary_content)

        # Link it
        cache.link_model_specific_summary_file(model_name)

        # Check symlink exists
        summary_file = cache.backend.get_file_path(key=Key.SUMMARY, value_type=Value.TEXT)
        assert summary_file.is_symlink()
        assert summary_file.resolve() == cache._get_model_specific_summary_file_path(model_name)

    def test_link_overwrites_existing_symlink(self, tmp_path: Path) -> None:
        """Test that linking overwrites an existing symlink."""
        cache = Cache(base_dir=tmp_path, name="test")

        # Create first model summary and link it
        cache.set_model_specific_summary("model-1", "Model 1 content")
        cache.link_model_specific_summary_file("model-1")

        # Create second model summary and link it
        cache.set_model_specific_summary("model-2", "Model 2 content")
        cache.link_model_specific_summary_file("model-2")

        # Check that the symlink now points to model-2
        summary_file = cache.backend.get_file_path(key=Key.SUMMARY, value_type=Value.TEXT)
        assert summary_file.is_symlink()
        assert summary_file.resolve().name == cache._get_model_specific_summary_file_path("model-2").name

    def test_link_target_content_accessible_via_symlink(self, tmp_path: Path) -> None:
        """Test that content is accessible through the symlink."""
        cache = Cache(base_dir=tmp_path, name="test")
        model_name = "claude-3"
        summary_content = "Accessible via symlink"

        cache.set_model_specific_summary(model_name, summary_content)
        cache.link_model_specific_summary_file(model_name)

        # Read through the symlink
        summary_file = cache.backend.get_file_path(key=Key.SUMMARY, value_type=Value.TEXT)
        assert summary_file.read_text() == summary_content


class TestReset:
    """Tests for reset functionality."""

    def test_reset_creates_history_directory(self, tmp_path: Path) -> None:
        """Test that reset creates the history directory."""
        cache = Cache(base_dir=tmp_path, name="test")

        cache.reset()

        history_dir = tmp_path / "test" / DOK_CACHE_HISTORY_SUB_DIR_PATH
        assert history_dir.exists()
        assert history_dir.is_dir()

    def test_reset_moves_files_to_version_directory(self, tmp_path: Path) -> None:
        """Test that reset moves cache files to a versioned history directory."""
        cache = Cache(base_dir=tmp_path, name="test")

        # Create some cache files
        cache.update_last_checked()
        cache.set_model_specific_summary("gpt-4o", "Test summary")

        # Reset
        cache.reset()

        # Check version directory was created
        history_dir = tmp_path / "test" / DOK_CACHE_HISTORY_SUB_DIR_PATH
        version_dirs = [d for d in history_dir.iterdir() if d.is_dir()]
        assert len(version_dirs) == 1

        # Check files were moved
        version_dir = version_dirs[0]
        versioned_files = list(version_dir.iterdir())
        assert len(versioned_files) == 3  # last checken + metadata file and model specific summary which is just a file

    def test_reset_increments_version_number(self, tmp_path: Path) -> None:
        """Test that consecutive resets create incrementing version numbers."""
        cache = Cache(base_dir=tmp_path, name="test")

        # First reset
        cache.reset()
        cache.update_last_checked()  # Add some content for next reset

        # Second reset
        cache.reset()

        history_dir = tmp_path / "test" / DOK_CACHE_HISTORY_SUB_DIR_PATH
        version_dirs = sorted([d for d in history_dir.iterdir() if d.is_dir()], key=lambda x: int(x.name))

        assert len(version_dirs) == 2
        assert version_dirs[0].name == "1"
        assert version_dirs[1].name == "2"

    def test_reset_handles_multiple_consecutive_resets(self, tmp_path: Path) -> None:
        """Test multiple consecutive resets maintain correct versioning."""
        cache = Cache(base_dir=tmp_path, name="test")
        num_resets = 5

        for i in range(num_resets):
            cache.update_last_checked()
            cache.set_model_specific_summary(f"model-{i}", f"Summary {i}")
            cache.reset()

        history_dir = tmp_path / "test" / DOK_CACHE_HISTORY_SUB_DIR_PATH
        version_dirs = sorted([d for d in history_dir.iterdir() if d.is_dir()], key=lambda x: int(x.name))

        assert len(version_dirs) == num_resets
        assert [int(d.name) for d in version_dirs] == list(range(1, num_resets + 1))

    def test_reset_clears_cache_directory(self, tmp_path: Path) -> None:
        """Test that reset clears files from the cache directory."""
        cache = Cache(base_dir=tmp_path, name="test")

        # Create files
        cache.update_last_checked()
        cache.set_model_specific_summary("gpt-4o", "Test")

        # Reset
        cache.reset()

        # Cache directory should only contain the history subdirectory
        remaining_items = [item for item in cache.backend.directory.iterdir() if item.is_file()]
        assert len(remaining_items) == 0

    def test_reset_preserves_history(self, tmp_path: Path) -> None:
        """Test that reset preserves content in history directory."""
        cache = Cache(base_dir=tmp_path, name="test")
        test_content = "Preserved content"

        # Create content and reset
        cache.set_model_specific_summary("gpt-4o", test_content)
        cache.reset()

        # Check history preserves the content
        history_dir = tmp_path / "test" / DOK_CACHE_HISTORY_SUB_DIR_PATH
        version_dir = history_dir / "1"

        # Find the summary file in history
        summary_files = list(version_dir.glob("*SUMMARY*"))
        assert len(summary_files) == 1
        assert summary_files[0].read_text() == test_content
