"""Phase 6 — offline end-to-end pilot transaction (no paid providers)."""
from scripts.pilot_transaction import run_pilot


async def test_pilot_transaction_loop():
    result = await run_pilot()
    assert result["escrow_status"] == "released"
    assert result["contractor_payout"] > 0
    assert result["platform_fee"] > 0
    # Contractor payout is the quote minus the platform fee.
    assert abs(result["contractor_payout"] + result["platform_fee"] - 120.0) < 1e-6
