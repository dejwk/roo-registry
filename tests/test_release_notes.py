import tempfile
import unittest
from pathlib import Path

from release_notes import read_top_entry, upsert_draft_entry


class ReleaseNotesTest(unittest.TestCase):

    def test_replaces_all_unpublished_content_and_preserves_history_bytes(self):
        for heading in (
            "# roo_library 1.2.2",
            "# [roo_library 1.2.2](https://example/release)",
        ):
            with self.subTest(heading=heading), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "RELEASE_NOTES.md"
                history = (heading + "\r\n\r\nPublished notes.\r\n\r\n---\r\n"
                           "# roo_library 1.2.1\r\nOlder notes.\r\n").encode()
                path.write_bytes(
                    b"# Unreleased\n\nNew feature.\n\n"
                    b"# roo_library 1.2.4\n\nOld draft.\n\n---\n\n"
                    b"# roo_library 1.2.3\n\nAnother draft.\n\n" + history
                )
                upsert_draft_entry(path, "roo_library", "1.2.4", "Final notes.",
                                   published_versions={"1.2.2", "1.2.1"})
                expected = b"# roo_library 1.2.4\n\nFinal notes.\n\n---\n\n" + history
                self.assertEqual(expected, path.read_bytes())
                upsert_draft_entry(path, "roo_library", "1.2.4", "Final notes.",
                                   published_versions={"1.2.2", "1.2.1"})
                self.assertEqual(expected, path.read_bytes())

    def test_first_release_replaces_all_drafts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "RELEASE_NOTES.md"
            path.write_text("# Unreleased\nDraft.\n# roo_library 0.1.0\nOld draft.\n")
            upsert_draft_entry(path, "roo_library", "1.0.0", "First release.",
                               published_versions=set())
            self.assertEqual("# roo_library 1.0.0\n\nFirst release.\n\n---\n", path.read_text())

    def test_repreparing_published_version_does_not_duplicate_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "RELEASE_NOTES.md"
            history = "# roo_library 1.2.1\nOlder notes.\n"
            path.write_text("# roo_library 1.2.2\nCurrent notes.\n" + history)
            upsert_draft_entry(path, "roo_library", "1.2.2", "Updated notes.",
                               published_versions={"1.2.2", "1.2.1"})
            self.assertEqual("# roo_library 1.2.2\n\nUpdated notes.\n\n---\n\n" + history,
                             path.read_text())

    def test_creates_a_draft_before_existing_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_path = Path(temp_dir) / "RELEASE_NOTES.md"
            notes_path.write_text("# roo_library 1.2.2\n\nOld notes.\n", encoding="utf-8")

            upsert_draft_entry(notes_path, "roo_library", "1.2.3", "New notes.")

            self.assertEqual(
                "# roo_library 1.2.3\n\nNew notes.\n\n---\n\n"
                "# roo_library 1.2.2\n\nOld notes.\n",
                notes_path.read_text(encoding="utf-8"),
            )

    def test_retaining_existing_notes_preserves_exact_file_bytes(self):
        for content in (
            "# roo_library 1.2.3\n\nExisting notes.\n\n---\n\n"
            "# roo_library 1.2.2\n\nHistory.\n",
            "\n# [roo_library 1.2.3](https://example/release)\n\n"
            "Existing notes.\n\n---\n\n\n# roo_library 1.2.2\n\nHistory.\n",
            "# roo_library 1.2.3\r\n\r\nExisting notes.\r\n\r\n---\r\n\r\n"
            "# roo_library 1.2.2\r\n\r\nHistory.\r\n",
            "# roo_library 1.2.3\n\nExisting notes.",
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp_dir:
                notes_path = Path(temp_dir) / "RELEASE_NOTES.md"
                original = content.encode("utf-8")
                notes_path.write_bytes(original)
                notes = read_top_entry(notes_path, "roo_library", "1.2.3")
                self.assertEqual("Existing notes.", notes)

                upsert_draft_entry(notes_path, "roo_library", "1.2.3", notes)

                self.assertEqual(original, notes_path.read_bytes())

    def test_updates_only_a_matching_top_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_path = Path(temp_dir) / "RELEASE_NOTES.md"
            notes_path.write_text(
                "# roo_library 1.2.3\n\nOld draft.\n\n---\n\n"
                "# roo_library 1.2.2\n\nHistory.\n",
                encoding="utf-8",
            )

            upsert_draft_entry(notes_path, "roo_library", "1.2.3", "Updated draft.")

            self.assertEqual(
                "Updated draft.",
                read_top_entry(notes_path, "roo_library", "1.2.3"),
            )
            self.assertIn("# roo_library 1.2.2\n\nHistory.", notes_path.read_text())


if __name__ == "__main__":
    unittest.main()
