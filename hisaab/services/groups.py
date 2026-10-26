"""Groups, members, expenses and settlements on top of the pure split/settle engines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlmodel import Session, select

from hisaab.core import models as m
from hisaab.core.autosettle import Debt, Identity, match_credit
from hisaab.core.settle import Payment, net_balances, simplify_debts
from hisaab.core.splits import compute_split
from hisaab.core.upi import PaymentLine, build_upi_link, is_valid_vpa, whatsapp_summary
from hisaab.services.importing import to_parsed

# ---------------------------------------------------------------- groups and members


def create_group(
    session: Session,
    name: str,
    kind: m.GroupKind | str = m.GroupKind.OTHER,
    me: str = "Me",
    me_vpa: str | None = None,
) -> m.Group:
    """Create a group with the owner as its first member.

    ``me_vpa`` is the owner's UPI ID, used in the QR codes friends scan to pay them back.
    """
    name = name.strip()
    if not name:
        raise ValueError("group name is empty")
    vpa = (me_vpa or "").strip() or None
    if vpa and not is_valid_vpa(vpa):
        raise ValueError(f"invalid UPI ID: {vpa}")
    group = m.Group(name=name, kind=m.GroupKind(kind))
    session.add(group)
    session.flush()
    session.add(m.Member(group_id=group.id, name=me, is_me=True, upi_vpa=vpa))
    session.commit()
    return group


def list_groups(session: Session, include_archived: bool = False) -> list[m.Group]:
    q = select(m.Group)
    if not include_archived:
        q = q.where(m.Group.archived == False)  # noqa: E712 - SQL expression
    return list(session.exec(q.order_by(m.Group.created_at.desc(), m.Group.id.desc())).all())


def get_group(session: Session, group_id: int) -> m.Group:
    group = session.get(m.Group, group_id)
    if group is None:
        raise LookupError(f"group {group_id} not found")
    return group


def archive_group(session: Session, group_id: int, archived: bool = True) -> None:
    group = get_group(session, group_id)
    group.archived = archived
    session.add(group)
    session.commit()


def add_member(
    session: Session,
    group_id: int,
    name: str,
    upi_vpa: str | None = None,
    phone: str | None = None,
    aliases: str = "",
) -> m.Member:
    get_group(session, group_id)
    name = name.strip()
    if not name:
        raise ValueError("member name is empty")
    vpa = (upi_vpa or "").strip() or None
    if vpa and not is_valid_vpa(vpa):
        raise ValueError(f"invalid UPI ID: {vpa}")
    if any(x.name.lower() == name.lower() for x in list_members(session, group_id)):
        raise ValueError(f"{name} is already in this group")
    member = m.Member(group_id=group_id, name=name, upi_vpa=vpa, phone=phone, aliases=aliases)
    session.add(member)
    session.commit()
    return member


def update_member(session: Session, member_id: int, **changes) -> m.Member:
    member = session.get(m.Member, member_id)
    if member is None:
        raise LookupError(f"member {member_id} not found")
    if "upi_vpa" in changes:
        changes["upi_vpa"] = (changes["upi_vpa"] or "").strip() or None
    if changes.get("upi_vpa") and not is_valid_vpa(changes["upi_vpa"]):
        raise ValueError(f"invalid UPI ID: {changes['upi_vpa']}")
    for key in ("name", "upi_vpa", "phone", "aliases"):
        if key in changes:
            setattr(member, key, changes[key])
    session.add(member)
    session.commit()
    return member


def list_members(session: Session, group_id: int) -> list[m.Member]:
    q = select(m.Member).where(m.Member.group_id == group_id).order_by(m.Member.id)
    return list(session.exec(q).all())


def get_me(session: Session, group_id: int) -> m.Member:
    for member in list_members(session, group_id):
        if member.is_me:
            return member
    raise LookupError(f"group {group_id} has no owner member")


# ---------------------------------------------------------------- expenses


def add_expense(
    session: Session,
    group_id: int,
    description: str,
    total_paise: int,
    paid_by: int,
    participants: Sequence[int],
    split_type: m.SplitType | str = m.SplitType.EQUAL,
    values: Mapping[int, float | int | str] | None = None,
    spent_at: datetime | None = None,
    transaction_id: int | None = None,
) -> m.Expense:
    """Create an expense and its shares. Shares always sum to the total in paise."""
    member_ids = {x.id for x in list_members(session, group_id)}
    if paid_by not in member_ids:
        raise ValueError("payer is not in this group")
    if not participants or not set(participants) <= member_ids:
        raise ValueError("participants must be members of this group")
    shares = compute_split(split_type, total_paise, list(participants), values)
    expense = m.Expense(
        group_id=group_id,
        transaction_id=transaction_id,
        description=description.strip() or "Expense",
        total_paise=total_paise,
        paid_by_member_id=paid_by,
        split_type=m.SplitType(split_type),
        spent_at=spent_at or m.now(),
    )
    session.add(expense)
    session.flush()
    for member_id, share in shares.items():
        value = (values or {}).get(member_id)
        session.add(
            m.ExpenseShare(
                expense_id=expense.id,
                member_id=member_id,
                share_paise=share,
                share_value=float(value) if value is not None else None,
            )
        )
    session.commit()
    return expense


def expense_from_txn(
    session: Session,
    txn_id: int,
    group_id: int,
    participants: Sequence[int],
    split_type: m.SplitType | str = m.SplitType.EQUAL,
    values: Mapping[int, float | int | str] | None = None,
    description: str | None = None,
) -> m.Expense:
    """Send an imported debit to a group as a split paid by the owner."""
    txn = session.get(m.Txn, txn_id)
    if txn is None:
        raise LookupError(f"transaction {txn_id} not found")
    if txn.direction is not m.Direction.DEBIT:
        raise ValueError("only money you paid can be split")
    if txn.is_split:
        raise ValueError("transaction is already split")
    desc = description or txn.merchant or txn.counterparty_name or "Expense"
    expense = add_expense(
        session,
        group_id,
        desc,
        txn.amount_paise,
        get_me(session, group_id).id,
        participants,
        split_type,
        values,
        txn.txn_at,
        txn.id,
    )
    txn.is_split = True
    session.add(txn)
    session.commit()
    return expense


def list_expenses(session: Session, group_id: int) -> list[m.Expense]:
    q = select(m.Expense).where(m.Expense.group_id == group_id)
    return list(session.exec(q.order_by(m.Expense.spent_at.desc(), m.Expense.id.desc())).all())


def expense_shares(session: Session, expense_id: int) -> dict[int, int]:
    q = select(m.ExpenseShare).where(m.ExpenseShare.expense_id == expense_id)
    return {s.member_id: s.share_paise for s in session.exec(q).all()}


def delete_expense(session: Session, expense_id: int) -> None:
    expense = session.get(m.Expense, expense_id)
    if expense is None:
        raise LookupError(f"expense {expense_id} not found")
    for share in session.exec(
        select(m.ExpenseShare).where(m.ExpenseShare.expense_id == expense_id)
    ).all():
        session.delete(share)
    session.flush()  # shares must go before the expense (no ORM relationship orders them)
    if expense.transaction_id:
        txn = session.get(m.Txn, expense.transaction_id)
        if txn is not None:
            txn.is_split = False
            session.add(txn)
    session.delete(expense)
    session.commit()


# ---------------------------------------------------------------- balances and settlements


def group_balances(session: Session, group_id: int) -> dict[int, int]:
    """Net balance per member id, from expenses and *confirmed* settlements only."""
    expenses = list_expenses(session, group_id)
    paid = [(e.paid_by_member_id, e.total_paise) for e in expenses]
    shares: list[tuple[int, int]] = []
    for e in expenses:
        shares.extend(expense_shares(session, e.id).items())
    q = select(m.Settlement).where(
        m.Settlement.group_id == group_id, m.Settlement.status == m.SettlementStatus.CONFIRMED
    )
    settled = [(s.from_member_id, s.to_member_id, s.amount_paise) for s in session.exec(q).all()]
    members = [x.id for x in list_members(session, group_id)]
    return net_balances(paid, shares, settled, members)


def settle_plan(session: Session, group_id: int) -> list[Payment[int]]:
    """Fewest payments that bring every balance in the group to zero."""
    return simplify_debts(group_balances(session, group_id))


def record_settlement(
    session: Session,
    group_id: int,
    from_member: int,
    to_member: int,
    amount_paise: int,
    method: m.SettlementMethod = m.SettlementMethod.MANUAL,
    status: m.SettlementStatus = m.SettlementStatus.CONFIRMED,
    transaction_id: int | None = None,
) -> m.Settlement:
    if amount_paise <= 0:
        raise ValueError("settlement amount must be positive")
    if from_member == to_member:
        raise ValueError("a member cannot pay themselves")
    ids = {x.id for x in list_members(session, group_id)}
    if from_member not in ids or to_member not in ids:
        raise ValueError("both members must be in the group")
    s = m.Settlement(
        group_id=group_id,
        from_member_id=from_member,
        to_member_id=to_member,
        amount_paise=amount_paise,
        method=method,
        status=status,
        transaction_id=transaction_id,
    )
    session.add(s)
    session.commit()
    return s


def list_settlements(
    session: Session, group_id: int | None = None, status: m.SettlementStatus | None = None
) -> list[m.Settlement]:
    q = select(m.Settlement)
    if group_id is not None:
        q = q.where(m.Settlement.group_id == group_id)
    if status is not None:
        q = q.where(m.Settlement.status == status)
    return list(session.exec(q.order_by(m.Settlement.id)).all())


def set_settlement_status(
    session: Session, settlement_id: int, status: m.SettlementStatus
) -> m.Settlement:
    s = session.get(m.Settlement, settlement_id)
    if s is None:
        raise LookupError(f"settlement {settlement_id} not found")
    s.status = status
    if status is m.SettlementStatus.CONFIRMED:
        s.settled_at = m.now()
    session.add(s)
    session.commit()
    return s


def confirm_settlement(session: Session, settlement_id: int) -> m.Settlement:
    return set_settlement_status(session, settlement_id, m.SettlementStatus.CONFIRMED)


def reject_settlement(session: Session, settlement_id: int) -> m.Settlement:
    return set_settlement_status(session, settlement_id, m.SettlementStatus.REJECTED)


# ---------------------------------------------------------------- auto-settle


def pending_debts_to_me(session: Session) -> tuple[list[Debt], list[Identity]]:
    """Every planned payment *to the owner*, minus already-proposed amounts, across groups."""
    debts: list[Debt] = []
    identities: list[Identity] = []
    for group in list_groups(session):
        me = get_me(session, group.id)
        proposed: dict[int, int] = {}
        for s in list_settlements(session, group.id, m.SettlementStatus.PROPOSED):
            if s.to_member_id == me.id:
                proposed[s.from_member_id] = proposed.get(s.from_member_id, 0) + s.amount_paise
        for p in settle_plan(session, group.id):
            if p.payee == me.id:
                left = p.amount_paise - proposed.get(p.payer, 0)
                if left > 0:
                    debts.append(Debt(p.payer, me.id, left, group.id))
        for x in list_members(session, group.id):
            if not x.is_me:
                identities.append(Identity(x.id, x.name, x.upi_vpa, tuple(x.alias_list())))
    return debts, identities


def propose_settlements(session: Session, txn_ids: Sequence[int]) -> list[m.Settlement]:
    """For each new credit transaction, propose settling the best-matching debt."""
    proposals: list[m.Settlement] = []
    for txn_id in txn_ids:
        txn = session.get(m.Txn, txn_id)
        if txn is None or txn.direction is not m.Direction.CREDIT:
            continue
        already = session.exec(
            select(m.Settlement).where(m.Settlement.transaction_id == txn_id)
        ).first()
        if already:
            continue
        debts, identities = pending_debts_to_me(session)
        match = match_credit(to_parsed(txn), debts, identities)
        if match is None:
            continue
        proposals.append(
            record_settlement(
                session,
                match.debt.group_id,
                match.debt.debtor,
                match.debt.creditor,
                match.amount_paise,
                method=m.SettlementMethod.UPI_SMS,
                status=m.SettlementStatus.PROPOSED,
                transaction_id=txn.id,
            )
        )
    return proposals


# ---------------------------------------------------------------- sharing


def payment_lines(session: Session, group_id: int, note: str | None = None) -> list[PaymentLine]:
    """Settle-up plan with a UPI link wherever the payee has a UPI ID."""
    group = get_group(session, group_id)
    by_id = {x.id: x for x in list_members(session, group_id)}
    lines = []
    for p in settle_plan(session, group_id):
        payee = by_id[p.payee]
        link = None
        if payee.upi_vpa:
            link = build_upi_link(
                payee.upi_vpa, payee.name, p.amount_paise, note or f"Hisaab {group.name}"
            )
        lines.append(PaymentLine(by_id[p.payer].name, payee.name, p.amount_paise, link))
    return lines


def group_summary(session: Session, group_id: int) -> str:
    """WhatsApp-ready settle-up message."""
    return whatsapp_summary(get_group(session, group_id).name, payment_lines(session, group_id))


def import_and_propose(session: Session, messages, **kwargs):
    """Import SMS, then propose settlements for any credits that repay a friend's debt.

    Returns ``(ImportReport, proposals)``. This is the full Hisaab loop in one call.
    """
    from hisaab.services.importing import import_messages

    report = import_messages(session, messages, **kwargs)
    return report, propose_settlements(session, report.txn_ids)
