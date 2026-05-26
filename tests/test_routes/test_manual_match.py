from unittest.mock import MagicMock, patch

MOCK_CANDIDATES = [
    {'id': 'uuid-1', 'title': 'Let It Be', 'artist': 'The Beatles', 'year': '2024',
     'country': 'GB', 'label': 'Apple Records', 'score': 97, 'tracks': [], 'track_count': 12},
    {'id': 'uuid-2', 'title': 'Let It Be', 'artist': 'The Beatles', 'year': '1970',
     'country': 'GB', 'label': 'Apple Records', 'score': 71, 'tracks': [], 'track_count': 12},
]

MOCK_RELEASE = {
    'id': 'uuid-1', 'title': 'Let It Be', 'artist': 'The Beatles', 'year': '2024',
    'country': 'GB', 'label': 'Apple Records', 'score': 97,
    'tracks': [{'position': 1, 'title': 'Two Of Us'}, {'position': 2, 'title': 'Dig A Pony'}],
    'track_count': 2,
}


def test_manual_match_page_loads(client):
    resp = client.get('/manual-match?stage_path=/some/path')
    assert resp.status_code == 200
    assert b'/some/path' in resp.data


@patch('app.routes.manual_match.search_releases', return_value=MOCK_CANDIDATES)
def test_search_returns_candidates(mock_search, client):
    resp = client.post('/manual-match/search',
                       data={'stage_path': '/some/path', 'query': 'Beatles Let It Be'})
    assert resp.status_code == 200
    assert b'Let It Be' in resp.data
    assert b'97' in resp.data   # score shown
    mock_search.assert_called_with('Beatles Let It Be', artist='', title='Beatles Let It Be')
    assert b'Tracks' in resp.data  # track toggle button rendered


@patch('app.routes.manual_match.get_release_by_id', return_value=MOCK_RELEASE)
def test_apply_by_id_shows_tracks(mock_get, client):
    resp = client.post('/manual-match/apply-by-id',
                       data={'stage_path': '/some/path', 'mb_uuid': 'uuid-1'})
    assert resp.status_code == 200
    assert b'Two Of Us' in resp.data
    assert b'Dig A Pony' in resp.data


@patch('app.routes.manual_match.acquire_lock', return_value=False)
def test_apply_blocked_when_locked(mock_acquire, client):
    resp = client.get('/manual-match/stream?stage_path=/p&mb_uuid=x')
    assert resp.status_code == 409


@patch('app.routes.manual_match.acquire_lock', return_value=True)
@patch('app.routes.manual_match.release_lock')
@patch('app.routes.manual_match.stream_import', return_value=iter(['data: done\n\n', 'data: [DONE]\n\n']))
def test_stream_endpoint_returns_sse(mock_import, mock_release, mock_acquire, client):
    resp = client.get('/manual-match/stream?stage_path=/p&mb_uuid=uuid-1')
    assert resp.status_code == 200
    assert resp.content_type == 'text/event-stream'


MOCK_RELEASE_DETAIL = {
    'id': 'uuid-1', 'title': 'Let It Be', 'artist': 'The Beatles', 'year': '2024',
    'country': 'GB', 'label': 'Apple Records', 'score': 97, 'track_count': 2,
    'disambiguation': '',
    'tracks': [
        {'position': 1, 'title': 'Two Of Us', 'length_ms': 180000},
        {'position': 2, 'title': 'Dig A Pony', 'length_ms': 240000},
    ],
}


@patch('app.routes.manual_match.acquire_lock', return_value=False)
def test_split_by_mb_blocked_when_locked(mock_acquire, client):
    resp = client.get('/manual-match/split-by-mb?stage_path=/p&mb_uuid=uuid-1')
    assert resp.status_code == 409


def test_split_by_mb_requires_mb_uuid(client):
    resp = client.get('/manual-match/split-by-mb?stage_path=/p')
    assert resp.status_code == 400


@patch('app.routes.manual_match.acquire_lock', return_value=True)
@patch('app.routes.manual_match.release_lock')
@patch('app.routes.manual_match.split_cue_rip')
@patch('app.routes.manual_match.probe_cue')
@patch('app.routes.manual_match._staging')
def test_split_by_mb_returns_sse(mock_staging, mock_probe, mock_split, mock_release, mock_acquire, client, tmp_path):
    audio_file = tmp_path / "album.flac"
    audio_file.touch()
    mock_probe.return_value = MagicMock(source_file=audio_file, track_count=10)
    mock_staging.create_stage.return_value = MagicMock()
    resp = client.get('/manual-match/split-by-mb?stage_path=/p&mb_uuid=uuid-1')
    assert resp.status_code == 200
    assert resp.content_type == 'text/event-stream'
    body = resp.data.decode()
    assert '[DONE]' in body
    mock_split.assert_called_once()


@patch('app.routes.manual_match.acquire_lock', return_value=True)
@patch('app.routes.manual_match.release_lock')
@patch('app.routes.manual_match.probe_cue', side_effect=Exception("CUE parse error"))
@patch('app.routes.manual_match._staging')
def test_split_by_mb_releases_lock_on_failure(mock_staging, mock_probe, mock_release, mock_acquire, client):
    """Lock must be released even when probe_cue raises."""
    resp = client.get('/manual-match/split-by-mb?stage_path=/p&mb_uuid=uuid-1')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert '[ERROR]' in body
    mock_release.assert_called_once()


@patch('app.routes.manual_match.search_releases', return_value=MOCK_CANDIDATES)
def test_search_with_artist_field(mock_search, client):
    """Artist field must be passed through as keyword arg to search_releases."""
    resp = client.post('/manual-match/search',
                       data={'stage_path': '/some/path', 'query': 'At Last!', 'artist': 'Etta James'})
    assert resp.status_code == 200
    mock_search.assert_called_with('At Last!', artist='Etta James', title='At Last!')
    assert b'At Last' in resp.data


@patch('app.routes.manual_match.search_releases', return_value=[])
def test_search_artist_only_no_query(mock_search, client):
    """Searching with only an artist field (empty album) still triggers search."""
    resp = client.post('/manual-match/search',
                       data={'stage_path': '/p', 'query': '', 'artist': 'Etta James'})
    assert resp.status_code == 200
    mock_search.assert_called_with('', artist='Etta James', title='')


# DSF / track-count scoring tests

@patch('app.routes.manual_match._local_tracks', return_value=[
    "01 - Anything To Say Youre Mine.dsf",
    '02 - My Dearest Darling.dsf',
    '03 - Trust In Me.dsf',
    '04 - A Sunday Kind Of Love.dsf',
    '05 - Tough Mary.dsf',
    '06 - I Just Want To Make Love To You.dsf',
    '07 - At Last.dsf',
    '08 - All I Could Do Was Cry.dsf',
    '09 - Stormy Weather.dsf',
    '10 - Girl Of My Dreams.dsf',
])
@patch('app.routes.manual_match.search_releases', return_value=[
    {'id': 'uuid-10', 'title': 'At Last!', 'artist': 'Etta James', 'year': '1960',
     'country': 'US', 'label': 'Chess', 'score': 100, 'tracks': [], 'track_count': 10,
     'disambiguation': ''},
    {'id': 'uuid-14', 'title': 'At Last!', 'artist': 'Etta James', 'year': '2008',
     'country': 'US', 'label': 'Chess', 'score': 100, 'tracks': [], 'track_count': 14,
     'disambiguation': ''},
    {'id': 'uuid-20', 'title': 'At Last', 'artist': 'Etta James', 'year': '1992',
     'country': 'GB', 'label': 'Charly', 'score': 100, 'tracks': [], 'track_count': 20,
     'disambiguation': ''},
])
def test_track_count_scoring_sorts_best_match_first(mock_search, mock_local, client):
    """10 local DSF files → 10-track release scores 100%, others score lower."""
    resp = client.post('/manual-match/search',
                       data={'stage_path': '/some/path', 'query': 'At Last!', 'artist': 'Etta James'})
    assert resp.status_code == 200
    body = resp.data.decode()
    # 10-track release must appear first (highest score)
    pos_10 = body.index('uuid-10')
    pos_14 = body.index('uuid-14')
    pos_20 = body.index('uuid-20')
    assert pos_10 < pos_14 < pos_20, "10-track release should rank first"
    # Score label should be "track count", not "relevance"
    assert 'track count' in body


@patch('app.routes.manual_match._local_tracks', return_value=[
    "01 - Anything To Say Youre Mine.dsf",
    '02 - My Dearest Darling.dsf',
])
@patch('app.routes.manual_match.search_releases', return_value=[
    {'id': 'uuid-0', 'title': 'Test', 'artist': 'Test', 'year': '2000',
     'country': 'US', 'label': '', 'score': 100, 'tracks': [], 'track_count': 0,
     'disambiguation': ''},
])
def test_track_count_falls_back_to_relevance_when_mb_count_unknown(mock_search, mock_local, client):
    """If MB track_count is 0 (unknown), fall back to relevance label."""
    resp = client.post('/manual-match/search',
                       data={'stage_path': '/some/path', 'query': 'Test', 'artist': ''})
    assert resp.status_code == 200
    assert b'relevance' in resp.data


def test_local_tracks_includes_dsf_and_dff(tmp_path):
    """DSF and DFF files must be picked up alongside FLAC."""
    from app.routes.manual_match import _local_tracks
    (tmp_path / 'track1.dsf').touch()
    (tmp_path / 'track2.dff').touch()
    (tmp_path / 'track3.flac').touch()
    (tmp_path / 'cover.jpg').touch()   # should be excluded
    result = _local_tracks(str(tmp_path))
    assert 'track1.dsf' in result
    assert 'track2.dff' in result
    assert 'track3.flac' in result
    assert 'cover.jpg' not in result


def test_compare_tracks_strips_extension_before_normalise(tmp_path):
    """_compare_tracks must match '07 - At Last.dsf' against MB title 'At Last'."""
    from app.routes.manual_match import _compare_tracks
    from app.types import TrackDetail
    local = ['07 - At Last.dsf', '08 - All I Could Do Was Cry.dsf']
    mb = [
        TrackDetail(position=7, title='At Last', length_ms=None),
        TrackDetail(position=8, title='All I Could Do Was Cry', length_ms=None),
    ]
    rows = _compare_tracks(local, mb)
    statuses = {r['mb']: r['status'] for r in rows}
    assert statuses['At Last'] == 'match'
    assert statuses['All I Could Do Was Cry'] == 'match'
