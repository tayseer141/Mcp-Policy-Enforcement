"""
Backwards-compatibility shim.

The Employee model was renamed to Customer (table: ``customers``). This
module now re-exports Customer so any lingering
``from app.models.employee_model import Employee`` keeps working and maps
to the same `customers` table — it does NOT define a separate `employees`
table.
"""

from app.models.customer_model import Customer

# Alias kept only for backward-compatibility with any unmigrated import.
Employee = Customer

__all__ = ["Customer", "Employee"]