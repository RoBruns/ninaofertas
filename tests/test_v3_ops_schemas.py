"""Schemas e helpers V3 sem banco."""

from decimal import Decimal

from api.schemas.v3_ops import CouponRadarCreate, MirrorInboxPatch, VipCreate


def test_coupon_normaliza_codigo() -> None:
    cup = CouponRadarCreate(code="  superoferta ")
    assert cup.code == "SUPEROFERTA"


def test_mirror_inbox_patch_status() -> None:
    patch = MirrorInboxPatch(status="skipped", skip_reason="manual")
    assert patch.status == "skipped"


def test_vip_create_preco() -> None:
    vip = VipCreate(contact_name="Ana", wish_product="airfryer", max_price=Decimal("199.90"))
    assert vip.max_price == Decimal("199.90")
