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
    # Row the single aggregate query would return for this album. None when the
    # album has no items — the query simply yields no row for it.
    first = items[0] if items else None
    a.agg_row = (id, len(items), 0, first.path, first.format) if first else None
    return a


def _wire(lib, albums):
    """Point lib.albums at *albums* and stub the one item-aggregate query."""
    lib.albums.return_value = albums
    rows = [a.agg_row for a in albums if a.agg_row is not None]
    lib.transaction.return_value.__enter__.return_value.query.return_value = rows
    return lib


@patch("app.beets_api.Library")
def test_list_albums_returns_sorted_list(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a1 = _make_album(album="Ziggy", albumartist="Bowie")
    a2 = _make_album(album="Aqualung", albumartist="Bowie")
    _wire(lib, [a1, a2])

    from app.beets_api import list_albums
    result = list_albums()

    assert len(result) == 2
    assert result[0]["album"] == "Aqualung"
    assert result[1]["album"] == "Ziggy"


@patch("app.beets_api.Library")
def test_list_albums_with_query(mock_lib_cls):
    lib = mock_lib_cls.return_value
    _wire(lib, [_make_album()])

    from app.beets_api import list_albums
    list_albums("Bowie")

    lib.albums.assert_called_with("Bowie")


@patch("app.beets_api.Library")
def test_get_album_by_id_found(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(id=42, album="Ziggy", albumartist="Bowie", year=1972)
    _wire(lib, [a])

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
    _wire(lib, [a])

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["artpath"] == "/media/music/Bowie/Ziggy (1972)/cover.jpg"


@patch("app.beets_api.Library")
def test_album_info_artpath_none_when_unset(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(artpath=None)
    _wire(lib, [a])

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["artpath"] is None


@patch("app.beets_api.Library")
def test_album_info_includes_mb_albumid(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(mb_albumid="some-uuid")
    _wire(lib, [a])

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["mb_albumid"] == "some-uuid"


@patch("app.beets_api.Library")
def test_album_info_mb_albumid_empty_when_none(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(mb_albumid=None)
    _wire(lib, [a])

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["mb_albumid"] == ""


@patch("app.beets_api.Library")
def test_album_info_includes_format(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(fmt="MP3")
    _wire(lib, [a])

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["format"] == "MP3"


@patch("app.beets_api.Library")
def test_album_info_format_and_path_empty_when_no_items(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(items=[])
    _wire(lib, [a])

    from app.beets_api import list_albums
    result = list_albums()

    assert result[0]["format"] == ""
    assert result[0]["path"] is None


@patch("app.beets_api.Library")
def test_album_info_artpath_str_passthrough(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album(artpath="/media/music/Bowie/cover.jpg")  # plain str, not bytes
    _wire(lib, [a])

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


@patch("app.beets_api.Library")
def test_list_albums_issues_one_item_query_regardless_of_album_count(mock_lib_cls):
    """Regression guard: the per-album a.items() call was 1.3s of page render.

    Reading track data must stay a single query no matter how big the library
    gets, so assert on the query count rather than on elapsed time.
    """
    lib = mock_lib_cls.return_value
    _wire(lib, [_make_album(id=i) for i in range(50)])

    from app.beets_api import list_albums
    result = list_albums()

    assert len(result) == 50
    assert lib.transaction.return_value.__enter__.return_value.query.call_count == 1
    for album in lib.albums.return_value:
        album.items.assert_not_called()


@patch("app.beets_api.Library")
def test_get_album_by_id_scopes_the_item_query_to_one_album(mock_lib_cls):
    lib = mock_lib_cls.return_value
    _wire(lib, [_make_album(id=42)])

    from app.beets_api import get_album_by_id
    get_album_by_id(42)

    sql, args = lib.transaction.return_value.__enter__.return_value.query.call_args[0]
    assert "WHERE album_id = ?" in sql
    assert args == (42,)


@patch("app.beets_api.Library")
def test_list_albums_reports_track_count_from_the_aggregate(mock_lib_cls):
    lib = mock_lib_cls.return_value
    a = _make_album()
    a.agg_row = (a.id, 11, 0, b"/media/music/Bowie/Ziggy/01.flac", "FLAC")
    _wire(lib, [a])

    from app.beets_api import list_albums
    assert list_albums()[0]["tracks"] == 11
