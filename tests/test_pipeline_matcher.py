from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.matcher import MATCH_THRESHOLD, clean_album, find_best_release, normalise_title, track_title_score
from app.pipeline.probe import ProbeResult
from app.types import MBCandidate, MBCandidateDetail, TrackDetail


def _candidate(mb_id: str, track_count: int, score: int = 90) -> MBCandidate:
    return MBCandidate(
        id=mb_id, title="Album", artist="Artist", year="2000",
        country="", label="", score=score, tracks=[], track_count=track_count,
        disambiguation="",
    )


def _detail(mb_id: str, titles: list[str]) -> MBCandidateDetail:
    tracks = [TrackDetail(position=i + 1, title=t) for i, t in enumerate(titles)]
    return MBCandidateDetail(
        id=mb_id, title="Album", artist="Artist", year="2000",
        country="", label="", score=90, tracks=tracks,
        track_count=len(tracks), disambiguation="",
    )


MB_TITLES = ["I'm a Fool to Want You", "For Heaven's Sake", "You Don't Know What Love Is"]


@pytest.mark.parametrize("raw,expected", [
    ("Mellow Gold SHM-CD", "Mellow Gold"),
    ("Guero SHM-CD", "Guero"),
    ("Mutations SHM-CD", "Mutations"),
    ("Kind of Blue Remastered", "Kind of Blue"),
    ("Abbey Road (2019 Remaster)", "Abbey Road"),
    ("The Dark Side of the Moon (50th Anniversary Edition)", "The Dark Side of the Moon"),
    ("Nevermind Deluxe Edition", "Nevermind"),
    ("In Utero [Japan Bonus Tracks]", "In Utero"),
    ("Blue (Deluxe Edition)", "Blue"),
    ("Mellow Gold", "Mellow Gold"),  # unchanged — no noise
])
def test_clean_album(raw, expected):
    assert clean_album(raw) == expected


def test_normalise_track_number():
    assert normalise_title("01 - Track One") == normalise_title("Track One")


def test_normalise_punctuation():
    assert normalise_title("Don't Worry 'bout Me (T.Koehler)") == normalise_title("Dont Worry bout Me TKoehler")


def test_normalise_case():
    assert normalise_title("STRANGE FRUIT") == normalise_title("strange fruit")


def test_track_title_score_exact():
    score = track_title_score(MB_TITLES, MB_TITLES)
    assert score == 1.0


def test_track_title_score_partial():
    local = ["Track A", "Track B", "Track C"]
    mb = ["Track A", "Track B", "Track X", "Track Y", "Track Z"]
    score = track_title_score(local, mb)
    assert score == pytest.approx(2 / 5)


def test_track_title_score_empty_mb():
    assert track_title_score(["Track A"], []) == 0.0


def test_track_title_score_normalisation_differences():
    local = ["01 - Don't Worry 'bout Me (T.Koehler)"]
    mb = ["Don't Worry 'bout Me"]
    assert track_title_score(local, mb) == 1.0


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_exact_match(mock_search, mock_detail):
    probe = ProbeResult(artist="Billie Holiday", album="Lady in Satin",
                        track_count=3, track_titles=MB_TITLES)
    mock_search.return_value = [_candidate("mb-123", track_count=3)]
    mock_detail.return_value = _detail("mb-123", MB_TITLES)

    result = find_best_release(probe)
    assert result == "mb-123"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_good_match(mock_search, mock_detail):
    probe = ProbeResult(artist="Artist", album="Album", track_count=10,
                        track_titles=[f"Track {i}" for i in range(10)])
    mb_titles = [f"Track {i}" for i in range(10)]
    mb_titles[9] = "Bonus Track (Hidden)"  # 9/10 match = 0.90 >= threshold
    mock_search.return_value = [_candidate("mb-456", track_count=10)]
    mock_detail.return_value = _detail("mb-456", mb_titles)

    result = find_best_release(probe)
    assert result == "mb-456"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_poor_match_returns_none(mock_search, mock_detail):
    probe = ProbeResult(artist="Artist", album="Album", track_count=10,
                        track_titles=[f"Track {i}" for i in range(10)])
    mb_titles = [f"Different {i}" for i in range(10)]  # 0% match
    mock_search.return_value = [_candidate("mb-789", track_count=10)]
    mock_detail.return_value = _detail("mb-789", mb_titles)

    result = find_best_release(probe)
    assert result is None


@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_empty_results(mock_search):
    mock_search.return_value = []
    probe = ProbeResult(artist="Artist", album="Album", track_count=5,
                        track_titles=["T1", "T2", "T3", "T4", "T5"])
    assert find_best_release(probe) is None


@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_track_count_filter_too_few(mock_search):
    probe = ProbeResult(artist="Artist", album="Album", track_count=10,
                        track_titles=[f"T{i}" for i in range(10)])
    # MB has 5 tracks, we have 10 — difference >3, filtered out
    mock_search.return_value = [_candidate("mb-bad", track_count=5)]
    result = find_best_release(probe)
    assert result is None


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_bonus_tracks_allowed(mock_search, mock_detail):
    # We have 16 tracks (13 standard + 3 Japan bonus); MB standard has 13.
    # Should still match the 13-track release.
    std_titles = [f"Track {i}" for i in range(13)]
    probe = ProbeResult(artist="Beck", album="Guero SHM-CD", track_count=16,
                        track_titles=std_titles + ["Japan Bonus 1", "Japan Bonus 2", "Japan Bonus 3"])
    mock_search.return_value = [_candidate("mb-guero", track_count=13)]
    mock_detail.return_value = _detail("mb-guero", std_titles)

    result = find_best_release(probe)
    assert result == "mb-guero"


@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_no_artist_and_album(mock_search):
    probe = ProbeResult(artist="", album="", track_count=5,
                        track_titles=["T1"])
    result = find_best_release(probe)
    mock_search.assert_not_called()
    assert result is None


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_picks_highest_score(mock_search, mock_detail):
    probe = ProbeResult(artist="Elvis", album="Classics", track_count=3,
                        track_titles=["Jailhouse Rock", "Hound Dog", "Blue Suede Shoes"])
    mock_search.return_value = [
        _candidate("mb-low", track_count=3, score=80),
        _candidate("mb-high", track_count=3, score=95),
    ]

    def detail_side(mb_id):
        if mb_id == "mb-high":
            return _detail("mb-high", ["Jailhouse Rock", "Hound Dog", "Blue Suede Shoes"])
        return _detail("mb-low", ["Other Track", "Another", "More"])

    mock_detail.side_effect = detail_side
    result = find_best_release(probe)
    assert result == "mb-high"
