TOOLS = [
    {
        "type": "function",
        "name": "get_customers",
        "description": "Get the full list of customers.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "get_customer_by_id",
        "description": "Get one customer by customer ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer ID"
                }
            },
            "required": ["customer_id"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "update_credit_limit",
        "description": "Update the credit limit of a customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer ID"
                },
                "new_credit_limit": {
                    "type": "integer",
                    "description": "The new credit limit"
                }
            },
            "required": ["customer_id", "new_credit_limit"],
            "additionalProperties": False
        }
    },
    {
        "type": "function",
        "name": "delete_customer",
        "description": "Delete a customer by customer ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "The customer ID"
                }
            },
            "required": ["customer_id"],
            "additionalProperties": False
        }
    }
]