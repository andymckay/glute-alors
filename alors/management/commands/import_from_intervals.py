"""Download the original FIT files for the latest intervals.icu activities.

Uses the intervals.icu REST API with the API key stored in the
``INTERVALS_TOKEN`` environment variable (read into
``settings.INTERVALS_TOKEN``).  The most recent activities are listed and each
one's original file is downloaded into the ``data`` directory as
``<activity_id>.fit``, ready for ``import_workout``.
"""

import base64
import json
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

API_BASE = "https://intervals.icu/api/v1"
# Endpoints that accept an athlete id treat "0" as "the athlete the API key
# belongs to".
ATHLETE_ID = "0"
DEFAULT_LIMIT = 7
# Cloudflare sometimes challenges plain Python user agents, so look like a
# browser.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


class Command(BaseCommand):
    help = (
        "Check intervals.icu for the latest activities and download each "
        "original FIT file into the data directory."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help="How many of the most recent activities to check "
            f"(default: {DEFAULT_LIMIT}).",
        )
        parser.add_argument(
            "--oldest",
            default=None,
            help="ISO date lower bound for the search window "
            "(default: one year ago).",
        )
        parser.add_argument(
            "--data-dir",
            default=str(settings.BASE_DIR / "data"),
            help="Directory to save the downloaded .fit files into.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download files that are already present.",
        )

    def handle(self, *args, **options):
        token = settings.INTERVALS_TOKEN
        if not token:
            raise CommandError(
                "No intervals.icu API key found. Set the INTERVALS_TOKEN "
                "environment variable."
            )

        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be at least 1.")
        oldest = (
            options["oldest"]
            or (timezone.localdate() - timedelta(days=365)).isoformat()
        )

        data_dir = Path(options["data_dir"])
        data_dir.mkdir(parents=True, exist_ok=True)

        activities = self._fetch_activities(token, oldest, limit)
        if not activities:
            self.stdout.write("No activities found.")
            return

        downloaded = 0
        skipped = 0
        without_file = 0
        for activity in activities:
            activity_id = activity.get("id")
            if not activity_id:
                continue
            dest = data_dir / f"{activity_id}.fit"
            if dest.exists() and not options["force"]:
                skipped += 1
                self.stdout.write(f"Skipped {dest.name} (already downloaded).")
                continue

            result = self._download_file(token, activity_id, dest)
            if result == "downloaded":
                downloaded += 1
                self.stdout.write(self.style.SUCCESS(f"Downloaded {dest.name}."))
            else:
                without_file += 1
                self.stdout.write(f"No original file available for {activity_id}.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {downloaded} downloaded, {skipped} already present, "
                f"{without_file} without an original file."
            )
        )

    def _fetch_activities(self, token, oldest, limit):
        """Return the most recent ``limit`` activities as a list of dicts."""
        url = (
            f"{API_BASE}/athlete/{ATHLETE_ID}/activities"
            f"?oldest={oldest}&limit={limit}"
        )

        status, body = self._get(url, token)
        if status != 200:
            raise CommandError(
                f"Intervals.icu returned HTTP {status} while listing "
                f"activities ({url})."
            )

        try:
            activities = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise CommandError(
                "Could not parse the activities response from intervals.icu."
            ) from error
        if not isinstance(activities, list):
            raise CommandError("Unexpected activities response from intervals.icu.")
        return activities

    def _download_file(self, token, activity_id, dest):
        """Download the original activity file to ``dest``.

        Returns ``"downloaded"`` when the file was saved, or ``"no_file"``
        when the activity has no downloadable original file (e.g. it was
        recorded manually or synced from Strava).
        """
        url = f"{API_BASE}/activity/{activity_id}/file"
        status, body = self._get(url, token)
        if status == 200:
            dest.write_bytes(body)
            return "downloaded"
        if status in (400, 404, 409):
            return "no_file"
        raise CommandError(
            f"Intervals.icu returned HTTP {status} while downloading " f"{activity_id}."
        )

    def _get(self, url, token):
        """GET ``url`` and return ``(status_code, body_bytes)``."""
        request = urllib.request.Request(url, headers=self._auth_headers(token))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except urllib.error.URLError as error:
            raise CommandError(
                f"Could not reach intervals.icu: {error.reason}"
            ) from error

    def _auth_headers(self, token):
        """Basic auth headers. The username is always ``API_KEY``."""
        credentials = base64.b64encode(f"API_KEY:{token}".encode()).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "User-Agent": USER_AGENT,
        }
