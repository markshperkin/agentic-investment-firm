from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

EDGAR_FORMS = ("10-K", "10-Q", "8-K")
USER_AGENT = "agentic-investment-firm research contact@example.com"


@dataclass
class RawFiling:
    ticker: str
    form_type: str
    source_url: str
    published_at: datetime  # EDGAR acceptance datetime
    text: str


class FilingSource(Protocol):
    def fetch(self, ticker: str, since: datetime, until: datetime) -> list[RawFiling]:
        ...


class EdgarSource:
    """Live SEC EDGAR. Lazy import of httpx; pulls the submissions index, filters
    by form + acceptance datetime, and downloads the primary document text.
    Runs against the network (locally) — unit tests use FakeFilingSource."""

    def __init__(self, forms: tuple[str, ...] = EDGAR_FORMS):
        self.forms = forms

    def _client(self):
        import httpx

        return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30)

    def _cik(self, client, ticker: str) -> str:
        tickers = client.get("https://www.sec.gov/files/company_tickers.json").json()
        for row in tickers.values():
            if row["ticker"].upper() == ticker.upper():
                return str(row["cik_str"]).zfill(10)
        raise ValueError(f"CIK not found for {ticker}")

    def fetch(self, ticker: str, since: datetime, until: datetime) -> list[RawFiling]:
        import re

        client = self._client()
        cik = self._cik(client, ticker)
        subs = client.get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        recent = subs["filings"]["recent"]
        out: list[RawFiling] = []
        for form, acc, doc, dt in zip(
            recent["form"], recent["accessionNumber"],
            recent["primaryDocument"], recent["acceptanceDateTime"],
        ):
            if form not in self.forms:
                continue
            published = datetime.fromisoformat(dt.replace("Z", "+00:00")).replace(tzinfo=None)
            if not (since <= published <= until):
                continue
            acc_nodash = acc.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{doc}"
            html = client.get(url).text
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"&[a-z]+;", " ", text)
            out.append(RawFiling(ticker, form, url, published, text))
        return out


class FakeFilingSource:
    """In-memory source for tests."""

    def __init__(self, filings: list[RawFiling]):
        self._filings = filings

    def fetch(self, ticker: str, since: datetime, until: datetime) -> list[RawFiling]:
        return [
            f for f in self._filings
            if f.ticker == ticker and since <= f.published_at <= until
        ]
