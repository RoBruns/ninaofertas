import hashlib

from core.platforms.shopee_api import escape_graphql_string, sign


def test_escape_graphql_string_escapa_aspas_e_barras() -> None:
    assert escape_graphql_string('oferta "casa" \\ nova') == 'oferta \\"casa\\" \\\\ nova'


def test_assinatura_shopee() -> None:
    expected = hashlib.sha256(b"app123payloadsecret").hexdigest()
    assert sign("app", "secret", 123, "payload") == expected
