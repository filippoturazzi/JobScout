"""LinkedIn, through JobSpy (see ``jobspy_base``). No key; a proxy is optional.

Verified against a live capture (``tests/fixtures/linkedin_sample.jsonl``, 5 rows): the
search results carry no description at all, so ``fetch_description`` is on and costs one extra
request per posting. The matcher cannot score an empty document, which is why that is not
optional here. Rows carry no salary. LinkedIn is the site most likely to rate-limit a
proxy-less client, which is why the volumes stay low (``Settings.jobspy_*``).
"""

from jobscout.sources.jobspy_base import JobSpySource


class LinkedInSource(JobSpySource):
    name = "linkedin"
    site = "linkedin"
    fetch_description = True
