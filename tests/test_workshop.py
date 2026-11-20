import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from track1 import workshop
from track1 import load_fabric


class WorkshopTests(unittest.TestCase):
    def test_tampered_data_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            workshop.verify("channels", b"not the workshop dataset")

    def test_missing_data_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                workshop.analyze(Path(directory))

    def test_download_does_not_overwrite_existing_modified_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "channels.csv"
            path.write_bytes(b"modified")
            with patch.object(workshop, "urlopen") as fetch:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    workshop.download(Path(directory))
                fetch.assert_not_called()
            self.assertEqual(path.read_bytes(), b"modified")

    def test_fabric_manifest_matches_download_manifest(self):
        self.assertEqual(load_fabric.ROWS, {name: count for name, (_, count) in workshop.FILES.items()})
        self.assertEqual(load_fabric.SHA256, {name: digest for name, (digest, _) in workshop.FILES.items()})

    @unittest.skipUnless(
        all((workshop.DATA / f"{name}.csv").is_file() for name in workshop.FILES),
        "download original workshop data first",
    )
    def test_original_dataset_results(self):
        result = workshop.analyze()
        self.assertEqual([len(result[f"Q{i}"]) for i in range(1, 6)], [60, 2, 4, 2, 81])
        for campaign in result["Q1"]:
            self.assertEqual(campaign["order_count"], campaign["approved_orders"]
                             + campaign["failed_orders"] + campaign["unknown_orders"])
        q2 = result["Q2"]
        self.assertEqual([row["orders_count"] for row in q2], [1337, 666])
        self.assertGreater(q2[1]["return_rate_pct"], q2[0]["return_rate_pct"])
        self.assertGreater(q2[1]["complaint_rate_pct"], q2[0]["complaint_rate_pct"])
        q3 = {row["promotion_type"]: row for row in result["Q3"]}
        self.assertLess(q3["Percent"]["net_to_gross"], q3["Bundle"]["net_to_gross"])
        self.assertLess(q3["Percent"]["repeat_customer_pct"], q3["Bundle"]["repeat_customer_pct"])
        q4 = result["Q4"]
        self.assertGreater(q4[1]["cancellation_rate_pct"], q4[0]["cancellation_rate_pct"])
        self.assertGreater(q4[1]["tickets_per_order"], q4[0]["tickets_per_order"])
        self.assertTrue(any(row["return_reason"] is None for row in result["Q5"]))


if __name__ == "__main__":
    unittest.main()
