from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from ..validators import validate_date


class ValidateDateTests(SimpleTestCase):
    def test_valid_iso_dates_do_not_raise(self):
        for date in ["2026-01-01", "2026-09-02", "2026-12-31", "2028-02-29"]:
            with self.subTest(date=date):
                # Should not raise an exception.
                validate_date(date)

    def test_invalid_dates_raise_validation_error(self):
        for date in ["2026-02-30", "2026-13-01", "not-a-date", "2026/09/02", ""]:
            with self.subTest(date=date):
                with self.assertRaises(ValidationError):
                    validate_date(date)

    def test_error_message_names_the_bad_date(self):
        with self.assertRaisesMessage(
            ValidationError, "2026-02-30 is not a valid date"
        ):
            validate_date("2026-02-30")
