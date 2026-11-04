"""Voucher-shaped storage plus the extra masters Tally registers do not always carry."""

from sqlalchemy import Column, Integer, String, Float, Date, Boolean, DateTime, Text
from .database import Base


class Voucher(Base):
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, index=True)
    voucher_date = Column(Date, nullable=False)
    voucher_type = Column(String, nullable=False)
    party_name = Column(String, nullable=False)
    product = Column(String, nullable=True)
    category = Column(String, nullable=True)
    territory = Column(String, nullable=True)
    salesperson = Column(String, nullable=True)
    quantity = Column(Float, nullable=True)
    amount = Column(Float, nullable=False)
    returns_amount = Column(Float, default=0)
    discount_pct = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    payment_mode = Column(String, nullable=True)
    payment_type = Column(String, nullable=True)
    debit_note = Column(String, nullable=True)
    po_number = Column(String, nullable=True)
    received_quantity = Column(Float, nullable=True)
    status = Column(String, nullable=True)
    due_date = Column(Date, nullable=True)
    segment = Column(String, nullable=True)
    invoice_no = Column(String, nullable=True)
    gstin = Column(String, nullable=True)
    gst_amount = Column(Float, default=0)
    nature = Column(String, nullable=True)
    tds_deducted = Column(Float, default=0)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    godown = Column(String, nullable=True)
    tally_guid = Column(String, nullable=True)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, nullable=False)
    product = Column(String, nullable=False)
    category = Column(String, nullable=True)
    branch = Column(String, nullable=True)
    quantity = Column(Float, nullable=False)
    value = Column(Float, nullable=False)
    movement = Column(String, nullable=True)
    reorder_level = Column(Float, default=20)
    safety_stock = Column(Float, default=10)
    lead_time_days = Column(Float, default=7)
    last_movement_date = Column(Date, nullable=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    movement_date = Column(Date, nullable=False)
    voucher_type = Column(String, nullable=True)
    product = Column(String, nullable=False)
    godown = Column(String, nullable=True)
    inward_qty = Column(Float, default=0)
    outward_qty = Column(Float, default=0)
    batch = Column(String, nullable=True)


class PartyMaster(Base):
    __tablename__ = "party_masters"

    id = Column(Integer, primary_key=True, index=True)
    party_name = Column(String, unique=True, nullable=False)
    kind = Column(String, default="customer")  # customer / supplier
    territory = Column(String, nullable=True)
    salesperson = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    credit_limit = Column(Float, default=0)
    gstin = Column(String, nullable=True)


class SalesTarget(Base):
    __tablename__ = "sales_targets"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, nullable=False)
    party_name = Column(String, nullable=False)
    target_amount = Column(Float, nullable=False)


class SupplierProfile(Base):
    __tablename__ = "supplier_profiles"

    id = Column(Integer, primary_key=True, index=True)
    party_name = Column(String, unique=True, nullable=False)
    gstin = Column(String, nullable=True)
    is_msme = Column(Boolean, default=False)
    has_agreement = Column(Boolean, default=False)
    is_transporter = Column(Boolean, default=False)
    payee_type = Column(String, default="Company")


class Gstr2bInvoice(Base):
    __tablename__ = "gstr2b_invoices"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, nullable=False)
    supplier_gstin = Column(String, nullable=False)
    supplier_name = Column(String, nullable=True)
    invoice_no = Column(String, nullable=False)
    taxable_value = Column(Float, default=0)
    tax_amount = Column(Float, default=0)


class GstReturn(Base):
    __tablename__ = "gst_returns"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, unique=True, nullable=False)
    gstr1_tax = Column(Float, default=0)
    gstr3b_tax_paid = Column(Float, default=0)
    gstr3b_itc_claimed = Column(Float, default=0)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    rec_key = Column(String, unique=True, nullable=False)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    party = Column(String, nullable=True)
    product = Column(String, nullable=True)
    amount = Column(Float, default=0)
    period_label = Column(String, nullable=True)
    data_as_of = Column(String, nullable=True)
    evidence_json = Column(Text, nullable=True)
    shap_json = Column(Text, nullable=True)
    action = Column(String, nullable=True)
    status = Column(String, default="open")  # open / saved / dismissed
    feedback = Column(String, nullable=True)


class SyncEvent(Base):
    __tablename__ = "sync_events"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    source = Column(String, nullable=False)  # tally / synthetic
    company = Column(String, nullable=True)
    status = Column(String, nullable=False)  # success / error / running
    message = Column(String, nullable=True)
    sales_count = Column(Integer, default=0)
    purchase_count = Column(Integer, default=0)
    stock_count = Column(Integer, default=0)
    tally_sales_total = Column(Float, default=0)
    dashboard_sales_total = Column(Float, default=0)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
