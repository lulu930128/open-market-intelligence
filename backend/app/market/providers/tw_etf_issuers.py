from __future__ import annotations

from dataclasses import dataclass, replace

from app.market.providers.tw_etf_contracts import TaiwanEtfInstrumentIdentity


SITCA_ETF_ISSUER_SOURCE_URL = (
    "https://www.sitca.org.tw/ROC/SITCA_ETF/etf_info.aspx"
)


def _normalized_identity(value: str | None) -> str:
    return "".join(str(value or "").split()).casefold()


@dataclass(frozen=True)
class TaiwanEtfIssuer:
    issuer_code: str
    short_name: str
    aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.issuer_code.strip() or not self.short_name.strip():
            raise ValueError("ETF issuer code and name must not be empty.")


class TaiwanEtfIssuerCatalogError(RuntimeError):
    pass


class TaiwanEtfIssuerCatalog:
    def __init__(self, issuers: tuple[TaiwanEtfIssuer, ...]) -> None:
        self._issuers = issuers
        codes = [issuer.issuer_code for issuer in issuers]
        if len(codes) != len(set(codes)):
            raise ValueError("ETF issuer catalog contains duplicate issuer codes.")

    @property
    def issuers(self) -> tuple[TaiwanEtfIssuer, ...]:
        return self._issuers

    def get(self, issuer_code: str) -> TaiwanEtfIssuer | None:
        normalized_code = _normalized_identity(issuer_code)
        return next(
            (
                issuer
                for issuer in self._issuers
                if _normalized_identity(issuer.issuer_code) == normalized_code
            ),
            None,
        )

    def resolve(
        self,
        identity: TaiwanEtfInstrumentIdentity,
    ) -> TaiwanEtfIssuer | None:
        if identity.issuer_code:
            issuer = self.get(identity.issuer_code)
            if issuer is not None:
                return issuer
        candidates = tuple(
            _normalized_identity(value) for value in identity.name_candidates()
        )
        matches = [
            issuer
            for issuer in self._issuers
            if any(
                candidate.startswith(_normalized_identity(alias))
                for candidate in candidates
                for alias in issuer.aliases
                if _normalized_identity(alias)
            )
        ]
        if len(matches) > 1:
            codes = ", ".join(issuer.issuer_code for issuer in matches)
            raise TaiwanEtfIssuerCatalogError(
                f"ETF issuer identity for stock_id={identity.stock_id} matched "
                f"multiple issuer codes: {codes}."
            )
        return matches[0] if matches else None


DEFAULT_TAIWAN_ETF_ISSUER_CATALOG = TaiwanEtfIssuerCatalog(
    (
        TaiwanEtfIssuer("A0001", "兆豐投信", ("兆豐", "MEGA")),
        TaiwanEtfIssuer("A0003", "第一金投信", ("第一金", "FIRST")),
        TaiwanEtfIssuer("A0005", "元大投信", ("元大", "YUANTA")),
        TaiwanEtfIssuer("A0008", "玉山投信", ("玉山", "E.SUN")),
        TaiwanEtfIssuer("A0009", "統一投信", ("統一", "UPAMC")),
        TaiwanEtfIssuer("A0010", "富邦投信", ("富邦", "FUBON", "FB")),
        TaiwanEtfIssuer("A0011", "摩根投信", ("摩根", "JPMORGAN")),
        TaiwanEtfIssuer("A0012", "華南永昌投信", ("華南永昌", "華南")),
        TaiwanEtfIssuer("A0016", "群益投信", ("群益", "CAPITAL")),
        TaiwanEtfIssuer("A0018", "聯博投信", ("聯博", "ALLIANCEBERNSTEIN")),
        TaiwanEtfIssuer("A0022", "復華投信", ("復華", "FHC")),
        TaiwanEtfIssuer("A0025", "永豐投信", ("永豐", "SINOPAC")),
        TaiwanEtfIssuer("A0026", "中國信託投信", ("中國信託", "中信", "CTBC")),
        TaiwanEtfIssuer("A0031", "貝萊德投信", ("貝萊德", "BLACKROCK", "ISHARES")),
        TaiwanEtfIssuer("A0032", "野村投信", ("野村", "NOMURA")),
        TaiwanEtfIssuer("A0033", "聯邦投信", ("聯邦", "UNION")),
        TaiwanEtfIssuer("A0036", "安聯投信", ("安聯", "ALLIANZ")),
        TaiwanEtfIssuer("A0037", "國泰投信", ("國泰", "CATHAY")),
        TaiwanEtfIssuer("A0041", "凱基投信", ("凱基", "KGI")),
        TaiwanEtfIssuer(
            "A0045",
            "富蘭克林華美投信",
            ("富蘭克林華美", "FRANKLIN TEMPLETON SINOPAC"),
        ),
        TaiwanEtfIssuer("A0047", "台新投信", ("台新", "TAISHIN")),
        TaiwanEtfIssuer("A0049", "大華銀投信", ("大華銀", "UOB")),
    )
)


def canonicalize_taiwan_etf_identity(
    identity: TaiwanEtfInstrumentIdentity,
    *,
    catalog: TaiwanEtfIssuerCatalog = DEFAULT_TAIWAN_ETF_ISSUER_CATALOG,
) -> TaiwanEtfInstrumentIdentity:
    issuer = catalog.resolve(identity)
    if issuer is None:
        return identity
    return replace(
        identity,
        issuer_code=issuer.issuer_code,
        issuer_name=identity.issuer_name or issuer.short_name,
    )


__all__ = [
    "DEFAULT_TAIWAN_ETF_ISSUER_CATALOG",
    "SITCA_ETF_ISSUER_SOURCE_URL",
    "TaiwanEtfIssuer",
    "TaiwanEtfIssuerCatalog",
    "TaiwanEtfIssuerCatalogError",
    "canonicalize_taiwan_etf_identity",
]
