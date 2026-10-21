"""
Tests to ensure Pro features are properly gated from free users.

All 13 Pro routes should redirect or return 403 for free users.
"""

import pytest


class TestCollectionsProGating:
    """Test that Collections routes block free users."""

    def test_free_user_blocked_from_collections_index(self, free_auth_client):
        """Free users should be redirected from /collections/"""
        response = free_auth_client.get('/collections/')
        assert response.status_code == 302  # Redirect
        assert b'/billing/upgrade' in response.data or response.location.endswith('/billing/upgrade')

    def test_pro_user_can_access_collections_index(self, auth_client):
        """Pro users should access /collections/ successfully."""
        response = auth_client.get('/collections/')
        assert response.status_code == 200

    def test_free_user_blocked_from_add_book(self, free_auth_client, sample_book_data):
        """Free users should be blocked from POST /collections/add"""
        response = free_auth_client.post('/collections/add', data=sample_book_data)
        # Should redirect or return error
        assert response.status_code in [302, 403]

    def test_pro_user_can_add_book(self, auth_client, sample_book_data):
        """Pro users should be able to add books."""
        response = auth_client.post('/collections/add', data={
            'title': sample_book_data['title'],
            'authors[]': sample_book_data['authors'],
            'isbn': sample_book_data['isbn']
        }, follow_redirects=False)
        # Should succeed (302 redirect to collections page or 200)
        assert response.status_code in [200, 302]

    def test_free_user_blocked_from_move_book(self, free_auth_client):
        """Free users should get 403 from POST /collections/move"""
        response = free_auth_client.post('/collections/move', data={
            'collection_id': 1,
            'shelf': 'currently_reading'
        })
        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data is not None
        assert 'error' in json_data

    def test_free_user_blocked_from_update_tags(self, free_auth_client):
        """Free users should get 403 from POST /collections/update-tags"""
        response = free_auth_client.post('/collections/update-tags', data={
            'collection_id': 1,
            'tags': 'fantasy, adventure'
        })
        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data is not None
        assert 'error' in json_data

    def test_free_user_blocked_from_mark_read(self, free_auth_client):
        """Free users should get 403 from POST /collections/mark-read"""
        response = free_auth_client.post('/collections/mark-read', data={
            'collection_id': 1
        })
        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data is not None
        assert 'error' in json_data

    def test_free_user_blocked_from_mark_reading(self, free_auth_client):
        """Free users should get 403 from POST /collections/mark-reading"""
        response = free_auth_client.post('/collections/mark-reading', data={
            'collection_id': 1
        })
        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data is not None
        assert 'error' in json_data

    def test_free_user_blocked_from_mark_unread(self, free_auth_client):
        """Free users should get 403 from POST /collections/mark-unread"""
        response = free_auth_client.post('/collections/mark-unread', data={
            'collection_id': 1
        })
        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data is not None
        assert 'error' in json_data

    def test_free_user_blocked_from_remove_book(self, free_auth_client):
        """Free users should get 403 from POST /collections/remove"""
        response = free_auth_client.post('/collections/remove', data={
            'collection_id': 1
        })
        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data is not None
        assert 'error' in json_data

    def test_free_user_blocked_from_export(self, free_auth_client):
        """Free users should be redirected from GET /collections/export"""
        response = free_auth_client.get('/collections/export')
        assert response.status_code == 302  # Redirect
        assert b'/billing/upgrade' in response.data or response.location.endswith('/billing/upgrade')

    def test_pro_user_can_export(self, auth_client, app, pro_user, create_collection_book):
        """Pro users should be able to export CSV."""
        # Create at least one book for pro user
        with app.app_context():
            create_collection_book(title='Test Book', isbn='1234567890')

        response = auth_client.get('/collections/export')
        # Should return CSV (200) or handle empty collection gracefully
        assert response.status_code == 200


class TestDashboardProGating:
    """Test that Dashboard routes block free users."""

    def test_free_user_blocked_from_dashboard(self, free_auth_client):
        """Free users should be redirected from /dashboard/"""
        response = free_auth_client.get('/dashboard/')
        assert response.status_code == 302  # Redirect
        assert b'/billing/upgrade' in response.data or response.location.endswith('/billing/upgrade')

    def test_pro_user_can_access_dashboard(self, auth_client):
        """Pro users should access /dashboard/ successfully."""
        response = auth_client.get('/dashboard/')
        assert response.status_code == 200


class TestGoalsProGating:
    """Test that Goals routes block free users."""

    def test_free_user_blocked_from_set_goal(self, free_auth_client):
        """Free users should be blocked from POST /goals/set"""
        response = free_auth_client.post('/goals/set', data={
            'year': 2026,
            'target_count': 24
        })
        # Should redirect or return error
        assert response.status_code in [302, 403]

    def test_pro_user_can_set_goal(self, auth_client):
        """Pro users should be able to set reading goals."""
        response = auth_client.post('/goals/set', data={
            'year': 2026,
            'target_count': 24
        }, follow_redirects=False)
        # Should succeed
        assert response.status_code in [200, 302]
