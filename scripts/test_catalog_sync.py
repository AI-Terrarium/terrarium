import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catalog_contract import digest, jsonl, normalize
from sync_public_catalog import (
    FILES,
    apply_snapshot,
    archive_matches,
    download,
    merge_catalog,
)


def entry(**values):
    return {
        "kind": "work",
        "slug": "one",
        "title": "One",
        "creator": "Original",
        "form": "games",
        "description": "before",
    } | values


class CatalogSyncTests(unittest.TestCase):
    def test_shared_slug_cannot_attach_another_authors_or_repositories_files(self):
        work = entry(source_url="https://github.com/owner/game")
        self.assertFalse(archive_matches(work, work | {"creator": "Someone Else"}))
        self.assertFalse(archive_matches(work, work | {"source_url": "https://github.com/owner/other"}))
        self.assertTrue(archive_matches(work, work | {"source_url": "https://github.com/Owner/Game.git/"}))
        self.assertTrue(archive_matches(work, work | {"creator": "@ORIGINAL"}))

    def test_pinned_dispatch_reads_one_revision_and_requires_the_expected_batch(self):
        revision = "a" * 40
        batch = "00000000-0000-0000-0000-000000000001"
        marker = json.dumps({"batch_id": batch, "generated_at": "2026-01-01T00:00:00Z"}).encode()
        seen = []

        def fetch(url, **kwargs):
            seen.append(url)
            self.assertIn("/raw/" + revision + "/", url)
            return marker if url.endswith("catalog-sync.json") else b"fixture"

        with patch("sync_public_catalog.fetch", fetch):
            bundle, actual = download(300, revision=revision, batch_id=batch)
            self.assertEqual(actual, revision)
            self.assertEqual(set(bundle), set(FILES))
            with self.assertRaisesRegex(ValueError, "source_batch_mismatch"):
                download(revision=revision, batch_id="another-batch")
            with self.assertRaisesRegex(ValueError, "invalid_source_revision"):
                download(revision="main", batch_id=batch)

    def test_review_can_remove_only_the_exact_duplicate_github_record(self):
        duplicate = normalize(entry(slug="duplicate"))
        resolution = {
            "kind": "work", "slug": "duplicate", "decision": "keep_platform",
            "fields": list(duplicate), "remote_hash": digest(duplicate),
        }
        result, _ = merge_catalog([], [duplicate], [], [resolution])
        self.assertEqual(result, [])
        edited = duplicate | {"description": "New independent edit"}
        result, _ = merge_catalog([], [edited], [], [resolution])
        self.assertEqual(result, [edited])

    def test_disjoint_edits_and_same_field_conflicts(self):
        base = entry()
        result, conflicts = merge_catalog(
            [base], [base | {"title": "Local"}], [base | {"description": "Remote"}]
        )
        self.assertEqual(result[0]["title"], "Local")
        self.assertEqual(result[0]["description"], "Remote")
        self.assertEqual(conflicts, [])
        result, conflicts = merge_catalog(
            [base], [base | {"title": "Local"}], [base | {"title": "Remote"}]
        )
        self.assertEqual(result[0]["title"], "Local")
        self.assertEqual(conflicts[0]["fields"], ["title"])

    def test_source_absence_never_deletes_a_github_work(self):
        result, conflicts = merge_catalog([entry()], [entry()], [])
        self.assertEqual(result, [normalize(entry())])
        self.assertEqual(conflicts, [])

    def test_explicit_review_resolution_requires_exact_observed_content(self):
        before = entry()
        local = normalize(entry(title="GitHub edit"))
        remote = entry(title="Platform value")
        resolution = {
            "kind": "work",
            "slug": "one",
            "decision": "keep_platform",
            "fields": ["title"],
            "remote_hash": digest(local),
        }
        result, conflicts = merge_catalog([before], [local], [remote], [resolution])
        self.assertEqual(result[0]["title"], "Platform value")
        result, conflicts = merge_catalog(
            [before], [local | {"title": "New edit after review"}], [remote], [resolution]
        )
        self.assertEqual(result[0]["title"], "New edit after review")
        self.assertTrue(conflicts)

    def test_member_objects_keep_public_relationships_only(self):
        record = normalize(
            entry(
                kind="collection",
                members=[
                    {
                        "id": "a",
                        "title": "A",
                        "work": "one",
                        "source_url": "https://example.org/a",
                        "private_note": "do not publish",
                    }
                ],
            )
        )
        self.assertEqual(record["members"][0]["work"], "one")
        self.assertNotIn("private_note", record["members"][0])

    def test_corrupted_snapshot_is_rejected_before_rendering(self):
        records = [entry()]
        body = jsonl(records)
        bundle = {
            "catalog.jsonl": body,
            "catalog-sync.json": json.dumps(
                {"schema_version": 1, "interval_hours": 8, "catalog_sha256": "0" * 64}
            ).encode(),
        }
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaisesRegex(ValueError, "snapshot_hash_mismatch"):
                apply_snapshot(Path(path), bundle, "a" * 40)
            self.assertFalse((Path(path) / "data").exists())


if __name__ == "__main__":
    unittest.main()
