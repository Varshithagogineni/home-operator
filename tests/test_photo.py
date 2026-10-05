"""Reading an appliance label: trusted only when it looks like a real model number."""

from home_operator import photo


def test_a_clear_label_is_read():
    r = photo.parse('{"found": true, "kind": "Dryer", "brand": "Bosch", "model_number": "wtg86403uc", "serial_number": "FD 9512"}')
    assert r["found"] and r["brand"] == "Bosch" and r["model_number"] == "WTG86403UC" and r["kind"] == "dryer"


def test_the_model_saying_it_could_not_read_it_is_respected():
    r = photo.parse('{"found": false, "unsure": "model number is blurred"}')
    assert not r["found"] and "blurred" in r["unsure"]


def test_a_guess_that_is_not_a_model_number_is_refused():
    for bad in ("unknown", "N/A", "12345", "ABCDEFG", ""):
        r = photo.parse('{"found": true, "kind": "dryer", "brand": "Bosch", "model_number": "%s"}' % bad)
        assert not r["found"], bad


def test_no_brand_means_no_appliance():
    assert not photo.parse('{"found": true, "kind": "dryer", "brand": "", "model_number": "WTG86403UC"}')["found"]


def test_prose_around_the_json_is_tolerated_and_garbage_is_not():
    assert photo.parse('Here it is: {"found": true, "kind": "washer", "brand": "LG", "model_number": "WM9500HKA"} done')["found"]
    assert not photo.parse("I think it's an LG washer")["found"]


def test_unsupported_images_are_refused_before_any_model_call():
    class Boom:
        def converse(self, **_):
            raise AssertionError("should not be called")
    assert not photo.read_label(b"...", "image/tiff", client=Boom())["found"]


def test_a_browser_data_url_is_decoded():
    image, media = photo.decode_upload(b"data:image/jpeg;base64,aGVsbG8=", "text/plain")
    assert image == b"hello" and media == "image/jpeg"


def test_the_recall_check_reports_a_failure_rather_than_saying_all_clear():
    def down(_):
        raise TimeoutError
    r = photo.recall_check({"brand": "Bosch", "model_number": "WTG86403UC", "category": "dryer"}, fetch=down)
    assert r == {"checked": False, "error": "TimeoutError"}
