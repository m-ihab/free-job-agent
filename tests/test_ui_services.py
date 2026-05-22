from job_agent.ui.services import APP_DESCRIPTION, APP_NAME, build_manual_search_groups


def test_ui_manual_search_groups_are_curated_by_default():
    groups = build_manual_search_groups("data scientist", "Paris", language="english", limit=2, boards="recommended")
    assert len(groups) == 2
    boards = {link["board_key"] for group in groups for link in group["links"]}
    assert "welcome-to-the-jungle" in boards
    assert "france-travail-web" in boards
    assert "glassdoor-fr" not in boards
    assert "indeed-fr" not in boards


def test_ui_api_application_text_is_portfolio_friendly():
    assert "Career Copilot" in APP_NAME
    assert "data science" in APP_DESCRIPTION.lower()
    assert "manual review" in APP_DESCRIPTION.lower()

