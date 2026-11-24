"""Genesis surround view: read the stored capture and request a new one.

These tests mock the HTTP layer, so no Genesis account or car is needed.
"""

from __future__ import annotations

import base64
import sys
import unittest

from aiohttp import ClientError

from test_genesis_polling import (
    PINLockedError,
    UsGenesis,
    _JsonResponse,
    _ready_api,
)

_util = sys.modules["ha_kia_hyundai.kia_hyundai_api.util"]


def _capture(time: str, image: bytes = b"jpeg") -> dict:
    return {
        "svmDetail": {
            "svmImage": base64.b64encode(image).decode(),
            "gpsDetail": {"time": time},
        }
    }


class GenesisSurroundViewTests(unittest.IsolatedAsyncioTestCase):
    def _install(self, api: UsGenesis, get_handler, post_handler=None):
        gets: list[str] = []
        posts: list[tuple[str, dict]] = []

        async def fake_get(url, headers=None):
            gets.append(url)
            result = get_handler(url)
            if isinstance(result, Exception):
                raise result
            return result

        async def fake_post(url, json_body=None, headers=None):
            posts.append((url, json_body))
            result = post_handler(url) if post_handler else _JsonResponse({"tid": "t"})
            if isinstance(result, Exception):
                raise result
            return result

        api._get_request_with_logging_and_errors_raised = fake_get
        api._post_request_with_logging_and_errors_raised = fake_post
        return gets, posts

    async def test_read_returns_the_newest_stored_capture(self):
        api = _ready_api()
        self._install(api, lambda url: _JsonResponse({"svmDetails": [
            _capture("20261108013654", b"older"),
            _capture("20261124040411", b"newest"),
            _capture("20261103122809", b"oldest"),
        ]}))

        capture = await api.get_surround_view("reg1")

        self.assertEqual(capture["image"], b"newest")
        self.assertEqual(capture["captured_at"], "20261124040411")

    async def test_read_returns_none_when_nothing_is_stored(self):
        api = _ready_api()
        self._install(api, lambda url: _JsonResponse({"svmDetails": []}))

        self.assertIsNone(await api.get_surround_view("reg1"))

    async def test_capture_sends_one_request_and_returns_the_new_image(self):
        api = _ready_api()
        stored = [_capture("20261112143620", b"old")]

        def post_handler(url):
            # The car uploads the new capture after the request is accepted.
            stored.insert(0, _capture("20261124040411", b"new"))
            return _JsonResponse({"tid": "t"})

        gets, posts = self._install(
            api, lambda url: _JsonResponse({"svmDetails": list(stored)}), post_handler
        )

        previous = await api.request_surround_view_capture("reg1")
        capture = await api.wait_for_surround_view("reg1", previous, poll_interval=0)

        self.assertEqual(previous, "20261112143620")
        self.assertEqual(capture["image"], b"new")
        self.assertEqual(len(posts), 1)
        url, body = posts[0]
        self.assertTrue(url.endswith("svm/findMyCarSVM"))
        self.assertEqual(body["blueLinkServicePin"], "1234")
        self.assertEqual(body["vin"], "KMTTESTVIN0000001")
        self.assertTrue(all(get.endswith("svm/getSVMDetails") for get in gets))

    async def test_refused_capture_request_is_raised_and_not_repeated(self):
        api = _ready_api()
        gets, posts = self._install(
            api,
            lambda url: _JsonResponse({"svmDetails": [_capture("20261112143620")]}),
            lambda url: ClientError(
                "BlueLink API error: You have exceeded the daily remote service request limit."
            ),
        )

        with self.assertRaises(ClientError):
            await api.request_surround_view_capture("reg1")

        self.assertEqual(len(posts), 1)

    async def test_wait_gives_up_when_no_new_capture_arrives(self):
        api = _ready_api()
        self._install(
            api, lambda url: _JsonResponse({"svmDetails": [_capture("20261112143620")]})
        )

        capture = await api.wait_for_surround_view(
            "reg1", "20261112143620", poll_interval=0, timeout=0.02
        )

        self.assertIsNone(capture)

    async def test_wait_keeps_going_after_a_temporary_error(self):
        api = _ready_api()
        replies = [
            ClientError("BlueLink API error: please try again later"),
            _JsonResponse({"svmDetails": [_capture("20261124040411", b"new")]}),
        ]
        self._install(api, lambda url: replies.pop(0))

        capture = await api.wait_for_surround_view(
            "reg1", "20261112143620", poll_interval=0
        )

        self.assertEqual(capture["image"], b"new")

    async def test_wait_stops_on_a_pin_error(self):
        api = _ready_api()
        gets, _ = self._install(
            api,
            lambda url: PINLockedError("BlueLink PIN locked: locked for 5 minutes."),
        )

        with self.assertRaises(PINLockedError):
            await api.wait_for_surround_view("reg1", None, poll_interval=0)

        self.assertEqual(len(gets), 1)

    async def test_startup_read_is_not_repeated_after_a_pin_error(self):
        api = _ready_api()
        gets, _ = self._install(
            api,
            lambda url: PINLockedError("BlueLink PIN locked: locked for 5 minutes."),
        )

        with self.assertRaises(PINLockedError):
            await api.get_surround_view("reg1", background_poll=True)
        with self.assertRaises(PINLockedError):
            await api.get_surround_view("reg1", background_poll=True)

        self.assertEqual(len(gets), 1)


class SurroundViewLogMaskingTests(unittest.TestCase):
    def test_image_data_is_masked_in_logged_dictionaries(self):
        cleaned = _util.clean_dictionary_for_logging({
            "svmDetails": [{"svmDetail": {"svmImage": "AAAA", "trunkOpen": "false"}}],
        })

        detail = cleaned["svmDetails"][0]["svmDetail"]
        self.assertEqual(detail["svmImage"], "***")
        self.assertEqual(detail["trunkOpen"], "false")


if __name__ == "__main__":
    unittest.main()
