from sentinelfi.services.text_utils import extract_upi_signals, normalize_descriptor, scrub_pii


def test_scrub_pii_masks_phone_and_email() -> None:
    text = "Contact 9876543210 or owner@example.com"
    out = scrub_pii(text, "salt")
    assert "9876543210" not in out
    assert "owner@example.com" not in out
    assert "<PHONE:" in out
    assert "<EMAIL:" in out


def test_normalize_descriptor() -> None:
    text = "UPI/RAHUL@okicici/AWS-CLOUD!!"
    assert normalize_descriptor(text) == "upi rahul@okicici aws cloud"


def test_extract_upi_signals_identifies_merchant_hint() -> None:
    text = "upi/p2m/swiggyinstamart@okaxis/txn 123456789012"
    signals = extract_upi_signals(text)
    assert signals["is_upi"] is True
    assert signals["merchant_token"] == "swiggy"
    assert signals["p2m_likely"] is True


def test_scrub_pii_preserves_upi_merchant_signal() -> None:
    text = "upi/swiggyinstamart@okaxis/order"
    out = scrub_pii(text, "salt")
    assert "<UPI_MERCHANT:swiggy>" in out
