"""LinkedIn, through JobSpy (see ``jobspy_base``). No key; a proxy is optional.

Verified against a live capture (``tests/fixtures/linkedin_sample.jsonl``, 5 rows): the
search results carry no description at all, so ``fetch_description`` is on and costs one extra
request per posting. The matcher cannot score an empty document, which is why that is not
optional here. Rows carry no salary. LinkedIn is the site most likely to rate-limit a
proxy-less client, which is why the volumes stay low (``Settings.jobspy_*``).
"""

from jobscout.sources.base import SearchQuery
from jobscout.sources.jobspy_base import JobSpySource


class LinkedInSource(JobSpySource):
    name = "linkedin"
    site = "linkedin"
    fetch_description = True

    def search_kwargs(self, query: SearchQuery) -> dict[str, object]:
        kwargs = super().search_kwargs(query)
        # ``location`` is kept — the LinkedIn scraper passes it straight to the guest search,
        # and the capture above proves "Brazil" returns postings from the whole country. It must
        # be the English name: "Brasil" returned five US postings (``linkedin_location_brasil``).
        # ``is_remote`` is dropped: python-jobspy 1.4.1 answers ``is_remote isn't supported,
        # ignoring it`` for LinkedIn (``jobspy/linkedin/__init__.py``) and LinkedIn's own
        # ``f_WT`` filter is not exposed, so sending it would change no result and would put
        # that warning in every run's errors, where a real block has to stand out. Remote-only
        # preferences are still honoured by ``pipeline.filters`` after the fetch.
        kwargs.pop("is_remote", None)
        return kwargs
