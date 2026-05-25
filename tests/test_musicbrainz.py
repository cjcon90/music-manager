import responses

from app import musicbrainz as mb

# Reset rate limit timestamp so tests don't sleep waiting for 1-second window
mb._last_request_ts = 0.0


MB_SEARCH_RESPONSE = {
    "releases": [
        {
            "id": "uuid-1234",
            "title": "Let It Be",
            "artist-credit": [{"artist": {"name": "The Beatles"}}],
            "date": "2024",
            "country": "GB",
            "label-info": [{"label": {"name": "Apple Records"}}],
            # The real MB search API returns track-count per medium, not individual track listings
            "media": [{"track-count": 12}],
            "score": 97,
        }
    ]
}

MB_RELEASE_RESPONSE = {
    "id": "uuid-1234",
    "title": "Let It Be",
    "artist-credit": [{"artist": {"name": "The Beatles"}}],
    "date": "2024",
    "country": "GB",
    "label-info": [{"label": {"name": "Apple Records"}}],
    "media": [
        {
            "tracks": [
                {"position": 1, "title": "Two Of Us"},
                {"position": 2, "title": "Dig A Pony"},
            ]
        }
    ],
}


@responses.activate
def test_search_releases_returns_candidates():
    responses.add(responses.GET, "https://musicbrainz.org/ws/2/release", json=MB_SEARCH_RESPONSE)
    result = mb.search_releases("The Beatles Let It Be")
    assert len(result) == 1
    assert result[0]["id"] == "uuid-1234"
    assert result[0]["title"] == "Let It Be"
    assert result[0]["score"] == 97
    assert result[0]["tracks"] == []  # search API does not return individual track listings
    assert result[0]["track_count"] == 12


@responses.activate
def test_get_release_by_id_returns_release():
    responses.add(
        responses.GET,
        "https://musicbrainz.org/ws/2/release/uuid-1234",
        json=MB_RELEASE_RESPONSE,
    )
    result = mb.get_release_by_id("uuid-1234")
    assert result["id"] == "uuid-1234"
    assert result["title"] == "Let It Be"
    assert result["tracks"] == [
        {"position": 1, "title": "Two Of Us", "length_ms": None},
        {"position": 2, "title": "Dig A Pony", "length_ms": None},
    ]


@responses.activate
def test_search_includes_user_agent():
    responses.add(
        responses.GET, "https://musicbrainz.org/ws/2/release", json={"releases": []}
    )
    mb.search_releases("test")
    assert "music-manager" in responses.calls[0].request.headers["User-Agent"]
