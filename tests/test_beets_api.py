from unittest.mock import MagicMock, patch


def _make_album(
    id=1,
    album="Ziggy Stardust",
    albumartist="David Bowie",
    year=1972,
    artpath=b"/media/music/David Bowie/Ziggy Stardust (1972)/cover.jpg",
    mb_albumid="b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
    items=None,
    fmt="FLAC",
):
    a = MagicMock()
    a.id = id
    a.album = album
    a.albumartist = albumartist
    a.year = year
    a.artpath = artpath
    a.mb_albumid = mb_albumid
    if items is None:
        item = MagicMock()
        item.track = 1
        item.title = "Starman"
        item.path = b"/media/music/David Bowie/Ziggy Stardust (1972)/01 - Starman.flac"
        item.format = fmt
        items = [item]
    a.items.return_value = items
    return a


@patch("app.beets_api.Library")
def test_list_albums_returns_sorted_list(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a1 = _make_album(album="Ziggy", albumartist="Bowie")
    a2 = _make_album(album="Aqualung", albumartist="Bowie")
    lib.albums.return_value = [a1, a2]

    from app.beets_api import list_albums
    result = list_albums()

    assert len(result) == 2
    assert result[0]["album"] == "Aqualung"
    assert result[1]["album"] == "Ziggy"


@patch("app.beets_api.Library")
def test_list_albums_with_query(mock_lib_cls):
    lib = mock_lib_cls.return_value
    lib.albums.return_value = [_make_album()]

    from app.beets_api import list_albums
    list_albums("Bowie")

    lib.albums.assert_called_with("Bowie")


@patch("app.beets_api.Library")
def test_get_album_by_id_found(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(id=42, album="Ziggy", albumartist="Bowie", year=1972)
    lib.albums.return_value = [a]

    from app.beets_api import get_album_by_id
    result = get_album_by_id(42)

    assert result["id"] == 42
    assert result["album"] == "Ziggy"
    lib.albums.assert_called_with("id:42")


@patch("app.beets_api.Library")
def test_get_album_by_id_not_found(mock_lib_cls):
    lib = mock_lib_cls.return_value
    lib.albums.return_value = []

    from app.beets_api import get_album_by_id
    assert get_album_by_id(999) is None


@patch("app.beets_api.Library")
def test_get_album_tracks_sorted(mock_lib_cls):
    lib = mock_lib_cls.return_value
    i1 = MagicMock(); i1.track = 2; i1.title = "B"; i1.path = b"/x/2.flac"
    i2 = MagicMock(); i2.track = 1; i2.title = "A"; i2.path = b"/x/1.flac"
    lib.items.return_value = [i1, i2]

    from app.beets_api import get_album_tracks
    result = get_album_tracks(1)

    assert result[0]["track"] == 1
    assert result[1]["track"] == 2
    lib.items.assert_called_with("album_id:1")


@patch("app.beets_api.Library")
def test_count_albums(mock_lib_cls):
    lib = mock_lib_cls.return_value
    lib.albums.return_value = [MagicMock(), MagicMock()]

    from app.beets_api import count_albums
    assert count_albums() == 2


@patch("app.beets_api.Library")
def test_album_info_includes_artpath(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(artpath=b"/media/music/Bowie/Ziggy (1972)/cover.jpg")
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["artpath"] == "/media/music/Bowie/Ziggy (1972)/cover.jpg"


@patch("app.beets_api.Library")
def test_album_info_artpath_none_when_unset(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(artpath=None)
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["artpath"] is None


@patch("app.beets_api.Library")
def test_album_info_includes_mb_albumid(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(mb_albumid="some-uuid")
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["mb_albumid"] == "some-uuid"


@patch("app.beets_api.Library")
def test_album_info_mb_albumid_empty_when_none(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(mb_albumid=None)
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["mb_albumid"] == ""


@patch("app.beets_api.Library")
def test_album_info_includes_format(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(fmt="MP3")
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["format"] == "MP3"


@patch("app.beets_api.Library")
def test_album_info_format_and_path_empty_when_no_items(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(items=[])
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["format"] == ""
    assert result[0]["path"] is None


@patch("app.beets_api.Library")
def test_album_info_artpath_str_passthrough(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(artpath="/media/music/Bowie/cover.jpg")  # plain str, not bytes
    lib.albums.return_value = [a]

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["artpath"] == "/media/music/Bowie/cover.jpg"


@patch("app.beets_api.Library")
def test_count_albums_without_mbid_uses_empty_mb_albumid_query(mock_lib_cls):
    lib = mock_lib_cls.return_value
    lib.albums.return_value = [MagicMock(), MagicMock(), MagicMock()]

    from app.beets_api import NO_MBID_QUERY, count_albums_without_mbid
    assert count_albums_without_mbid() == 3

    # The query string is the contract with beets: `field::regex` with ^$ matches
    # albums whose mb_albumid is empty. Verified against the live library.
    assert NO_MBID_QUERY == "mb_albumid::^$"
    lib.albums.assert_called_with(NO_MBID_QUERY)
