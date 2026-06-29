from sqlalchemy.orm import Session
from app.models.customer_model import Customer

def execute_tool(db: Session, tool_name: str, arguments: dict):
    # --- Read Operations ---
    if tool_name == "get_customers":
        customers = db.query(Customer).all()
        return [
            {
                "id": cust.id,
                "name": cust.name,
                "company": cust.company,
                "credit_limit": cust.credit_limit,
            }
            for cust in customers
        ]

    if tool_name == "get_customer_by_id":
        customer_id = arguments.get("customer_id")
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return {"error": "Customer not found"}

        return {
            "id": customer.id,
            "name": customer.name,
            "company": customer.company,
            "credit_limit": customer.credit_limit,
        }

    # --- Update Operations ---
    if tool_name == "update_credit_limit":
        customer_id = arguments.get("customer_id")
        new_credit_limit = arguments.get("new_credit_limit")

        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return {"error": "Customer not found"}

        customer.credit_limit = new_credit_limit
        db.commit()
        db.refresh(customer)

        return {
            "message": "Credit limit updated successfully",
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "company": customer.company,
                "credit_limit": customer.credit_limit,
            },
        }

    # --- Delete Operations (Updated for Policy Support) ---
    if tool_name == "delete_customer":
        customer_ids = arguments.get("customer_ids")
        customer_id = arguments.get("customer_id")

        # Case 1: Bulk Delete (List of IDs)
        if customer_ids and isinstance(customer_ids, list):
            deleted_count = 0
            for cust_id in customer_ids:
                customer = db.query(Customer).filter(Customer.id == cust_id).first()
                if customer:
                    db.delete(customer)
                    deleted_count += 1
            db.commit()
            return {"message": f"Bulk delete successful", "deleted_count": deleted_count}

        # Case 2: Single Delete
        if customer_id is not None:
            customer = db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                return {"error": "Customer not found"}

            db.delete(customer)
            db.commit()
            return {"message": f"Customer {customer_id} deleted successfully", "deleted_count": 1}

        return {"error": "Missing customer_id or customer_ids"}

    return {"error": f"Unknown tool: {tool_name}"}