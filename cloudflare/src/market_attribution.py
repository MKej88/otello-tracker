from decimal import Decimal


def symmetric_two_factor_attribution(
    *,
    shares: int,
    anchor_price: Decimal,
    current_price: Decimal,
    anchor_fx: Decimal,
    current_fx: Decimal,
) -> dict[str, Decimal]:
    """Fordel pris- og valutaeffekt symmetrisk, uavhengig av rekkefølge."""
    quantity = Decimal(shares)
    total = quantity * (current_price * current_fx - anchor_price * anchor_fx)
    price_effect = (
        quantity
        * (current_price - anchor_price)
        * (anchor_fx + current_fx)
        / Decimal("2")
    )
    return {
        "total_change_nok": total,
        "price_effect_nok": price_effect,
        "fx_effect_nok": total - price_effect,
    }
