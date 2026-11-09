from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import require_operator
from app.database import Customer, get_db
from app.schemas.auth import OperatorIdentity
from app.schemas.customers import CreateCustomerRequest, CustomerResponse


router = APIRouter()


@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=201,
    tags=["customers"],
)
def create_customer(
    body: CreateCustomerRequest,
    db: Session = Depends(get_db),
    operator: OperatorIdentity = Depends(require_operator),
):
    customer = Customer(
        display_name=body.display_name,
        owner_operator_id=operator.id,
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    tags=["customers"],
)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, customer_id)

    if customer is None:
        raise HTTPException(
            status_code=404,
            detail="Customer not found",
        )

    return customer
