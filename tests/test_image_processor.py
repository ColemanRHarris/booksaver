"""
Tests for ImageProcessor's handling of Gemini vision output.

The Gemini call itself is mocked - these tests verify the parsing contract
(a Python-literal list, not JSON) and that malformed model output degrades
gracefully instead of crashing the request.
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_genai_client():
    with patch('services.image_processor.genai.Client') as mock_client_cls:
        client = MagicMock()
        mock_client_cls.return_value = client
        yield client


@pytest.fixture
def image_processor(app, mock_genai_client, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test_gemini_key')
    from services.image_processor import ImageProcessor
    processor = ImageProcessor()
    processor.image_storage = MagicMock()
    processor.image_storage.create_temp_file.return_value = '/tmp/fake-image.jpg'
    processor.image_storage.delete_image.return_value = None
    return processor


def _ready_file():
    gen_file = MagicMock()
    gen_file.state.name = "ACTIVE"
    gen_file.name = "files/fake123"
    return gen_file


def test_parses_well_formed_python_literal_response(image_processor, mock_genai_client, monkeypatch):
    mock_genai_client.files.upload.return_value = _ready_file()

    response = MagicMock()
    response.text = '["Project Hail Mary by Andy Weir", "The Martian by Andy Weir"]'
    mock_genai_client.models.generate_content.return_value = response

    monkeypatch.setattr(
        'os.path.exists', lambda path: True if path == '/tmp/fake-image.jpg' else False
    )
    monkeypatch.setattr('services.image_processor.check_file_size', lambda path: True)
    monkeypatch.setattr(image_processor, '_search_books_from_text', lambda texts: [{'title': t} for t in texts])

    result = image_processor.process_image('image-123')

    assert result['status'] == 'success'
    assert result['total_texts'] == 2
    assert len(result['books']) == 2


def test_malformed_response_does_not_raise(image_processor, mock_genai_client, monkeypatch):
    mock_genai_client.files.upload.return_value = _ready_file()

    response = MagicMock()
    response.text = "Sure! Here are the books: Project Hail Mary, The Martian"  # not a Python literal
    mock_genai_client.models.generate_content.return_value = response

    monkeypatch.setattr('os.path.exists', lambda path: True)
    monkeypatch.setattr('services.image_processor.check_file_size', lambda path: True)

    result = image_processor.process_image('image-456')

    assert result['status'] == 'success'
    assert result['books'] == []
    assert result['total_texts'] == 0


def test_empty_response_returns_no_books(image_processor, mock_genai_client, monkeypatch):
    mock_genai_client.files.upload.return_value = _ready_file()

    response = MagicMock()
    response.text = ""
    mock_genai_client.models.generate_content.return_value = response

    monkeypatch.setattr('os.path.exists', lambda path: True)
    monkeypatch.setattr('services.image_processor.check_file_size', lambda path: True)

    result = image_processor.process_image('image-789')

    assert result['status'] == 'success'
    assert result['books'] == []
