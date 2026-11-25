import unittest

from track1.standardization import RULES, standardize_value


class Track1StandardizationTests(unittest.TestCase):
    def test_workshop_status_mappings(self):
        rules = {rule.source: rule for rule in RULES["orders"]}
        self.assertEqual(standardize_value("Completed", rules["order_status"]), "PAID")
        self.assertEqual(standardize_value("Cancelled", rules["order_status"]), "CANCELLED")
        self.assertEqual(standardize_value("RetrySuccess", {rule.source: rule for rule in RULES["payments"]}["payment_status"]), "AUTHORIZED")
        self.assertEqual(standardize_value("InTransit", {rule.source: rule for rule in RULES["shipments"]}["shipment_status"]), "IN_TRANSIT")

    def test_support_reason_mapping_preserves_distinct_meaning(self):
        rule = next(rule for rule in RULES["support_tickets"] if rule.source == "ticket_reason")
        self.assertEqual(standardize_value("NoTrackingUpdate", rule), "NO_TRACKING_UPDATE")
        self.assertEqual(standardize_value(None, rule), None)

    def test_unknown_status_is_not_silently_kept_or_discarded(self):
        rule = next(rule for rule in RULES["orders"] if rule.source == "order_status")
        with self.assertRaisesRegex(ValueError, "unmapped value"):
            standardize_value("UnexpectedStatus", rule)


if __name__ == "__main__":
    unittest.main()
