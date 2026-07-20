from app.models import Balance


def test_only_creditor_may_confirm_settle():
    # net > 0 → partner 2 owes partner 1, so partner 1 is the creditor.
    bal = Balance(partner1_id=1, partner2_id=2, net_cents=20000)
    assert bal.creditor_id == 1
    assert bal.may_confirm_settle(1) is True   # creditor can confirm
    assert bal.may_confirm_settle(2) is False  # debtor cannot


def test_debtor_side_reversed():
    # net < 0 → partner 1 owes partner 2, so partner 2 is the creditor.
    bal = Balance(partner1_id=1, partner2_id=2, net_cents=-500)
    assert bal.creditor_id == 2
    assert bal.may_confirm_settle(2) is True
    assert bal.may_confirm_settle(1) is False


def test_when_square_either_partner_may_confirm():
    bal = Balance(partner1_id=1, partner2_id=2, net_cents=0)
    assert bal.creditor_id is None
    assert bal.may_confirm_settle(1) is True
    assert bal.may_confirm_settle(2) is True
