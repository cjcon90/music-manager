from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.matcher import (
    MATCH_THRESHOLD,
    _album_search_variants,
    _strip_all_noise,
    clean_album,
    find_best_release,
    normalise_title,
    track_title_score,
)
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

# ---------------------------------------------------------------------------
# clean_album — strips _PRESSING only (format/pressing annotations)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    # Format annotations
    ("Who's Next {UK, Sterling}", "Who's Next"),
    ("Tommy {Original UK}", "Tommy"),
    ("Nevermind (LP)", "Nevermind"),
    ("Nevermind [2LP]", "Nevermind"),
    ("Nevermind (CD)", "Nevermind"),
    ("Ziggy Stardust (UK version)", "Ziggy Stardust"),
    ("Exile on Main St. (US pressing)", "Exile on Main St."),
    # Things clean_album does NOT strip (left for tier 2)
    ("Who's Next (Remastered)", "Who's Next (Remastered)"),
    ("Kind of Blue Remastered", "Kind of Blue Remastered"),
    ("Tommy (1 of 2)", "Tommy (1 of 2)"),
    ("Quadrophenia (1991 MFSL Gold) - Disc 1", "Quadrophenia (1991 MFSL Gold) - Disc 1"),
    ("The Who Sell Out (1970 UK Reissue)", "The Who Sell Out (1970 UK Reissue)"),
    # Safe to pass through unchanged
    ("Mellow Gold", "Mellow Gold"),
    ("1999", "1999"),
])
def test_clean_album(raw, expected):
    assert clean_album(raw) == expected


# ---------------------------------------------------------------------------
# _strip_all_noise — strips all bracketed content + disc suffixes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    # The Who problem cases
    ("Who's Next (Remastered)", "Who's Next"),
    ("The Who Sell Out (1970 UK Reissue)", "The Who Sell Out"),
    ("Tommy (1 of 2)", "Tommy"),
    ("Tommy 2 of 2", "Tommy"),
    ("Quadrophenia (1991 MFSL Gold) - Disc 1", "Quadrophenia"),
    ("Quadrophenia (1991 MFSL Gold) - Disc 2", "Quadrophenia"),
    # Other common patterns
    ("Kind of Blue (Legacy Edition)", "Kind of Blue"),
    ("Nevermind (Deluxe Edition)", "Nevermind"),
    ("Abbey Road [2019 Remaster]", "Abbey Road"),
    ("Exile on Main St. {UK, Sterling}", "Exile on Main St."),
    # Must NOT strip — bare numbers that are the title
    ("1999", "1999"),
    ("Heroes", "Heroes"),
    # Must NOT strip — year in title without brackets
    ("Kind of Blue Remastered", "Kind of Blue Remastered"),
])
def test_strip_all_noise(raw, expected):
    assert _strip_all_noise(raw) == expected


# ---------------------------------------------------------------------------
# _album_search_variants — tiered de-duplicated variants
# ---------------------------------------------------------------------------

def test_variants_who_sell_out():
    # Tier 1 unchanged (no pressing annotations), tier 2 strips the bracket
    variants = _album_search_variants("The Who Sell Out (1970 UK Reissue)")
    assert variants[0] == "The Who Sell Out (1970 UK Reissue)"  # tier 1 = unchanged
    assert variants[1] == "The Who Sell Out"                     # tier 2 strips bracket
    # tier 3: first 2 words → "The Who" — included as tier 3
    assert "The Who" in variants


def test_variants_tommy():
    variants = _album_search_variants("Tommy (1 of 2)")
    assert variants[0] == "Tommy (1 of 2)"  # tier 1 unchanged
    assert variants[1] == "Tommy"           # tier 2 strips bracket
    # tier 3: only 1 word → no tier 3
    assert len(variants) == 2


def test_variants_pressing_stripped_in_tier1():
    # {UK, Sterling} is a pressing annotation → tier 1 already cleans it
    variants = _album_search_variants("Who's Next {UK, Sterling}")
    assert variants[0] == "Who's Next"   # tier 1 strips {}
    # tier 2 = same result → deduplicated
    assert all(v != "Who's Next {UK, Sterling}" for v in variants)


def test_variants_no_noise():
    # Clean title → all tiers produce same result → only 1 variant
    variants = _album_search_variants("Mellow Gold")
    assert variants == ["Mellow Gold"]


def test_variants_1999_safe():
    # "1999" must never be mangled
    variants = _album_search_variants("1999")
    assert variants[0] == "1999"


def test_variants_tier3_for_long_title():
    variants = _album_search_variants("Quadrophenia (1991 MFSL Gold) - Disc 1")
    assert "Quadrophenia" in variants      # tier 2
    # "Quadrophenia" is only 1 word → no tier 3 added


# ---------------------------------------------------------------------------
# normalise_title
# ---------------------------------------------------------------------------

def test_normalise_track_number():
    assert normalise_title("01 - Track One") == normalise_title("Track One")


def test_normalise_punctuation():
    assert normalise_title("Don't Worry 'bout Me (T.Koehler)") == normalise_title("Dont Worry bout Me TKoehler")


def test_normalise_case():
    assert normalise_title("STRANGE FRUIT") == normalise_title("strange fruit")


# ---------------------------------------------------------------------------
# track_title_score
# ---------------------------------------------------------------------------

def test_track_title_score_exact():
    assert track_title_score(MB_TITLES, MB_TITLES) == 1.0


def test_track_title_score_partial():
    local = ["Track A", "Track B", "Track C"]
    mb = ["Track A", "Track B", "Track X", "Track Y", "Track Z"]
    assert track_title_score(local, mb) == pytest.approx(2 / 5)


def test_track_title_score_empty_mb():
    assert track_title_score(["Track A"], []) == 0.0


def test_track_title_score_normalisation_differences():
    local = ["01 - Don't Worry 'bout Me (T.Koehler)"]
    mb = ["Don't Worry 'bout Me"]
    assert track_title_score(local, mb) == 1.0


# ---------------------------------------------------------------------------
# find_best_release — tiered search integration
# ---------------------------------------------------------------------------

WHO_NEXT_TRACKS = [
    "Baba O'Riley", "Bargain", "Love Ain't for Keeping",
    "My Wife", "The Song Is Over", "Getting in Tune",
    "Going Mobile", "Behind Blue Eyes", "Won't Get Fooled Again",
]

TOMMY_TRACKS = [
    "Overture", "It's a Boy", "1921", "Amazing Journey", "Sparks",
    "Eyesight to the Blind", "Christmas", "Cousin Kevin", "The Acid Queen",
    "Underture", "Do You Think It's Alright?", "Fiddle About", "Pinball Wizard",
    "There's a Doctor", "Go to the Mirror!", "Tommy Can You Hear Me?",
    "Smash the Mirror", "Sensation",
]

QUAD_DISC1_TRACKS = [
    "I Am the Sea", "The Real Me", "Quadrophenia", "Cut My Hair",
    "The Punk Meets the Godfather", "I'm One", "The Dirty Jobs",
    "Helpless Dancer", "Is It in My Head?", "I've Had Enough",
]

SELL_OUT_TRACKS = [
    "Armenia City in the Sky", "Heinz Baked Beans", "Mary Anne with the Shaky Hand",
    "Odorono", "Tattoo", "Our Love Was", "I Can See for Miles",
    "I Can't Reach You", "Medac", "Relax", "Silas Stingy",
    "Sunrise", "Rael 1 and 2",
]


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_whos_next_remastered_tag_matches_via_tier2(mock_search, mock_detail):
    """Who's Next with (Remastered) in album tag: tier 1 unchanged, tier 2 strips it."""
    probe = ProbeResult(
        artist="The Who",
        album="Who's Next (Remastered)",
        track_count=9,
        track_titles=WHO_NEXT_TRACKS,
    )

    def search_side(query):
        if "Who's Next (Remastered)" in query:
            return []   # tier 1 finds nothing
        if "Who's Next" in query:
            return [_candidate("mb-whos-next", track_count=9)]
        return []

    mock_search.side_effect = search_side
    mock_detail.return_value = _detail("mb-whos-next", WHO_NEXT_TRACKS)

    result = find_best_release(probe)
    assert result == "mb-whos-next"
    assert mock_search.call_count == 2  # tier 1 fails, tier 2 succeeds


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_tommy_n_of_n_matches_via_tier2(mock_search, mock_detail):
    """Tommy (1 of 2): clean_album leaves '(1 of 2)' unchanged; tier 2 strips it."""
    probe = ProbeResult(
        artist="The Who",
        album="Tommy (1 of 2)",
        track_count=18,
        track_titles=TOMMY_TRACKS,
    )

    def search_side(query):
        if "Tommy (1 of 2)" in query:
            return []
        if '"Tommy"' in query:
            return [_candidate("mb-tommy", track_count=18)]
        return []

    mock_search.side_effect = search_side
    mock_detail.return_value = _detail("mb-tommy", TOMMY_TRACKS)

    result = find_best_release(probe)
    assert result == "mb-tommy"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_quadrophenia_mfsl_matches_via_tier2(mock_search, mock_detail):
    """Quadrophenia (1991 MFSL Gold) - Disc 1: edition + disc suffix both stripped."""
    probe = ProbeResult(
        artist="The Who",
        album="Quadrophenia (1991 MFSL Gold) - Disc 1",
        track_count=10,
        track_titles=QUAD_DISC1_TRACKS,
    )

    def search_side(query):
        if "Quadrophenia (1991 MFSL Gold)" in query:
            return []
        if '"Quadrophenia"' in query:
            return [_candidate("mb-quad", track_count=10)]
        return []

    mock_search.side_effect = search_side
    mock_detail.return_value = _detail("mb-quad", QUAD_DISC1_TRACKS)

    result = find_best_release(probe)
    assert result == "mb-quad"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_sell_out_reissue_matches_via_tier2(mock_search, mock_detail):
    """The Who Sell Out (1970 UK Reissue): year+country noise stripped by tier 2."""
    probe = ProbeResult(
        artist="The Who",
        album="The Who Sell Out (1970 UK Reissue)",
        track_count=13,
        track_titles=SELL_OUT_TRACKS,
    )

    def search_side(query):
        if "1970 UK Reissue" in query:
            return []
        if "The Who Sell Out" in query:
            return [_candidate("mb-sell-out", track_count=13)]
        return []

    mock_search.side_effect = search_side
    mock_detail.return_value = _detail("mb-sell-out", SELL_OUT_TRACKS)

    result = find_best_release(probe)
    assert result == "mb-sell-out"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_tier1_match_skips_tier2(mock_search, mock_detail):
    """If tier 1 finds a match, tier 2 is never attempted."""
    probe = ProbeResult(
        artist="Artist", album="Clean Album {UK}", track_count=3,
        track_titles=MB_TITLES,
    )
    mock_search.return_value = [_candidate("mb-clean", track_count=3)]
    mock_detail.return_value = _detail("mb-clean", MB_TITLES)

    result = find_best_release(probe)
    assert result == "mb-clean"
    assert mock_search.call_count == 1  # stopped at tier 1


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_tier3_fallback_short_title(mock_search, mock_detail):
    """Tier 3 (first 2 words) used when tiers 1+2 fail on a decorated title."""
    probe = ProbeResult(
        artist="Miles Davis", album="Kind of Blue Remastered Edition",
        track_count=3, track_titles=MB_TITLES,
    )

    def search_side(query):
        if '"Kind of Blue Remastered Edition"' in query:
            return []
        if '"Kind of"' in query:
            return [_candidate("mb-kob", track_count=3)]
        return []

    mock_search.side_effect = search_side
    mock_detail.return_value = _detail("mb-kob", MB_TITLES)

    result = find_best_release(probe)
    assert result == "mb-kob"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_1999_title_unchanged(mock_search, mock_detail):
    """'1999' must never be mangled — no digits stripped from titles."""
    probe = ProbeResult(
        artist="Prince", album="1999", track_count=3, track_titles=MB_TITLES,
    )
    mock_search.return_value = [_candidate("mb-1999", track_count=3)]
    mock_detail.return_value = _detail("mb-1999", MB_TITLES)

    result = find_best_release(probe)
    assert result == "mb-1999"
    call_args = mock_search.call_args_list[0][0][0]
    assert '"1999"' in call_args


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_exact_match(mock_search, mock_detail):
    probe = ProbeResult(artist="Billie Holiday", album="Lady in Satin",
                        track_count=3, track_titles=MB_TITLES)
    mock_search.return_value = [_candidate("mb-123", track_count=3)]
    mock_detail.return_value = _detail("mb-123", MB_TITLES)
    assert find_best_release(probe) == "mb-123"


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_poor_match_returns_none(mock_search, mock_detail):
    probe = ProbeResult(artist="Artist", album="Album", track_count=10,
                        track_titles=[f"Track {i}" for i in range(10)])
    mock_search.return_value = [_candidate("mb-789", track_count=10)]
    mock_detail.return_value = _detail("mb-789", [f"Different {i}" for i in range(10)])
    assert find_best_release(probe) is None


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
    mock_search.return_value = [_candidate("mb-bad", track_count=5)]
    assert find_best_release(probe) is None


@patch("app.pipeline.matcher.get_release_by_id")
@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_bonus_tracks_allowed(mock_search, mock_detail):
    """We have 16 tracks (13 standard + 3 Japan bonus); MB standard has 13 — still matches."""
    std_titles = [f"Track {i}" for i in range(13)]
    probe = ProbeResult(artist="Beck", album="Guero (SHM-CD)", track_count=16,
                        track_titles=std_titles + ["Japan Bonus 1", "Japan Bonus 2", "Japan Bonus 3"])
    mock_search.return_value = [_candidate("mb-guero", track_count=13)]
    mock_detail.return_value = _detail("mb-guero", std_titles)
    assert find_best_release(probe) == "mb-guero"


@patch("app.pipeline.matcher.search_releases")
def test_find_best_release_no_artist_and_album(mock_search):
    probe = ProbeResult(artist="", album="", track_count=5, track_titles=["T1"])
    assert find_best_release(probe) is None
    mock_search.assert_not_called()


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
    assert find_best_release(probe) == "mb-high"
