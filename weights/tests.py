import contextlib
import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .management.commands import fetch_fitbod_images
from .management.commands.fetch_fitbod_images import (
    IMAGES,
    Command as FetchFitbodImagesCommand,
    _holders,
    _is_foreign,
)
from .management.commands.import_fitbod_exercises import FITBOD_DIR, _load
from .models import Exercise

CDN_IMAGE = "https://equipment-pngs.fitbod.me/0.png"

# The bundled Fitbod files, and the exercise count in the catalogue.
BUNDLED_FILES = [
    "exercises.json",
    "equipment.json",
    "muscle_groups.json",
    "exercise_categories.json",
    "exercise_equipment.json",
    "exercise_primary_muscle_groups.json",
    "exercise_secondary_muscle_groups.json",
    "exercise_categorizations.json",
    "exercise_instructions_metadata.json",
]
BUNDLED_EXERCISE_COUNT = 1406


def _dump(directory, filename, rows):
    (Path(directory) / filename).write_text(json.dumps({"data": rows}), encoding="utf-8")


def _related(resource, resource_id):
    """A JSON:API relationship in the shape the bundled app tables use."""
    return {"links": {"related": f"/api/v3/{resource}/{resource_id}"}}


def _join(resource, exercise_id, link_key, other_id):
    return {
        "id": f"{resource}-{exercise_id}-{other_id}",
        "type": resource,
        "relationships": {
            "exercise": _related("exercises", exercise_id),
            link_key: _related(link_key if link_key != "muscle_group" else "muscle_groups", other_id),
        },
    }


def _exercise(exercise_id, name, **attributes):
    base = {
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "external_resource_id": int(exercise_id),
        "level": 1,
        "movement_pattern": None,
        "mobility_type": "none",
        "body_tier": 0,
        "is_bodyweight": False,
        "is_assisted": False,
        "is_unilateral": False,
        "is_cardio": False,
        "is_timed": False,
        "is_distance": False,
        "is_web_published": True,
        "exercise_alias": "",
        "rating": 3,
        "tone_rating": 2,
        "oly_rating": 1,
        "tier": 0,
        "oly_tier": 0,
        "power_tier": 0,
        "relative_weight": None,
        "coefficient": 1,
    }
    base.update(attributes)
    return {"id": str(exercise_id), "type": "exercises", "attributes": base}


class ExerciseModelTests(TestCase):
    def test_str_and_list_fields(self):
        exercise = Exercise.objects.create(
            fitbod_id="101",
            external_resource_id=24,
            name="Leg Press",
            slug="leg-press",
            alias="Leg Sled",
            level=1,
            categories=["weighted"],
            equipment=["Leg Press Machine"],
            primary_muscles=["Quadriceps"],
            secondary_muscles=["Glutes", "Hamstrings"],
            instructions="Sit down.\n\nPress.",
        )
        self.assertEqual(str(exercise), "Leg Press")
        self.assertEqual(list(exercise.equipment), ["Leg Press Machine"])
        self.assertEqual(list(exercise.secondary_muscles), ["Glutes", "Hamstrings"])
        self.assertEqual(exercise.imported_at is not None, True)


class ImportFitbodExercisesCommandTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = self._tmp.name

    def test_joins_the_reference_tables(self):
        _dump(
            self.directory,
            "exercises.json",
            [_exercise("101", "Leg Press"), _exercise("202", "Back Extension")],
        )
        _dump(
            self.directory,
            "equipment.json",
            [
                {"id": "3", "attributes": {"name": "Leg Press Machine"}},
                {"id": "4", "attributes": {"name": "Barbells"}},
            ],
        )
        _dump(
            self.directory,
            "muscle_groups.json",
            [
                {"id": "8", "attributes": {"name": "Quadriceps"}},
                {"id": "7", "attributes": {"name": "Glutes"}},
                {"id": "2", "attributes": {"name": "Abs"}},
            ],
        )
        _dump(
            self.directory,
            "exercise_categories.json",
            [{"id": "2", "attributes": {"name": "weighted"}}],
        )
        _dump(
            self.directory,
            "exercise_equipment.json",
            [_join("exercise_equipment", "101", "equipment", "3")],
        )
        _dump(
            self.directory,
            "exercise_primary_muscle_groups.json",
            [_join("exercise_primary_muscle_groups", "101", "muscle_group", "8")],
        )
        _dump(
            self.directory,
            "exercise_secondary_muscle_groups.json",
            [
                _join("exercise_secondary_muscle_groups", "101", "muscle_group", "7"),
                _join("exercise_secondary_muscle_groups", "101", "muscle_group", "7"),
                _join("exercise_secondary_muscle_groups", "202", "muscle_group", "2"),
            ],
        )
        _dump(
            self.directory,
            "exercise_categorizations.json",
            [_join("exercise_categorizations", "101", "exercise_category", "2")],
        )
        _dump(
            self.directory,
            "exercise_instructions_metadata.json",
            [
                {
                    "id": "4101780",
                    "type": "exercise_instructions_metadata",
                    "attributes": {
                        "instructions": "Sit down.\r\n\r\nPress the sled away.",
                        "image_url": "https://exercise-jpgs.fitbod.me/95.jpg",
                        "animation_url": "https://exercise-gifs.fitbod.me/95.gif",
                        "video_url": None,
                        "full_website_name": "https://fitbod.me/exercises/leg-press",
                    },
                    "relationships": {"exercise": _related("exercises", "101")},
                }
            ],
        )

        call_command("import_fitbod_exercises", directory=self.directory)

        self.assertEqual(Exercise.objects.count(), 2)
        leg_press = Exercise.objects.get(slug="leg-press")
        self.assertEqual(leg_press.fitbod_id, "101")
        self.assertEqual(leg_press.equipment, ["Leg Press Machine"])
        self.assertEqual(leg_press.primary_muscles, ["Quadriceps"])
        # The duplicate join row is folded into one entry.
        self.assertEqual(leg_press.secondary_muscles, ["Glutes"])
        self.assertEqual(leg_press.categories, ["weighted"])
        # CRLF is normalised so the text reads correctly wherever it is shown.
        self.assertEqual(leg_press.instructions, "Sit down.\n\nPress the sled away.")
        self.assertEqual(leg_press.reference_url, "https://fitbod.me/exercises/leg-press")
        self.assertEqual(leg_press.image_url, "https://exercise-jpgs.fitbod.me/95.jpg")
        self.assertEqual(leg_press.animation_url, "https://exercise-gifs.fitbod.me/95.gif")
        self.assertEqual(leg_press.video_url, "")
        # The untouched resource is kept.
        self.assertEqual(leg_press.raw["id"], "101")

        # An exercise with no join rows at all still imports.
        back_extension = Exercise.objects.get(slug="back-extension")
        self.assertEqual(back_extension.equipment, [])
        self.assertEqual(back_extension.primary_muscles, [])
        self.assertEqual(back_extension.secondary_muscles, ["Abs"])
        self.assertEqual(back_extension.instructions, "")

    def test_reimport_updates_rather_than_duplicating(self):
        _dump(self.directory, "exercises.json", [_exercise("101", "Leg Press")])
        call_command("import_fitbod_exercises", directory=self.directory)
        self.assertEqual(Exercise.objects.count(), 1)

        _dump(
            self.directory,
            "exercises.json",
            [_exercise("101", "Leg Press", level=2, rating=5)],
        )
        call_command("import_fitbod_exercises", directory=self.directory)

        self.assertEqual(Exercise.objects.count(), 1)
        exercise = Exercise.objects.get()
        self.assertEqual(exercise.level, 2)
        self.assertEqual(exercise.rating, 5)

    def test_exercise_without_a_slug_gets_one(self):
        payload = _exercise("4099302", "Foam Roll Chest - Alternative")
        del payload["attributes"]["slug"]
        _dump(self.directory, "exercises.json", [payload])

        call_command("import_fitbod_exercises", directory=self.directory)

        exercise = Exercise.objects.get()
        self.assertEqual(exercise.slug, "foam-roll-chest-alternative")
        self.assertEqual(exercise.fitbod_id, "4099302")

    def test_live_api_relationship_shape_is_accepted(self):
        """The live API nests the id under ``data`` instead of ``links``."""
        _dump(self.directory, "exercises.json", [_exercise("101", "Leg Press")])
        _dump(
            self.directory,
            "muscle_groups.json",
            [{"id": "8", "attributes": {"name": "Quadriceps"}}],
        )
        _dump(
            self.directory,
            "exercise_primary_muscle_groups.json",
            [
                {
                    "id": "1",
                    "type": "exercise_primary_muscle_groups",
                    "relationships": {
                        "exercise": {"data": {"id": "101"}},
                        "muscle_group": {"data": {"id": "8"}},
                    },
                }
            ],
        )

        call_command("import_fitbod_exercises", directory=self.directory)

        self.assertEqual(Exercise.objects.get().primary_muscles, ["Quadriceps"])

    def test_missing_directory_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "Fitbod directory not found"):
            call_command("import_fitbod_exercises", directory="/nope/not/here")

    def test_empty_catalogue_is_an_error(self):
        _dump(self.directory, "exercises.json", [])
        with self.assertRaisesMessage(CommandError, "No exercises found"):
            call_command("import_fitbod_exercises", directory=self.directory)

    def test_missing_catalogue_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "Missing Fitbod file"):
            call_command("import_fitbod_exercises", directory=self.directory)


class BundledFitbodDataTests(TestCase):
    """The JSON copied out of the APK has to stay where the command expects."""

    def test_bundled_files_are_present(self):
        for filename in BUNDLED_FILES:
            self.assertTrue((FITBOD_DIR / filename).is_file(), filename)

    def test_bundled_catalogue_parses(self):
        rows = _load(FITBOD_DIR / "exercises.json")
        self.assertEqual(len(rows), BUNDLED_EXERCISE_COUNT)
        self.assertTrue(all(row.get("attributes") for row in rows))
        self.assertTrue(all(row["attributes"].get("name") for row in rows))

    def test_bundled_image_urls_are_local(self):
        """fetch_fitbod_images has run, so the pictures are served by us."""
        for filename in IMAGES:
            payload = json.loads(
                (FITBOD_DIR / filename).read_text(encoding="utf-8")
            )
            urls = [
                holder["image_url"]
                for holder in _holders(payload)
                if holder.get("image_url")
            ]
            self.assertTrue(urls, filename)

            # Fitbod's CDN is missing (404) or blocks (403) a handful of these
            # images outright, so those few are left pointing at Fitbod.
            unavailable = [url for url in urls if _is_foreign(url, set())]
            self.assertLess(len(unavailable), len(urls) / 10, unavailable[:5])

            # An empty set of "our" hosts makes every absolute URL foreign.
            for url in urls:
                if _is_foreign(url, set()):
                    continue
                self.assertTrue(url.startswith(settings.STATIC_URL), url)
                relative = url[len(settings.STATIC_URL) :]
                self.assertTrue(
                    (Path(settings.STATIC_ROOT) / relative).is_file(), url
                )


class FetchFitbodImagesCommandTests(TestCase):
    """The downloads are stubbed at ``_download``; nothing here hits the network."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.directory = self.root / "fitbod"
        self.directory.mkdir()
        self.static_root = self.root / "static"

    def _write(self, rows, filename="equipment.json"):
        (self.directory / filename).write_text(
            json.dumps({"data": rows}), encoding="utf-8"
        )

    def _read(self, filename="equipment.json"):
        payload = json.loads((self.directory / filename).read_text(encoding="utf-8"))
        return [
            holder["image_url"]
            for holder in _holders(payload)
            if holder.get("image_url")
        ]

    def _run(self, download=None, allowed_hosts=("testserver",), **options):
        """Run the command, stubbing the network, and return the fetched URLs."""
        fetched = []

        def fake(url, target):
            fetched.append(url)
            if download is not None:
                download(url, target)
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"image-bytes")

        with self.settings(
            STATIC_ROOT=self.static_root, ALLOWED_HOSTS=list(allowed_hosts)
        ):
            with patch.object(
                FetchFitbodImagesCommand, "_download", side_effect=fake
            ):
                call_command(
                    "fetch_fitbod_images", directory=str(self.directory), **options
                )
        return fetched

    def test_downloads_a_foreign_image_and_points_the_json_at_it(self):
        self._write(
            [
                {
                    "id": "1",
                    "attributes": {
                        "name": "Barbells",
                        "image_url": "https://equipment-pngs.fitbod.me/0.png",
                    },
                },
                {
                    "id": "2",
                    "attributes": {
                        "name": "Box",
                        "image_url": "/static/weights/equipment/9.png",
                    },
                },
            ]
        )

        fetched = self._run()

        self.assertEqual(fetched, ["https://equipment-pngs.fitbod.me/0.png"])
        self.assertTrue((self.static_root / "weights/equipment/0.png").is_file())
        self.assertEqual(
            self._read(),
            ["/static/weights/equipment/0.png", "/static/weights/equipment/9.png"],
        )

    def test_a_second_run_finds_nothing_to_do(self):
        self._write(self._equipment_row("https://equipment-pngs.fitbod.me/0.png"))

        self._run()
        fetched = self._run()

        self.assertEqual(fetched, [])
        self.assertEqual(self._read(), ["/static/weights/equipment/0.png"])

    def test_an_image_already_on_disk_is_reused(self):
        """A run interrupted before the JSON was rewritten picks up where it left off."""
        self._write(self._equipment_row(CDN_IMAGE))
        stuck = self.static_root / "weights/equipment/0.png"
        stuck.parent.mkdir(parents=True)
        stuck.write_bytes(b"image-bytes")

        fetched = self._run()

        self.assertEqual(fetched, [])
        self.assertEqual(stuck.read_bytes(), b"image-bytes")
        self.assertEqual(self._read(), ["/static/weights/equipment/0.png"])

    def test_a_failed_download_leaves_the_remote_url_alone(self):
        self._write(self._equipment_row("https://equipment-pngs.fitbod.me/0.png"))

        def boom(url, target):
            raise urllib.error.URLError("no route to host")

        self._run(download=boom)

        self.assertEqual(
            self._read(), ["https://equipment-pngs.fitbod.me/0.png"]
        )
        self.assertFalse((self.static_root / "weights/equipment/0.png").exists())

    def test_an_image_on_our_own_host_is_left_alone(self):
        self._write(self._equipment_row("https://glute.example/0.png"))

        fetched = self._run(allowed_hosts=["glute.example"])

        self.assertEqual(fetched, [])
        self.assertEqual(self._read(), ["https://glute.example/0.png"])

    def test_instructions_images_go_to_the_exercises_folder(self):
        self._write(
            [
                {
                    "id": "4101780",
                    "attributes": {
                        "image_url": "https://exercise-jpgs.fitbod.me/95.jpg",
                        "animation_url": "https://exercise-gifs.fitbod.me/95.gif",
                        "video_url": "https://exercise-mp4s.fitbod.me/95.mp4",
                    },
                }
            ],
            filename="exercise_instructions_metadata.json",
        )

        fetched = self._run()

        self.assertEqual(fetched, ["https://exercise-jpgs.fitbod.me/95.jpg"])
        self.assertTrue((self.static_root / "weights/exercises/95.jpg").is_file())
        self.assertEqual(
            self._read("exercise_instructions_metadata.json"),
            ["/static/weights/exercises/95.jpg"],
        )

    def test_video_and_animation_urls_are_not_touched(self):
        self._write(
            [
                {
                    "id": "4101780",
                    "attributes": {
                        "animation_url": "https://exercise-gifs.fitbod.me/95.gif",
                        "video_url": "https://exercise-mp4s.fitbod.me/95.mp4",
                    },
                }
            ],
            filename="exercise_instructions_metadata.json",
        )

        fetched = self._run()

        self.assertEqual(fetched, [])
        payload = json.loads(
            (self.directory / "exercise_instructions_metadata.json").read_text()
        )
        attributes = payload["data"][0]["attributes"]
        self.assertEqual(
            attributes["animation_url"], "https://exercise-gifs.fitbod.me/95.gif"
        )
        self.assertEqual(
            attributes["video_url"], "https://exercise-mp4s.fitbod.me/95.mp4"
        )

    def test_the_local_url_follows_static_url(self):
        self._write(self._equipment_row("https://equipment-pngs.fitbod.me/0.png"))

        with self.settings(STATIC_URL="/assets/"):
            self._run()

        self.assertEqual(self._read(), ["/assets/weights/equipment/0.png"])

    def test_missing_directory_is_an_error(self):
        with self.assertRaisesMessage(CommandError, "Fitbod directory not found"):
            call_command("fetch_fitbod_images", directory="/nope/not/here")

    def test_a_url_with_no_filename_is_left_alone(self):
        self._write(self._equipment_row("https://equipment-pngs.fitbod.me/.png"))

        fetched = self._run()

        self.assertEqual(fetched, [])
        self.assertEqual(self._read(), ["https://equipment-pngs.fitbod.me/.png"])
        self.assertFalse((self.static_root / "weights/equipment/.png").exists())

    @staticmethod
    def _equipment_row(image_url):
        return [
            {"id": "1", "attributes": {"name": "Barbells", "image_url": image_url}}
        ]

    def test_a_throttled_download_is_retried(self):
        """Cloudflare 403s a share of requests; the retry is what saves them."""
        self._write(self._equipment_row(CDN_IMAGE))
        urlopen = Mock(
            side_effect=_next_response(
                [
                    _http_error(403),
                    _http_error(403),
                    _FakeResponse(b"image-bytes"),
                ]
            )
        )

        with self._no_network_pauses():
            with patch.object(urllib.request, "urlopen", urlopen):
                call_command(
                    "fetch_fitbod_images", directory=str(self.directory)
                )

        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(
            (self.static_root / "weights/equipment/0.png").read_bytes(),
            b"image-bytes",
        )
        self.assertEqual(self._read(), ["/static/weights/equipment/0.png"])

    def test_a_missing_image_is_not_retried(self):
        self._write(self._equipment_row(CDN_IMAGE))
        urlopen = Mock(side_effect=_next_response([_http_error(404)]))

        with self._no_network_pauses():
            with patch.object(urllib.request, "urlopen", urlopen):
                call_command(
                    "fetch_fitbod_images", directory=str(self.directory)
                )

        self.assertEqual(urlopen.call_count, 1)
        # The URL is left alone rather than broken, and nothing was written.
        self.assertEqual(self._read(), [CDN_IMAGE])
        self.assertFalse((self.static_root / "weights/equipment/0.png").exists())

    def test_a_giving_up_download_leaves_no_half_written_file(self):
        self._write(self._equipment_row(CDN_IMAGE))
        urlopen = Mock(
            side_effect=_next_response([_http_error(403) for _ in range(99)])
        )

        with self._no_network_pauses():
            with patch.object(urllib.request, "urlopen", urlopen):
                call_command(
                    "fetch_fitbod_images", directory=str(self.directory)
                )

        self.assertEqual(urlopen.call_count, fetch_fitbod_images.ATTEMPTS)
        self.assertEqual(self._read(), [CDN_IMAGE])
        self.assertFalse((self.static_root / "weights/equipment/0.png").exists())

    def _no_network_pauses(self):
        """The test settings plus the module's sleeps disabled."""
        stack = contextlib.ExitStack()
        stack.enter_context(
            self.settings(STATIC_ROOT=self.static_root, ALLOWED_HOSTS=["testserver"])
        )
        stack.enter_context(patch.object(fetch_fitbod_images, "RETRY_PAUSE", 0))
        stack.enter_context(patch.object(fetch_fitbod_images, "REQUEST_PAUSE", 0))
        return stack


class _FakeResponse:
    """Just enough of an HTTP response for ``_fetch``."""

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def read(self):
        return self.payload


def _http_error(status):
    return urllib.error.HTTPError(CDN_IMAGE, status, "blocked", {}, None)


def _next_response(results):
    """A ``urlopen`` replacement that plays ``results`` back in order."""

    def urlopen(request, timeout=None):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return urlopen
