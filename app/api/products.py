from fastapi import APIRouter, Depends

from app.dependencies import AppRuntime, get_runtime
from app.schemas.products import ProductOption


router = APIRouter()


@router.get("/products", response_model=list[ProductOption], tags=["products"])
def list_products(runtime: AppRuntime = Depends(get_runtime)):
    return runtime.repository.list_published_products()