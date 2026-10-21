"""
Tests for RecommendationsService's anti-hallucination guard.

The recommendation prompt instructs Gemini to only choose titles that exist
in the user's real collection. This test verifies the code-side guarantee:
even if the model returns a title that isn't in the user's collection, it
is dropped rather than persisted as a recommendation.
"""

import json
from unittest.mock import MagicMock, patch

from models.ai_recommendation import AIRecommendation
from services.recommendations_service import RecommendationsService


def _gemini_response(payload):
    response = MagicMock()
    response.text = json.dumps(payload)
    return response


def test_hallucinated_title_is_filtered_out(app, pro_user, create_collection_book, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test_gemini_key')
    real_book = create_collection_book(title='Project Hail Mary', authors=['Andy Weir'])

    gemini_payload = [
        {
            'title': 'Project Hail Mary',
            'authors': 'Andy Weir',
            'reason': 'A gripping, hard sci-fi survival story.',
        },
        {
            'title': 'A Book That Does Not Exist In This Collection',
            'authors': 'Nobody',
            'reason': 'Hallucinated by the model.',
        },
    ]

    with patch('services.recommendations_service.genai.Client') as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _gemini_response(gemini_payload)
        mock_client_cls.return_value = mock_client

        results = RecommendationsService.generate_recommendations(pro_user.id, force_regenerate=True)

    titles = [r.book_title for r in results]
    assert titles == ['Project Hail Mary']
    assert 'A Book That Does Not Exist In This Collection' not in titles

    persisted = AIRecommendation.query.filter_by(user_id=pro_user.id).all()
    assert len(persisted) == 1
    assert persisted[0].book_title == 'Project Hail Mary'
    assert persisted[0].recommendation_reason == 'A gripping, hard sci-fi survival story.'


def test_no_unread_books_returns_empty_without_calling_gemini(app, pro_user):
    with patch('services.recommendations_service.genai.Client') as mock_client_cls:
        results = RecommendationsService.generate_recommendations(pro_user.id, force_regenerate=True)

    assert results == []
    mock_client_cls.assert_not_called()


def test_non_list_response_is_rejected(app, pro_user, create_collection_book, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test_gemini_key')
    create_collection_book(title='Project Hail Mary', authors=['Andy Weir'])

    with patch('services.recommendations_service.genai.Client') as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _gemini_response({'not': 'a list'})
        mock_client_cls.return_value = mock_client

        results = RecommendationsService.generate_recommendations(pro_user.id, force_regenerate=True)

    assert results == []
    assert AIRecommendation.query.filter_by(user_id=pro_user.id).count() == 0
