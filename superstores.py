import os
from dotenv import load_dotenv, find_dotenv

import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="USA Superstore Dashboard (MySQL)", layout="wide")

# -----------------------------
# Load .env (search current dir + parents)
# -----------------------------
ENV_FILE = find_dotenv(".env", usecwd=True)
if not ENV_FILE:
    st.error("Could not find .env. Make sure it exists in project3/.env")
    st.stop()

load_dotenv(ENV_FILE)
st.caption(f"Loaded .env from: {ENV_FILE}")

# -----------------------------
# DB Engine
# -----------------------------
@st.cache_resource  #caches the engine (connection object)
def get_engine():
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    db   = os.getenv("DB_NAME")      # should be retail
    user = os.getenv("DB_USER")
    pw   = os.getenv("DB_PASS")

    missing = [k for k, v in {
        "DB_HOST": host,
        "DB_NAME": db,
        "DB_USER": user,
        "DB_PASS": pw
    }.items() if not v]

    if missing:
        st.error(f"Missing env vars: {', '.join(missing)}. Check project3/.env")
        st.stop()

    return create_engine(f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}") #So instead of rebuilding a DB connection every rerun, Streamlit reuses the same engine object.

# -----------------------------
# Load data from MySQL
# -----------------------------
@st.cache_data(ttl=60)  #caches the DataFrame data for 60 seconds
def load_data_from_mysql() -> pd.DataFrame:
    engine = get_engine()
    df = pd.read_sql("SELECT * FROM superstore", con=engine)

    # Parse / clean for snake_case columns
    if "order_date" in df.columns:
        df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    if "ship_date" in df.columns:
        df["ship_date"] = pd.to_datetime(df["ship_date"], errors="coerce")
    if "sales" in df.columns:
        df["sales"] = pd.to_numeric(df["sales"], errors="coerce").fillna(0)

    # postal_code is double in your MySQL, convert safely to string
    if "postal_code" in df.columns:
        df["postal_code"] = (
            pd.to_numeric(df["postal_code"], errors="coerce")
            .astype("Int64")
            .astype(str)
            .replace("<NA>", "")
        )

    return df

df = load_data_from_mysql()

# -----------------------------
# Validations
# -----------------------------
st.title("📊 USA Superstore Dashboard")

if df.empty:
    st.warning("No rows returned from MySQL table `superstore`.")
    st.stop()

if "order_date" not in df.columns:
    st.error("Column `order_date` not found in MySQL table `superstore`.")
    st.write("Columns found:", df.columns.tolist())
    st.stop()

df_dates = df.dropna(subset=["order_date"])  #This prevents filter UI from breaking (because date range needs min/max).
if df_dates.empty:
    st.error("`order_date` has no valid values (all NULL/invalid).")
    st.stop()

# -----------------------------
# Sidebar Filters
# -----------------------------
st.sidebar.header("Filters")

dmin = df_dates["order_date"].min().date()
dmax = df_dates["order_date"].max().date()
date_range = st.sidebar.date_input("Order Date Range", [dmin, dmax]) #Creates a date picker that returns a list like:

regions = sorted(df["region"].dropna().unique()) if "region" in df.columns else []  #gets unique values from columns
categories = sorted(df["category"].dropna().unique()) if "category" in df.columns else [] #Default selects all values → dashboard starts unfiltered
segments = sorted(df["segment"].dropna().unique()) if "segment" in df.columns else []

region = st.sidebar.multiselect("Region", options=regions, default=regions) if regions else []
category = st.sidebar.multiselect("Category", options=categories, default=categories) if categories else []
segment = st.sidebar.multiselect("Segment", options=segments, default=segments) if segments else []

# -----------------------------
# Apply Filters
# -----------------------------
filtered_df = df[
    df["order_date"].notna()
    & (df["order_date"].dt.date.between(date_range[0], date_range[1]))
]

if "region" in df.columns and region:
    filtered_df = filtered_df[filtered_df["region"].isin(region)]
if "category" in df.columns and category:
    filtered_df = filtered_df[filtered_df["category"].isin(category)]
if "segment" in df.columns and segment:
    filtered_df = filtered_df[filtered_df["segment"].isin(segment)]

# -----------------------------
# KPIs
# -----------------------------
total_sales = float(filtered_df["sales"].sum()) if "sales" in filtered_df.columns else 0.0
total_orders = int(filtered_df["order_id"].nunique()) if "order_id" in filtered_df.columns else 0
total_customers = int(filtered_df["customer_id"].nunique()) if "customer_id" in filtered_df.columns else 0
avg_order_value = (total_sales / total_orders) if total_orders else 0.0
#sum() gives total sales
#nunique() gives number of distinct orders/customers.
#Average order value = sales / orders
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Sales", f"${total_sales:,.2f}")
k2.metric("Orders", f"{total_orders:,}")
k3.metric("Customers", f"{total_customers:,}")
k4.metric("Avg Order Value", f"${avg_order_value:,.2f}")

st.divider()

# -----------------------------
# Charts
# -----------------------------
c1, c2 = st.columns(2)

with c1:
    if "category" in filtered_df.columns and "sales" in filtered_df.columns:
        by_cat = (
            filtered_df.groupby("category", as_index=False)["sales"]
            .sum()
            .sort_values("sales", ascending=False)
        )
        st.plotly_chart(px.bar(by_cat, x="category", y="sales", title="Sales by Category"),
                        use_container_width=True)
    else:
        st.info("Columns `category` and/or `sales` not available for this chart.")

with c2:
    if "region" in filtered_df.columns and "sales" in filtered_df.columns:
        by_reg = (
            filtered_df.groupby("region", as_index=False)["sales"]
            .sum()
            .sort_values("sales", ascending=False)
        )
        st.plotly_chart(px.bar(by_reg, x="region", y="sales", title="Sales by Region"),
                        use_container_width=True)
    else:
        st.info("Columns `region` and/or `sales` not available for this chart.")

st.divider()

# -----------------------------
# Time Series
# -----------------------------
if "order_date" in filtered_df.columns and "sales" in filtered_df.columns:
    monthly_sales = (
        filtered_df.dropna(subset=["order_date"])
        .assign(month=lambda x: x["order_date"].dt.to_period("M").astype(str))
        .groupby("month", as_index=False)["sales"]
        .sum()
    )
    fig = px.line(monthly_sales, x="month", y="sales", title="Monthly Sales Trend")
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Top Products
# -----------------------------
if "product_name" in filtered_df.columns and "sales" in filtered_df.columns:
    top_products = (
        filtered_df.groupby("product_name", as_index=False)["sales"]
        .sum()
        .sort_values("sales", ascending=False)
        .head(10)
    )
    st.plotly_chart(
        px.bar(top_products, x="sales", y="product_name", orientation="h", title="Top 10 Products by Sales"),
        use_container_width=True
    )

# -----------------------------
# Data Preview & Export
# -----------------------------
st.subheader("Filtered Data Preview")
st.dataframe(filtered_df.head(100), use_container_width=True)

st.download_button(
    "Download Filtered Data",
    data=filtered_df.to_csv(index=False).encode("utf-8"),
    file_name="filtered_superstore_data.csv",
    mime="text/csv"
)

#python -m streamlit run superstores\superstores.py