from unittest.mock import patch

MOCK_ALBUMS = [
    {
        "id": 1,
        "album": "Ziggy Stardust",
        "artist": "David Bowie",
        "year": 1972,
        "tracks": 11,
        "path": "/media/music/David Bowie/Ziggy Stardust (1972)/01.flac",
        "artpath": "/media/music/David Bowie/Ziggy Stardust (1972)/cover.jpg",
        "mb_albumid": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
        "format": "FLAC",
    },
    {
        "id": 2,
        "album": "Aqualung",
        "artist": "Jethro Tull",
        "year": 1971,
        "tracks": 13,
        "path": "/media/music/Jethro Tull/Aqualung (1971)/01.flac",
        "artpath": None,
        "mb_albumid": "",
        "format": "MP3",
    },
]


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=42)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_shows_albums(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Ziggy Stardust" in resp.data
    assert b"Aqualung" in resp.data


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=42)
@patch("app.routes.library.list_albums", return_value=[MOCK_ALBUMS[0]])
def test_library_search_passes_query(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/?q=Bowie")
    assert resp.status_code == 200
    mock_list.assert_called_with("Bowie")


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=5)
@patch("app.routes.library.count_albums", return_value=133)
@patch("app.routes.library.list_albums", return_value=[])
def test_library_stats_bar_shows_counts(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/")
    data = resp.data.decode()
    assert "133" in data
    assert "5" in data


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=2)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_shows_thumbnail_img(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/")
    assert b"/album/1/art" in resp.data
    assert b"/album/2/art" in resp.data


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=2)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_shows_mb_status_pill(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/")
    data = resp.data.decode()
    assert "mb-pill--matched" in data    # album 1 has mb_albumid
    assert "mb-pill--unmatched" in data  # album 2 has empty mb_albumid


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=2)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_shows_fix_art_button(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/")
    assert b"fix-art-btn" in resp.data


@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=2)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_shows_format(mock_list, mock_count, mock_attention, mock_active, client):
    resp = client.get("/")
    assert b"FLAC" in resp.data
    assert b"MP3" in resp.data


@patch("app.routes.library.count_albums_without_mbid", return_value=37)
@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=895)
@patch("app.routes.library.list_albums", return_value=[MOCK_ALBUMS[1]])
def test_library_no_mb_filter_queries_albums_missing_mbid(
    mock_list, mock_count, mock_attention, mock_active, mock_nomb, client
):
    resp = client.get("/?filter=no-mb")
    assert resp.status_code == 200
    mock_list.assert_called_with("mb_albumid::^$")


@patch("app.routes.library.count_albums_without_mbid", return_value=37)
@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=895)
@patch("app.routes.library.list_albums", return_value=[MOCK_ALBUMS[1]])
def test_library_no_mb_filter_composes_with_search(
    mock_list, mock_count, mock_attention, mock_active, mock_nomb, client
):
    resp = client.get("/?q=Bowie&filter=no-mb")
    assert resp.status_code == 200
    mock_list.assert_called_with("Bowie mb_albumid::^$")


@patch("app.routes.library.count_albums_without_mbid", return_value=37)
@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=895)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_unknown_filter_value_is_ignored(
    mock_list, mock_count, mock_attention, mock_active, mock_nomb, client
):
    resp = client.get("/?q=Bowie&filter=bogus")
    assert resp.status_code == 200
    mock_list.assert_called_with("Bowie")


@patch("app.routes.library.count_albums_without_mbid", return_value=37)
@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=895)
@patch("app.routes.library.list_albums", return_value=MOCK_ALBUMS)
def test_library_tile_shows_no_mb_count_and_links_to_filter(
    mock_list, mock_count, mock_attention, mock_active, mock_nomb, client
):
    resp = client.get("/")
    data = resp.data.decode()
    assert "37" in data
    assert "filter=no-mb" in data


@patch("app.routes.library.count_albums_without_mbid", return_value=37)
@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=895)
@patch("app.routes.library.list_albums", return_value=[MOCK_ALBUMS[1]])
def test_library_filtered_view_announces_itself_and_offers_clear(
    mock_list, mock_count, mock_attention, mock_active, mock_nomb, client
):
    resp = client.get("/?filter=no-mb")
    data = resp.data.decode()
    assert "no MusicBrainz ID" in data
    assert "Clear filter" in data


@patch("app.routes.library.count_albums_without_mbid", return_value=37)
@patch("app.routes.library.get_active", return_value=None)
@patch("app.routes.library.count_need_attention", return_value=0)
@patch("app.routes.library.count_albums", return_value=895)
@patch("app.routes.library.list_albums", return_value=[MOCK_ALBUMS[1]])
def test_library_search_form_keeps_filter_active(
    mock_list, mock_count, mock_attention, mock_active, mock_nomb, client
):
    resp = client.get("/?filter=no-mb")
    data = resp.data.decode()
    assert '<input type="hidden" name="filter" value="no-mb">' in data
