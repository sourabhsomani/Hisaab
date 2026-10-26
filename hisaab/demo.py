"""Synthetic demo data: three months of fake bank SMS plus a trip group, so visitors to the
Hugging Face demo can try the full loop. Every name, account and number here is invented."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlmodel import Session

from hisaab.parsers.pipeline import Message
from hisaab.services import groups as gsvc
from hisaab.services.importing import import_messages

MERCHANTS = [
    ("Swiggy", 180, 650),
    ("Zomato", 200, 800),
    ("Blinkit", 120, 900),
    ("Zepto", 90, 600),
    ("Uber", 90, 450),
    ("Amazon", 300, 2500),
    ("Indian Oil", 500, 2000),
    ("Airtel", 299, 999),
    ("BigBasket", 400, 2200),
    ("BookMyShow", 250, 900),
]
FRIENDS = [
    ("ANANYA RAO", "ananya.r@okaxis"),
    ("KABIR SETHI", "kabir.s@ybl"),
    ("ISHA MENON", "isha.m@okhdfcbank"),
]


def _ref(rng: random.Random) -> str:
    return str(rng.randint(400000000000, 499999999999))


def _hdfc_card(rng: random.Random, when: datetime, merchant: str, rupees: int) -> Message:
    body = (
        f"Spent Rs.{rupees}.00 On HDFC Bank Card 4821 At RAZ*{merchant.upper()} On "
        f"{when:%Y-%m-%d:%H:%M:%S} Bal Rs.{rng.randint(5000, 90000)}.00 Not You? "
        "Call 18002586161"
    )
    return Message("AX-HDFCBK", body, when)


def _icici_upi(rng: random.Random, when: datetime, merchant: str, rupees: int) -> Message:
    body = (
        f"ICICI Bank Acct XX777 debited for Rs {rupees}.00 on {when:%d-%b-%y}; "
        f"{merchant.upper()} credited. UPI:{_ref(rng)}. Call 18002662 for dispute."
    )
    return Message("AX-ICICIB", body, when)


def demo_messages(seed: int = 7, months: int = 3, end: date | None = None) -> list[Message]:
    """Deterministic synthetic SMS: card and UPI spends, rent, and a friend's repayment."""
    rng = random.Random(seed)
    end = end or date.today()
    start = end - timedelta(days=30 * months)
    out: list[Message] = []
    day = start
    while day <= end:
        for _ in range(rng.choice([0, 1, 1, 2])):
            merchant, lo, hi = rng.choice(MERCHANTS)
            when = datetime.combine(day, datetime.min.time()) + timedelta(
                hours=rng.randint(8, 22), minutes=rng.randint(0, 59)
            )
            maker = rng.choice([_hdfc_card, _icici_upi])
            out.append(maker(rng, when, merchant, rng.randint(lo, hi)))
        if day.day == 1:
            when = datetime.combine(day, datetime.min.time()) + timedelta(hours=10)
            out.append(
                Message(
                    "JD-SBIUPI",
                    f"Dear UPI user A/C X3141 debited by 18000.00 on date {when:%d%b%y} trf to "
                    f"PRAKASH LANDLORD Refno {_ref(rng)}. If not u? call 1800111109. -SBI",
                    when,
                )
            )
        day += timedelta(days=1)
    out.append(Message("AX-HDFCBK", "123456 is your OTP for Rs.999 at AMAZON. Do not share."))
    return out


def repayment_sms(when: datetime, name: str, rupees: int) -> Message:
    return Message(
        "VM-ICICIT",
        f"Dear Customer, Acct XX777 is credited with Rs {rupees}.00 on {when:%d-%b-%y} from "
        f"{name}. UPI:{random.Random(rupees).randint(400000000000, 499999999999)}-ICICI Bank.",
        when,
    )


def seed_demo(session: Session, seed: int = 7, end: date | None = None) -> dict:
    """Load demo SMS, a Goa trip with three friends, and one auto-detected repayment."""
    end = end or date.today()
    report = import_messages(session, demo_messages(seed, end=end))
    trip = gsvc.create_group(session, "Goa trip", "trip", me="Me")
    me = gsvc.get_me(session, trip.id).id
    ids = [me]
    for name, vpa in FRIENDS:
        ids.append(gsvc.add_member(session, trip.id, name.title(), vpa, aliases=name).id)
    when = datetime.combine(end - timedelta(days=10), datetime.min.time())
    gsvc.add_expense(session, trip.id, "Villa", 2400000, me, ids, spent_at=when)
    gsvc.add_expense(
        session, trip.id, "Scooter rental", 360000, ids[1], ids, spent_at=when + timedelta(hours=5)
    )
    gsvc.add_expense(
        session,
        trip.id,
        "Seafood dinner",
        480000,
        ids[2],
        ids,
        "shares",
        {me: 2, ids[1]: 1, ids[2]: 2, ids[3]: 1},
        spent_at=when + timedelta(days=1),
    )
    # The first friend who owes me pays back over UPI; Hisaab spots it in the credit SMS.
    debts, _ = gsvc.pending_debts_to_me(session)
    proposals = []
    if debts:
        debtor = next(x for x in gsvc.list_members(session, trip.id) if x.id == debts[0].debtor)
        sms = repayment_sms(
            when + timedelta(days=3), debtor.name.upper(), debts[0].amount_paise // 100
        )
        _, proposals = gsvc.import_and_propose(session, [sms])
    flat = gsvc.create_group(session, "Flat 302", "flat")
    flat_me = gsvc.get_me(session, flat.id).id
    roomie = gsvc.add_member(session, flat.id, "Kabir Sethi", "kabir.s@ybl").id
    gsvc.add_expense(session, flat.id, "Wi-Fi", 99900, roomie, [flat_me, roomie])
    return {
        "messages": report.total,
        "transactions": len(report.txn_ids),
        "groups": 2,
        "proposals": len(proposals),
    }
