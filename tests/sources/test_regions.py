import pytest

from jobscout.sources.regions import countries_in, country_of, english_name


@pytest.mark.parametrize(
    ("typed", "country"),
    [
        ("Argentina", "argentina"),
        ("França", "france"),
        ("Alemanha", "germany"),
        ("EUA", "usa"),
        ("México", "mexico"),
        ("Índia", "india"),
    ],
)
def test_a_country_is_recognised_as_people_write_it(typed, country):
    assert country_of(typed) == country


@pytest.mark.parametrize("typed", ["remoto", "Recife", "Europe", "CA", "Georgia"])
def test_anything_else_is_not_a_country(typed):
    assert country_of(typed) is None


@pytest.mark.parametrize(
    ("country", "written"),
    [
        ("brazil", "Brazil"),
        ("usa", "United States"),
        ("south korea", "South Korea"),
        ("bosnia and herzegovina", "Bosnia and Herzegovina"),
    ],
)
def test_a_country_has_an_english_name_for_sites_that_geocode_text(country, written):
    assert english_name(country) == written


@pytest.mark.parametrize(
    ("location", "named"),
    [
        ("Worldwide", set()),
        ("Greater São Paulo Area", set()),
        ("Curitiba, Paraná, Brazil", {"brazil"}),
        ("Recife, PE, BR", {"brazil"}),
        ("Rio de Janeiro", set()),  # "de" is Germany's code, and only counts as the last part
        ("Sydney, Australia", {"australia"}),
        ("Indiana", set()),
        ("Canada, United Kingdom", {"canada", "uk"}),
    ],
)
def test_the_countries_a_location_names(location, named):
    assert countries_in(location) == named


def test_an_area_names_the_countries_inside_it():
    assert {"brazil", "argentina", "mexico"} <= countries_in("LATAM")
    assert {"portugal", "germany", "uk"} <= countries_in("Remote - Europe")
    assert {"usa", "canada"} <= countries_in("North America")
    assert "brazil" not in countries_in("Europe, USA, Canada, APAC")
