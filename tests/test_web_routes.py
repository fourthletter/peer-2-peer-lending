import csv
import io
from datetime import datetime, timezone

from src.web import app


def test_incidents_page_loads():
    with app.test_client() as client:
        response = client.get("/incidents")
        assert response.status_code == 200
        assert b"Geographic regions" in response.data


def test_methodology_page_loads():
    with app.test_client() as client:
        response = client.get("/methodology")
        assert response.status_code == 200


def test_news_page_loads():
    with app.test_client() as client:
        response = client.get("/news")
        assert response.status_code == 200


def test_export_csv_uses_session_preview():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["digest_payload"] = {
                "articles": [
                    {
                        "headline": "AI layoffs hit tech sector",
                        "url": "https://example.com/story",
                        "summary": "Workers face displacement.",
                        "published": datetime(2024, 3, 1, tzinfo=timezone.utc).isoformat(),
                        "source": "Example",
                        "publisher_country": "United States",
                        "search_region": "",
                        "thematic_region": "North America",
                        "concepts": ["employment"],
                        "companies": [],
                    }
                ],
                "discovered": 1,
                "new_candidates": 1,
                "ranked_count": 1,
                "note": "",
                "plain": "",
                "coverage_label": "",
                "filter_summary": "",
                "search_query": "",
            }
        response = client.post("/export")
        assert response.status_code == 200
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        assert rows[0] == ["title", "date", "summary", "concepts", "companies", "country", "url"]
        assert rows[1][0] == "AI layoffs hit tech sector"
        assert rows[1][1] == "2024-03-01"
        assert rows[1][6] == "https://example.com/story"
