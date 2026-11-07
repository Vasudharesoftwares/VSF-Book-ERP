"""
Standalone perpetual Weighted Average Cost engine.

SAFETY:
- Accepts an already-open SQLite connection.
- Does not open tenant databases.
- Does not commit or roll back transactions.
- Does not modify stock_balances or accounting journals.
- Caller owns the transaction.
- Intended for isolated testing before route integration.
"""

import math
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class WACError(Exception):
    """Base exception for WAC costing errors."""


class OpeningCostReviewRequired(WACError):
    """Existing inventory has no verified opening cost."""


class InsufficientCostedStock(WACError):
    """Requested stock issue exceeds verified costed stock."""


class DuplicateMovement(WACError):
    """A movement key has already been used."""


class InvalidCostInput(WACError):
    """Invalid quantity or cost supplied to the engine."""


def _decimal(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidCostInput(f"Invalid {field}.")

    if not result.is_finite():
        raise InvalidCostInput(f"{field} must be a finite number.")

    return result


def _quantity(value):
    result = _decimal(value, "quantity")

    if result <= 0:
        raise InvalidCostInput("Quantity must be greater than zero.")

    return result.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _money(value):
    return _decimal(value, "amount").quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _float(value):
    return float(value)


def _require_schema(db):
    required = {
        "inventory_cost_balances",
        "inventory_cost_movements",
        "stock_balances",
    }

    existing = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    missing = required - existing

    if missing:
        raise WACError(
            "Required tables missing: " + ", ".join(sorted(missing))
        )


def _existing_movement(db, movement_key):
    return db.execute(
        """
        SELECT id, movement_key
        FROM inventory_cost_movements
        WHERE movement_key=?
        """,
        (movement_key,),
    ).fetchone()


def _load_balance(db, branch_id, product_id, create_zero=False):
    row = db.execute(
        """
        SELECT id, physical_quantity, inventory_value,
               average_unit_cost, cost_status
        FROM inventory_cost_balances
        WHERE branch_id=? AND product_id=?
        """,
        (branch_id, product_id),
    ).fetchone()

    if row:
        return {
            "id": row[0],
            "quantity": row[1],
            "value": row[2],
            "average_cost": row[3],
            "status": row[4],
        }

    physical = db.execute(
        """
        SELECT quantity
        FROM stock_balances
        WHERE branch_id=? AND product_id=?
        """,
        (branch_id, product_id),
    ).fetchone()

    existing_quantity = (
        _decimal(physical[0], "existing stock quantity")
        if physical else Decimal("0")
    )

    if existing_quantity != 0:
        raise OpeningCostReviewRequired(
            "Physical stock exists but no WAC balance is recorded. "
            "Verify its opening cost before automatic costing."
        )

    if not create_zero:
        raise WACError("WAC balance does not exist for this product and branch.")

    db.execute(
        """
        INSERT INTO inventory_cost_balances
        (
            branch_id, product_id, physical_quantity,
            inventory_value, average_unit_cost, cost_status
        )
        VALUES (?, ?, 0, 0, NULL, 'verified')
        """,
        (branch_id, product_id),
    )

    balance_id = db.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    return {
        "id": balance_id,
        "quantity": 0,
        "value": 0,
        "average_cost": None,
        "status": "verified",
    }


def _validate_costed_balance(balance):
    if balance["status"] != "verified":
        raise OpeningCostReviewRequired(
            "Inventory costing is blocked: opening cost requires review."
        )

    if balance["quantity"] is None or balance["value"] is None:
        raise OpeningCostReviewRequired(
            "Inventory quantity or value is unknown."
        )

    quantity = _decimal(balance["quantity"], "inventory quantity")
    value = _decimal(balance["value"], "inventory value")

    if quantity < 0 or value < 0:
        raise WACError("Negative inventory quantity or value is not permitted.")

    if quantity > 0 and balance["average_cost"] is None:
        raise OpeningCostReviewRequired(
            "Positive stock has no verified average unit cost."
        )

    if quantity == 0 and value != 0:
        raise WACError(
            "Zero inventory quantity has a non-zero inventory value."
        )

    return quantity, value


def _record_movement(
    db,
    *,
    movement_key,
    branch_id,
    product_id,
    movement_type,
    reference_type,
    reference_id,
    reference_line_id,
    quantity_in,
    quantity_out,
    unit_cost,
    value_in,
    value_out,
    quantity_after,
    inventory_value_after,
    cost_status,
    notes,
):
    if not movement_key or not str(movement_key).strip():
        raise InvalidCostInput("A unique movement key is required.")

    if _existing_movement(db, movement_key):
        raise DuplicateMovement(
            f"Movement key already exists: {movement_key}"
        )

    try:
        cursor = db.execute(
            """
            INSERT INTO inventory_cost_movements
            (
                movement_key, branch_id, product_id,
                movement_type, reference_type, reference_id,
                reference_line_id, quantity_in, quantity_out,
                unit_cost, value_in, value_out,
                quantity_after, inventory_value_after,
                cost_status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                movement_key,
                branch_id,
                product_id,
                movement_type,
                reference_type,
                reference_id,
                reference_line_id,
                _float(quantity_in),
                _float(quantity_out),
                None if unit_cost is None else _float(unit_cost),
                None if value_in is None else _float(value_in),
                None if value_out is None else _float(value_out),
                _float(quantity_after),
                _float(inventory_value_after),
                cost_status,
                notes,
            ),
        )
    except sqlite3.IntegrityError as exc:
        if _existing_movement(db, movement_key):
            raise DuplicateMovement(
                f"Movement key already exists: {movement_key}"
            ) from exc
        raise

    movement_id = cursor.lastrowid

    db.execute(
        """
        UPDATE inventory_cost_balances
        SET physical_quantity=?,
            inventory_value=?,
            average_unit_cost=?,
            cost_status=?,
            last_movement_id=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE branch_id=? AND product_id=?
        """,
        (
            _float(quantity_after),
            _float(inventory_value_after),
            (
                _float(inventory_value_after / quantity_after)
                if quantity_after > 0 else None
            ),
            cost_status,
            movement_id,
            branch_id,
            product_id,
        ),
    )

    return {
        "movement_id": movement_id,
        "movement_key": movement_key,
        "quantity_after": _float(quantity_after),
        "inventory_value_after": _float(inventory_value_after),
        "average_unit_cost": (
            _float(inventory_value_after / quantity_after)
            if quantity_after > 0 else None
        ),
        "cost_status": cost_status,
    }


def receive_inventory(
    db,
    *,
    movement_key,
    branch_id,
    product_id,
    quantity,
    unit_cost,
    movement_type="purchase_receipt",
    reference_type=None,
    reference_id=None,
    reference_line_id=None,
    notes=None,
):
    """
    Add verified-cost inventory using perpetual weighted average.

    Caller must update physical stock and accounting separately,
    inside the same outer transaction when integrated.
    """
    _require_schema(db)

    qty = _quantity(quantity)
    cost = _money(unit_cost)

    if cost < 0:
        raise InvalidCostInput("Unit cost cannot be negative.")

    if _existing_movement(db, movement_key):
        raise DuplicateMovement(f"Movement key already exists: {movement_key}")

    balance = _load_balance(
        db, branch_id, product_id, create_zero=True
    )

    old_qty, old_value = _validate_costed_balance(balance)

    incoming_value = _money(qty * cost)
    new_qty = old_qty + qty
    new_value = _money(old_value + incoming_value)

    return _record_movement(
        db,
        movement_key=movement_key,
        branch_id=branch_id,
        product_id=product_id,
        movement_type=movement_type,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_line_id=reference_line_id,
        quantity_in=qty,
        quantity_out=Decimal("0"),
        unit_cost=cost,
        value_in=incoming_value,
        value_out=Decimal("0"),
        quantity_after=new_qty,
        inventory_value_after=new_value,
        cost_status="verified",
        notes=notes,
    )


def issue_inventory(
    db,
    *,
    movement_key,
    branch_id,
    product_id,
    quantity,
    movement_type="sale",
    reference_type=None,
    reference_id=None,
    reference_line_id=None,
    notes=None,
):
    """
    Remove inventory at the current WAC and return its captured cost.

    Historical sale costs must be stored by the caller at posting time.
    """
    _require_schema(db)

    qty = _quantity(quantity)

    if _existing_movement(db, movement_key):
        raise DuplicateMovement(f"Movement key already exists: {movement_key}")

    balance = _load_balance(
        db, branch_id, product_id, create_zero=False
    )

    old_qty, old_value = _validate_costed_balance(balance)

    if qty > old_qty:
        raise InsufficientCostedStock(
            "Requested quantity exceeds verified costed inventory."
        )

    average_cost = _decimal(
        balance["average_cost"], "average unit cost"
    )

    # If all remaining stock is issued, clear any rounding residue.
    if qty == old_qty:
        outgoing_value = old_value
        new_value = Decimal("0.00")
    else:
        outgoing_value = _money(qty * average_cost)
        new_value = _money(old_value - outgoing_value)

    new_qty = old_qty - qty

    if new_value < 0:
        raise WACError("Issue would produce negative inventory value.")

    result = _record_movement(
        db,
        movement_key=movement_key,
        branch_id=branch_id,
        product_id=product_id,
        movement_type=movement_type,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_line_id=reference_line_id,
        quantity_in=Decimal("0"),
        quantity_out=qty,
        unit_cost=average_cost,
        value_in=Decimal("0"),
        value_out=outgoing_value,
        quantity_after=new_qty,
        inventory_value_after=new_value,
        cost_status="verified",
        notes=notes,
    )

    result["issued_unit_cost"] = _float(average_cost)
    result["issued_cost_total"] = _float(outgoing_value)

    return result


def adjust_inventory(
    db,
    *,
    movement_key,
    branch_id,
    product_id,
    quantity_change,
    reason,
    verified_unit_cost=None,
):
    """
    Positive adjustment requires an explicit verified unit cost.
    Negative adjustment removes stock at current WAC.
    """
    change = _decimal(quantity_change, "quantity change")

    if change == 0:
        raise InvalidCostInput("Quantity change cannot be zero.")

    if not reason or not str(reason).strip():
        raise InvalidCostInput("Adjustment reason is required.")

    if change > 0:
        if verified_unit_cost is None:
            raise InvalidCostInput(
                "Positive stock adjustment requires a verified unit cost."
            )

        return receive_inventory(
            db,
            movement_key=movement_key,
            branch_id=branch_id,
            product_id=product_id,
            quantity=change,
            unit_cost=verified_unit_cost,
            movement_type="manual_adjustment_in",
            reference_type="manual_adjustment",
            notes=reason,
        )

    return issue_inventory(
        db,
        movement_key=movement_key,
        branch_id=branch_id,
        product_id=product_id,
        quantity=abs(change),
        movement_type="manual_adjustment_out",
        reference_type="manual_adjustment",
        notes=reason,
    )

def adjust_inventory_value(
    db,
    *,
    movement_key,
    branch_id,
    product_id,
    value_change,
    reason,
    reference_type=None,
    reference_id=None,
    reference_line_id=None,
):
    """
    Change inventory valuation without changing physical quantity.

    Positive value_change increases inventory value.
    Negative value_change decreases inventory value.

    Requires verified positive stock and a non-negative resulting value.
    Caller owns the transaction. No stock quantity or journal is posted here.
    """
    _require_schema(db)

    if not reason or not str(reason).strip():
        raise InvalidCostInput("Adjustment reason is required.")

    if not movement_key or not str(movement_key).strip():
        raise InvalidCostInput("A unique movement key is required.")

    if _existing_movement(db, movement_key):
        raise DuplicateMovement(
            f"Movement key already exists: {movement_key}"
        )

    change = _money(value_change)

    if change == 0:
        raise InvalidCostInput("Value change cannot be zero.")

    balance = _load_balance(
        db, branch_id, product_id, create_zero=False
    )

    old_qty, old_value = _validate_costed_balance(balance)

    if old_qty <= 0:
        raise InvalidCostInput(
            "Value-only adjustment requires positive verified stock."
        )

    new_value = _money(old_value + change)

    if new_value < 0:
        raise InvalidCostInput(
            "Value adjustment cannot produce negative inventory value."
        )

    new_average = _money(new_value / old_qty)

    result = _record_movement(
        db,
        movement_key=movement_key,
        branch_id=branch_id,
        product_id=product_id,
        movement_type="inventory_value_adjustment",
        reference_type=reference_type,
        reference_id=reference_id,
        reference_line_id=reference_line_id,
        quantity_in=Decimal("0"),
        quantity_out=Decimal("0"),
        unit_cost=new_average,
        value_in=max(change, Decimal("0")),
        value_out=max(-change, Decimal("0")),
        quantity_after=old_qty,
        inventory_value_after=new_value,
        cost_status="verified",
        notes=reason,
    )

    result["value_change"] = _float(change)
    result["previous_inventory_value"] = _float(old_value)
    result["previous_average_unit_cost"] = (
        _float(old_value / old_qty)
    )
    return result
