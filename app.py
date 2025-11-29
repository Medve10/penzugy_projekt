# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import json
from datetime import date
from pathlib import Path

st.set_page_config(page_title="SMA PoC", page_icon="💸", layout="wide")

BASE_DIR = Path(__file__).parent
AUTH_FILE = BASE_DIR / "auth_state.json"

# ----- Persistent auth helpers -----
def load_persisted_auth():
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        # minimal sanity check
        if isinstance(data, dict) and "logged_in" in data:
            return data
    except Exception:
        return None
    return None

def save_persisted_auth(auth_dict: dict):
    try:
        AUTH_FILE.write_text(json.dumps(auth_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # fail silently for demo

def clear_persisted_auth():
    try:
        if AUTH_FILE.exists():
            AUTH_FILE.unlink()
    except Exception:
        pass

# ----- Session state -----
if "auth" not in st.session_state:
    st.session_state.auth = {
        "logged_in": False,
        "email": None,
        "org": None,
        "role": None,
    }

# try auto-login from persisted auth
persisted = load_persisted_auth()
if persisted and not st.session_state.auth.get("logged_in"):
    st.session_state.auth = persisted

AUTH = st.session_state.auth

# RBAC helper
def is_admin() -> bool:
    return AUTH.get("role") == "admin"

# Helper: loading transactions
def load_transactions(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    # if there is no invoice_no column in the CSV, add an empty one for linking
    if "invoice_no" not in df.columns:
        df["invoice_no"] = pd.NA
    return df

# Helper: loading invoices
def load_invoices(csv_path: Path) -> pd.DataFrame:
    df_i = pd.read_csv(csv_path)

    # parse dates
    df_i["issue_date"] = pd.to_datetime(df_i["issue_date"], errors="coerce")
    df_i["due_date"] = pd.to_datetime(df_i["due_date"], errors="coerce")

    # numeric fields
    df_i["net"] = pd.to_numeric(df_i["net"], errors="coerce").fillna(0.0)
    df_i["vat"] = pd.to_numeric(df_i["vat"], errors="coerce").fillna(0.0)

    # status default, if missing
    if "status" not in df_i.columns:
        df_i["status"] = "issued"

    # gross = net + vat
    df_i["gross"] = df_i["net"] + df_i["vat"]

    return df_i

# Helper: invoice status recalculation
def recompute_invoice_status(inv_row: pd.Series, tx: pd.DataFrame) -> str:
    gross = float(inv_row["gross"])
    ino = inv_row["invoice_no"]
    linked_in = tx[(tx["invoice_no"] == ino) & (tx["direction"] == "in")]["amount"].sum()
    if linked_in >= gross - 1e-6:
        return "paid"
    if pd.Timestamp(date.today()) > pd.Timestamp(inv_row["due_date"]):
        return "overdue"
    return "issued"

def auto_link_by_description(inv_no: str, tx: pd.DataFrame):
    """If transaction description contains the invoice number and is incoming, link it."""
    mask = (tx["direction"] == "in") & tx["description"].str.contains(inv_no, case=False, na=False)
    tx.loc[mask, "invoice_no"] = inv_no

# --- Sidebar ---
with st.sidebar:
    st.title("SMA PoC")
    if not AUTH["logged_in"]:
        st.subheader("Login")
        email = st.text_input("Email", value="admin@example.com")
        password = st.text_input("Password", type="password", value="admin")
        org = st.text_input("Organization", value="Demo Kft.")
        remember = st.checkbox("Remember me", value=True)
        if st.button("Login"):
            if (email, password) in [("admin@example.com", "admin"), ("user@example.com", "user")]:
                AUTH.update({
                    "logged_in": True,
                    "email": email,
                    "org": org,
                    "role": "admin" if email.startswith("admin@") else "user",
                })
                st.session_state.auth = AUTH
                if remember:
                    save_persisted_auth(AUTH)
                else:
                    clear_persisted_auth()
                st.success("Successful login.")
            else:
                st.error("Incorrect login")
    else:
        st.caption(
            f"Logged in: {AUTH['email']} | Organization: {AUTH['org']} | Role: {AUTH.get('role')}"
        )
        if st.button("Log out"):
            st.session_state.auth = {
                "logged_in": False, "email": None, "org": None, "role": None
            }
            clear_persisted_auth()
            st.experimental_rerun()

    st.markdown("---")
    page = st.radio(
        "Pages",
        ["Dashboard", "Transactions", "Invoices (Mock)", "Settings (Mock)"],
        disabled=not AUTH["logged_in"],
    )

st.title("SMA PoC – Prototype")
st.info(
    "This frontend is a Python/Streamlit prototype. For login: "
    "'admin@example.com'/'admin' or 'user@example.com'/'user'."
)

if not AUTH["logged_in"]:
    st.warning("Please log in to continue.")
    st.stop()

# --- data loading + session state ---
data_path = BASE_DIR / "assets" / "transactions.csv"
invoices_path = BASE_DIR / "assets" / "invoices.csv"
if "transactions" not in st.session_state:
    st.session_state["transactions"] = load_transactions(data_path)

if "invoices" not in st.session_state:
    try:
        st.session_state["invoices"] = load_invoices(invoices_path)
    except FileNotFoundError:
        st.error(f"invoices.csv not found at: {invoices_path}")
        st.session_state["invoices"] = pd.DataFrame(
            columns=["invoice_no","issue_date","due_date","counterparty","net","vat","gross","status"]
        )

df = st.session_state["transactions"]
df_invoices = st.session_state["invoices"]

# --- Pages ---
if page == "Dashboard":
    st.header("Control panel")
    st.caption(f"Organization: {AUTH['org']} | User: {AUTH['email']}")

    # KPIs (current month)
    today = df["date"].max().date() if not df.empty else pd.Timestamp.today().date()
    month_mask = (df["date"].dt.to_period("M") == pd.Timestamp(today).to_period("M"))
    m = df[month_mask]
    income = m.loc[m["direction"] == "in", "amount"].sum()
    expense = -m.loc[m["direction"] == "out", "amount"].sum()
    cashflow = income - expense

    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly income", f"{income:,.0f} HUF")
    c2.metric("Monthly expenses", f"{expense:,.0f} HUF")
    c3.metric("Monthly cash-flow", f"{cashflow:,.0f} HUF")

    st.subheader("Monthly trends")
    monthly = df.copy()
    monthly["month"] = monthly["date"].dt.to_period("M").dt.to_timestamp()

    # income
    monthly_in = (
        monthly.loc[monthly["direction"] == "in"]
        .groupby("month")["amount"].sum()
        .reset_index(name="income")
    )

    # expenses
    monthly_out = (
        monthly.loc[monthly["direction"] == "out"]
        .groupby("month")["amount"].sum()
        .mul(-1)  # only negate the amount Series
        .reset_index(name="expense")
    )

    trend = (
        pd.merge(monthly_in, monthly_out, on="month", how="outer")
        .fillna(0.0)
    )
    trend["cashflow"] = trend["income"] - trend["expense"]

    st.line_chart(trend.set_index("month")[["income", "expense", "cashflow"]])

    st.subheader("Accounts receivable")
    open_invoices = df_invoices[df_invoices["status"] != "paid"].copy()
    if open_invoices.empty:
        st.write("No open invoices.")
    else:
        st.dataframe(
            open_invoices[["invoice_no", "issue_date", "due_date", "counterparty", "gross", "status"]]
            .sort_values("due_date"),
            use_container_width=True,
            hide_index=True,
        )

elif page == "Transactions":
    st.header("Transactions")
    colf1, colf2, colf3, colf4 = st.columns([1,1,1,2])
    with colf1:
        direction = st.selectbox("Direction", ["all","in","out"], index=0)
    with colf2:
        account = st.selectbox("Account", ["all"] + sorted(df["account"].unique().tolist()))
    with colf3:
        category = st.selectbox("Category", ["all"] + sorted(df["category"].dropna().unique().tolist()))
    with colf4:
        search = st.text_input("Search in description")

    mask = pd.Series(True, index=df.index)
    if direction != "all":
        mask &= (df["direction"] == direction)
    if account != "all":
        mask &= (df["account"] == account)
    if category != "all":
        mask &= (df["category"] == category)
    if search:
        mask &= df["description"].str.contains(search, case=False, na=False)

    filtered = df[mask].sort_values("date", ascending=False)
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    st.markdown("### Quick Categorization (demo)")

    if is_admin():
        row_id = st.number_input("Transaction ID", min_value=1, step=1)
        new_cat = st.selectbox(
            "New Category",
            ["Sales","COGS","Rent","Travel","Software","Meals","Logistics"]
        )
        new_inv = st.text_input("Link to invoice (optional, e.g. INV-1002)", value="")
        if st.button("Save (demo)"):
            idx = df.index[df["id"] == int(row_id)]
            if len(idx) == 0:
                st.error("No such transaction ID.")
            else:
                df.loc[idx, "category"] = new_cat
                inv_no = new_inv.strip().upper() or pd.NA
                df.loc[idx, "invoice_no"] = inv_no
                st.success(
                    f"Set: id={int(row_id)} → category={new_cat}, invoice_no={inv_no} "
                    "(demo only, not persisted)"
                )
    else:
        st.info("You can view and filter transactions. Editing and linking is restricted to admin users.")

elif page == "Invoices (Mock)":
    st.header("Invoices")

    # status filter
    colf1, colf2 = st.columns([1,3])
    with colf1:
        status_filter = st.selectbox("Status", ["all","issued","overdue","paid"], index=0)

    inv = df_invoices.copy()
    if status_filter != "all":
        inv = inv[inv["status"] == status_filter]

    # paid / due amount calculation based on linked transactions
    paid_sum = []
    for _, r in inv.iterrows():
        s = df[(df["invoice_no"] == r["invoice_no"]) & (df["direction"] == "in")]["amount"].sum()
        paid_sum.append(float(s))

    inv["paid_amount"] = paid_sum
    inv["due_amount"] = (inv["gross"] - inv["paid_amount"]).clip(lower=0.0)

    st.dataframe(
        inv[["invoice_no","issue_date","due_date","counterparty","gross","paid_amount","due_amount","status"]]
        .sort_values("due_date"),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("Invoice details and actions")

    selected_inv = st.selectbox("Select invoice", ["-- select --"] + inv["invoice_no"].tolist())
    if selected_inv and selected_inv != "-- select --":
        row = df_invoices.loc[df_invoices["invoice_no"] == selected_inv].iloc[0]
        st.write("Invoice:", selected_inv)
        st.write("Counterparty:", str(row["counterparty"]))
        st.write("Issue date:", pd.Timestamp(row["issue_date"]).date())
        st.write("Due date:", pd.Timestamp(row["due_date"]).date())
        st.write("Gross amount:", f"{float(row['gross']):,.0f} HUF")
        st.write("Current status:", row["status"])

        # linked transactions
        linked = df[df["invoice_no"] == selected_inv]
        st.markdown("**Linked transactions**")
        st.dataframe(
            linked[["id","date","description","amount","direction","category","invoice_no"]]
            .sort_values("date"),
            use_container_width=True,
            hide_index=True,
        )

        if is_admin():
            # auto-link by description
            if st.button("Auto-link by description"):
                auto_link_by_description(selected_inv, df)
                st.success("Auto-link done (description contains invoice number).")

            # manual linking
            st.markdown("**Manual linking**")
            candidates = df[(df["direction"] == "in") & (df["invoice_no"].isna())]
            options = candidates["id"].astype(int).tolist()
            chosen = st.multiselect("Pick incoming transactions to link", options)
            if st.button("Link selected"):
                df.loc[df["id"].isin(chosen), "invoice_no"] = selected_inv
                st.success(f"Linked {len(chosen)} transaction(s) to {selected_inv}.")

            # unlink
            if not linked.empty:
                unlink_ids = st.multiselect("Unlink transactions", linked["id"].astype(int).tolist())
                if st.button("Unlink selected"):
                    df.loc[df["id"].isin(unlink_ids), "invoice_no"] = pd.NA
                    st.success(f"Unlinked {len(unlink_ids)} transaction(s).")

            st.markdown("---")
            st.markdown("**Status actions**")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("Mark as issued"):
                    df_invoices.loc[df_invoices["invoice_no"] == selected_inv, "status"] = "issued"
                    st.success("Status set to issued.")
            with col2:
                if st.button("Mark as paid"):
                    df_invoices.loc[df_invoices["invoice_no"] == selected_inv, "status"] = "paid"
                    st.success("Status set to paid.")
            with col3:
                if st.button("Mark as overdue"):
                    df_invoices.loc[df_invoices["invoice_no"] == selected_inv, "status"] = "overdue"
                    st.success("Status set to overdue.")
            with col4:
                if st.button("Recompute status"):
                    recomputed = recompute_invoice_status(row, df)
                    df_invoices.loc[df_invoices["invoice_no"] == selected_inv, "status"] = recomputed
                    st.success(f"Recomputed status: {recomputed}")
        else:
            st.info(
                "You can view invoices and linked transactions. "
                "Only admin users can modify links or change invoice status."
            )

elif page == "Settings (Mock)":
    st.header("Settings")
    st.write("Organization:", AUTH["org"])
    st.write("Role:", AUTH["role"])
    st.caption("RBAC, audit log, exports – planned for later iterations.")
