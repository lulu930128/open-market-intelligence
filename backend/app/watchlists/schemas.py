from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class WatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class WatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None

    group_name: str
    description: str | None = None

    sort_order: int
    is_active: bool

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None

    group_name: str
    description: str | None = None

    sort_order: int
    is_active: bool

    children: list["WatchlistGroupTreeRead"] = []


class WatchlistItemCreate(BaseModel):
    group_id: int
    stock_id: str = Field(..., min_length=1, max_length=20)

    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class WatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    stock_id: str | None = Field(default=None, min_length=1, max_length=20)

    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class WatchlistItemRead(BaseModel):
    id: int

    group_id: int
    stock_id: str
    stock_name: str | None = None

    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool

    created_at: datetime
    updated_at: datetime