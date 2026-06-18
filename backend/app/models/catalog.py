from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, ForeignKey, JSON, DateTime, Text, Numeric, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class Brand(Base, PkMixin, TimestampMixin):
    __tablename__ = "brands"
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Collection(Base, PkMixin, TimestampMixin):
    __tablename__ = "collections"
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    season: Mapped[str | None] = mapped_column(String(64))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)

    brand: Mapped["Brand"] = relationship("Brand", lazy="joined")


class Model(Base, PkMixin, TimestampMixin):
    __tablename__ = "models"
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    product_type: Mapped[str | None] = mapped_column(String(64))
    season: Mapped[str | None] = mapped_column(String(64))
    constructor_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    designer_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    details_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Standard Allowed Minutes per piece. Used by planning to estimate sewing
    # duration accurately instead of the static 45% share.
    sam_minutes: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)

    images: Mapped[list["ModelImage"]] = relationship("ModelImage", back_populates="model", cascade="all, delete-orphan")
    sizes: Mapped[list["ModelSize"]] = relationship("ModelSize", back_populates="model", cascade="all, delete-orphan")
    colors: Mapped[list["ModelColor"]] = relationship("ModelColor", back_populates="model", cascade="all, delete-orphan")
    bom: Mapped[list["ModelBOM"]] = relationship("ModelBOM", back_populates="model", cascade="all, delete-orphan")


class CollectionModel(Base, PkMixin, TimestampMixin):
    __tablename__ = "collection_models"
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)


class ModelImage(Base, PkMixin, TimestampMixin):
    __tablename__ = "model_images"
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(128))
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    image_type: Mapped[str | None] = mapped_column(String(32))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model: Mapped["Model"] = relationship("Model", back_populates="images")


class ModelSize(Base, PkMixin, TimestampMixin):
    __tablename__ = "model_sizes"
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    measurement_json: Mapped[dict | None] = mapped_column(JSON)
    model: Mapped["Model"] = relationship("Model", back_populates="sizes")


class ModelColor(Base, PkMixin, TimestampMixin):
    __tablename__ = "model_colors"
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color_name: Mapped[str] = mapped_column(String(64), nullable=False)
    color_code: Mapped[str | None] = mapped_column(String(16))
    model: Mapped["Model"] = relationship("Model", back_populates="colors")


class ModelBOM(Base, PkMixin, TimestampMixin):
    __tablename__ = "model_bom"
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    size: Mapped[str | None] = mapped_column(String(32))
    color: Mapped[str | None] = mapped_column(String(64))
    quantity_per_piece: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    waste_percent: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    model: Mapped["Model"] = relationship("Model", back_populates="bom")
