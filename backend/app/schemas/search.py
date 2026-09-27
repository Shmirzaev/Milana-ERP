from pydantic import BaseModel


class SearchResultOut(BaseModel):
    type: str
    id: int
    label: str
    url: str


class SearchPageOut(BaseModel):
    rows: list[SearchResultOut]
    total: int
    page: int
    page_size: int
    has_more: bool
