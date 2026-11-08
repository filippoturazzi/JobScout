def test_the_page_is_served_at_the_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "jobscout" in response.text.lower()
    assert response.headers["cache-control"] == "no-cache"


def test_the_design_system_is_served(client):
    css = client.get("/static/design/tokens.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    logo = client.get("/static/design/logos/jobscout-mark.svg")
    assert logo.status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_the_api_still_answers_beside_the_page(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/status").status_code == 200
