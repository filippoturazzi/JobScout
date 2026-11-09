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


def test_static_files_are_revalidated_on_every_load(client):
    first = client.get("/static/app.js")
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-cache"
    etag = first.headers["etag"]
    again = client.get("/static/app.js", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


def test_scripts_are_served_as_javascript(client):
    # Browsers refuse a module script served as text/plain, which a Windows registry can map.
    response = client.get("/static/app.js")
    assert response.headers["content-type"].startswith("text/javascript")
