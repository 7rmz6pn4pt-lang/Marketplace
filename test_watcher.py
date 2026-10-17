"""Offline tests for the matching and location rules:  python -m pytest -q"""
import pytest

import watcher as w

CFG = w.load_config(w.CONFIG_PATH)


def ev(title, desc=""):
    lst = w.Listing(source="t", url="https://x/1", title=title, description=desc)
    ok = w.evaluate(lst, CFG["match"])
    return ok, lst.labels, lst.reject_reason


@pytest.mark.parametrize("title,desc,labels", [
    ("Trek Domane AL 3 Disc 58cm", "", ["58 CM", "DISC"]),
    ("Trek Domane AL3 2022", "size 58, thru axle", ["58 CM", "DISC", "GEN 3+"]),
    ("TREK DOMANE AL-3 Gen 3 road bike", "Frame size XL", ["58 CM", "DISC", "GEN 3+"]),
    ("Trek road bike", "Domane AL 3 disc, 58 cm frame", ["58 CM", "DISC"]),
    ("Trek Domane AL 3", "Great condition, Shimano Sora", ["SIZE UNKNOWN", "CHECK BRAKES"]),
    ("Trek Domane AL 3", "Listed 12/10/2026. Shimano Sora", ["SIZE UNKNOWN", "CHECK BRAKES"]),
    ("Trek Domane AL 3", "Model year: 2021, 58cm", ["58 CM", "DISC"]),
    ("Trek Domane AL 3 disc", "Not rim brakes - hydraulic disc", ["SIZE UNKNOWN", "CHECK BRAKES"]),
])
def test_matches(title, desc, labels):
    ok, got, why = ev(title, desc)
    assert ok, why
    for l in labels:
        assert l in got


@pytest.mark.parametrize("title,desc,reason", [
    ("Trek Domane SL 5 58cm disc", "", "not an AL 3"),
    ("Trek Domane SLR 6", "AL 3 owners will love this", "excluded"),
    ("Trek Domane AL 2 Disc 58", "", "not an AL 3"),       # AL 3 nowhere
    ("Trek Domane AL 4 58cm", "upgrade over the al 3", "excluded"),
    ("Trek Domane AL 3 frameset", "58cm disc", "excluded"),
    ("WANTED: Trek Domane AL 3 58cm", "", "excluded"),
    ("Trek Domane AL 3 58cm", "Rim brakes, Tiagra", "rim brake"),
    ("Trek Domane AL 3 disc", "Frame size 54cm", "other size"),
    ("Trek Domane AL 3 disc", "Size: M", "other size"),
    ("Trek Emonda AL 3 58cm", "", "no 'domane'"),
    ("Trek Domane AL 30", "", "not an AL 3"),
])
def test_rejects(title, desc, reason):
    ok, _, why = ev(title, desc)
    assert not ok
    assert reason in why


def test_price_not_a_size():
    ok, labels, _ = ev("Trek Domane AL 3 disc", "$580 ono")
    assert ok and "SIZE UNKNOWN" in labels


def loc(card, url="https://x/1", server=False):
    lst = w.Listing(source="t", url=url, title="t", card_text=card)
    return w.locate(lst, CFG, server), lst


def test_location_near():
    ok, lst = loc("Trek Domane\n$900\nSouth Yarra, VIC 3141")
    assert ok and lst.location == "South Yarra VIC" and lst.distance_km < 3


def test_location_far_vic_dropped():
    ok, _ = loc("Trek Domane\n$900\nFrankston, VIC 3199")
    assert not ok


def test_location_other_state_dropped():
    ok, _ = loc("Trek Domane\n$900\nBondi, NSW 2026")
    assert not ok


def test_location_unknown_kept_with_label():
    ok, lst = loc("Trek Domane $900")
    assert ok and "CHECK LOCATION" in lst.labels


def test_gumtree_suburb_from_url():
    ok, lst = loc("Trek Domane $900", url="https://www.gumtree.com.au/s-ad/fitzroy-north/road-bikes/trek/123", server=True)
    assert ok and lst.location.startswith("Fitzroy North")


def test_canonical_ebay():
    assert w.canonical("https://www.ebay.com.au/itm/Trek-Domane/2345678901?hash=x") == "https://www.ebay.com.au/itm/2345678901"


def test_no_results_marker():
    assert w.NO_RESULT_RE.search("sorry, 0 results for trek domane")
    assert not w.NO_RESULT_RE.search("showing 10 results")
