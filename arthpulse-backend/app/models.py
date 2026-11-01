"""
1. Voucher — shaped like a Tally voucher, not a pre-aggregated report row.
   Every KPI, table and alert on the frontend is computed FROM this table
   by the API layer, the same way it will eventually be computed from
   real Tally exports. This is what keeps the door open for the
   compliance engine (269ST, GST checks) later without a schema rewrite.

2. InventoryItem — stock is a current STATE, not a transaction log, so
   it gets its own table rather than being derived from vouchers.
"""

from sqlalchemy import Column, Integer, String, Float, Date, Boolean
from .database import Base
 
 
class Voucher(Base):
    __tablename__ = "vouchers"
 
    id = Column(Integer, primary_key=True, index=True)
    voucher_date = Column(Date, nullable=False)
    voucher_type = Column(String, nullable=False)   # Sales / Purchase / Receipt / Payment
    party_name = Column(String, nullable=False)
    product = Column(String, nullable=True)
    category = Column(String, nullable=True)
    territory = Column(String, nullable=True)
    salesperson = Column(String, nullable=True)
    quantity = Column(Float, nullable=True)
    amount = Column(Float, nullable=False)
    returns_amount = Column(Float, default=0)
    payment_mode = Column(String, nullable=True)    # Cash / Bank
    payment_type = Column(String, nullable=True)    # Receivable / Payable (for Receipt/Payment vouchers)
    debit_note = Column(String, nullable=True)
    po_number = Column(String, nullable=True)
    received_quantity = Column(Float, nullable=True)
    status = Column(String, nullable=True)
    due_date = Column(Date, nullable=True)
    segment = Column(String, nullable=True)          # New / Active / Growing / Declining / Inactive
    # --- compliance fields (GST and TDS) ---
    invoice_no = Column(String, nullable=True)       # sales invoice / supplier invoice number
    gstin = Column(String, nullable=True)            # GSTIN of the customer or supplier
    gst_amount = Column(Float, default=0)            # GST on this voucher (amount is the taxable value)
    nature = Column(String, nullable=True)           # nature of payment: Contractor / Professional / Rent-Building / ...
    tds_deducted = Column(Float, default=0)          # TDS actually deducted on this payment
 
 
class InventoryItem(Base):
    __tablename__ = "inventory_items"
 
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, nullable=False)
    product = Column(String, nullable=False)
    category = Column(String, nullable=True)
    branch = Column(String, nullable=True)
    quantity = Column(Float, nullable=False)
    value = Column(Float, nullable=False)
    movement = Column(String, nullable=True)  # Fast-moving / Slow-moving / Non-moving
    reorder_level = Column(Float, default=20)
 
 
class SupplierProfile(Base):
    """
    Facts about a party that Tally registers do not carry, entered once:
    used by the MSME payment rule, the cash-payment limit and TDS rates.
    """
    __tablename__ = "supplier_profiles"
 
    id = Column(Integer, primary_key=True, index=True)
    party_name = Column(String, unique=True, nullable=False)
    gstin = Column(String, nullable=True)
    is_msme = Column(Boolean, default=False)          # micro / small enterprise supplier
    has_agreement = Column(Boolean, default=False)    # written payment agreement (45 days) or not (15 days)
    is_transporter = Column(Boolean, default=False)   # goods-transport payee (higher cash limit)
    payee_type = Column(String, default="Company")    # Individual / Company (affects some TDS rates)
 
 
class Gstr2bInvoice(Base):
    """One supplier invoice as reported in the buyer's GSTR-2B."""
    __tablename__ = "gstr2b_invoices"
 
    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, nullable=False)            # "2026-08"
    supplier_gstin = Column(String, nullable=False)
    supplier_name = Column(String, nullable=True)
    invoice_no = Column(String, nullable=False)
    taxable_value = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
 
 
class GstReturn(Base):
    """Monthly return totals: what was reported and paid on the GST portal."""
    __tablename__ = "gst_returns"
 
    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, unique=True, nullable=False)   # "2026-08"
    gstr1_tax = Column(Float, default=0)                  # output tax reported in GSTR-1
    gstr3b_tax_paid = Column(Float, default=0)            # output tax paid in GSTR-3B
    gstr3b_itc_claimed = Column(Float, default=0)         # input credit claimed in GSTR-3B
 
 
class User(Base):
    """A person who can sign in. The role decides which areas of the app they can use."""
    __tablename__ = "users"
 
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)             # key into auth.ROLES
    password_hash = Column(String, nullable=False)    # PBKDF2 hash, never the password itself
    is_active = Column(Boolean, default=True)
 