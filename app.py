from datetime import datetime
import re
from dateutil import parser
import gspread
import pandas as pd
import plotly.express as px
import streamlit as st
from web_scraper import run_paginated_scraper

# Page configuration
st.set_page_config(
    page_title="Ethiopian Job Market Analytics", page_icon="🇪🇹", layout="wide"
)


# Robust date parsing helper for deadline calculations
def parse_flexible_date(date_str):
  if not date_str or date_str == "N/A":
    return None
  try:
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", str(date_str)).strip()
    dt = parser.parse(cleaned, default=datetime(2026, 1, 1))
    return dt
  except Exception:
    return None


# Load Data Function
@st.cache_data(ttl=60)
def load_data():
  gc = gspread.service_account(filename="credentials.json")
  sheet = gc.open("Job Market Database").sheet1
  data = sheet.get_all_records()
  df = pd.DataFrame(data)

  if not df.empty:
    df.replace("", "N/A", inplace=True)
    df["Fetched Parsed"] = df["Date Fetched"].apply(parse_flexible_date)
    df["Deadline Parsed"] = df["Deadline"].apply(parse_flexible_date)

    def calc_days(row):
      if pd.notnull(row["Deadline Parsed"]) and pd.notnull(
          row["Fetched Parsed"]
      ):
        delta = (row["Deadline Parsed"] - row["Fetched Parsed"]).days
        return delta if delta >= 0 else None
      return None

    df["Days to Deadline"] = df.apply(calc_days, axis=1)

  return df


# -------------------------------------------------------------
# SIDEBAR CONTROLS & FETCH BUTTON
# -------------------------------------------------------------
st.sidebar.title("🛠️ Actions & Filters")

if st.sidebar.button("🚀 Fetch Latest Telegram Jobs"):
  progress_bar = st.sidebar.progress(0)
  status_text = st.sidebar.empty()
  with st.spinner("Scraping public Telegram channel..."):
    new_jobs = run_paginated_scraper(progress_bar, status_text)
  st.sidebar.success(f"Done! Added {new_jobs} clean jobs to Google Sheets.")
  st.cache_data.clear()
  st.rerun()

if st.sidebar.button("🔄 Refresh Data"):
  st.cache_data.clear()
  st.rerun()

st.sidebar.markdown("---")

# Main Page Header
st.title("🇪🇹 Ethiopian Job Market Dashboard")

try:
  raw_df = load_data()

  if raw_df.empty:
    st.warning("No job data found in your Google Sheet.")
    st.stop()

  st.markdown(f"#### Total Active Listings Analyzed: **{len(raw_df)}**")
  st.markdown(
      "Real-time analytics pipeline parsing job listings from Telegram web"
      " preview."
  )
  st.markdown("---")

  # Sidebar Filters
  workplace_options = list(raw_df["Workplace Type"].unique())
  selected_workplace = st.sidebar.multiselect(
      "Workplace Type", workplace_options, default=workplace_options
  )

  employment_options = list(raw_df["Employment Type"].unique())
  selected_employment = st.sidebar.multiselect(
      "Employment Type", employment_options, default=employment_options
  )

  location_options = list(raw_df["Location"].unique())
  selected_location = st.sidebar.multiselect(
      "Location", location_options, default=location_options
  )

  # Apply Filters
  filtered_df = raw_df[
      (raw_df["Workplace Type"].isin(selected_workplace))
      & (raw_df["Employment Type"].isin(selected_employment))
      & (raw_df["Location"].isin(selected_location))
  ]

  # Key Metric Cards
  col1, col2, col3, col4 = st.columns(4)
  col1.metric("Total Jobs Listed", len(filtered_df))
  col2.metric(
      "Remote Roles",
      len(
          filtered_df[
              filtered_df["Workplace Type"].str.contains(
                  "Remote", case=False, na=False
              )
          ]
      ),
  )
  col3.metric(
      "On-site Roles",
      len(
          filtered_df[
              filtered_df["Workplace Type"].str.contains(
                  "On-site", case=False, na=False
              )
          ]
      ),
  )

  valid_deadlines = filtered_df["Days to Deadline"].dropna()
  avg_days = (
      round(valid_deadlines.mean(), 1) if not valid_deadlines.empty else "N/A"
  )
  col4.metric(
      "Avg. Days to Deadline",
      f"{avg_days} Days" if avg_days != "N/A" else "N/A",
  )

  st.markdown("---")

  # Analytics Charts
  row1_col1, row1_col2 = st.columns(2)

  with row1_col1:
    st.subheader("📌 Top 10 Common Job Titles")
    top_titles = (
        filtered_df["Job Title"]
        .value_counts()
        .head(10)
        .reset_index(name="Count")
    )
    fig_titles = px.bar(
        top_titles,
        x="Count",
        y="Job Title",
        orientation="h",
        color="Count",
        color_continuous_scale="Blues",
    )
    fig_titles.update_layout(
        yaxis={"categoryorder": "total ascending"}, showlegend=False
    )
    st.plotly_chart(fig_titles, use_container_width=True)

  with row1_col2:
    st.subheader("🏢 Workplace Flexibility")
    workplace_counts = (
        filtered_df["Workplace Type"].value_counts().reset_index()
    )
    fig_donut = px.pie(
        workplace_counts,
        names="Workplace Type",
        values="count",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Pastel,
    )
    st.plotly_chart(fig_donut, use_container_width=True)

  row2_col1, row2_col2 = st.columns(2)

  with row2_col1:
    st.subheader("💼 Employment Type Breakdown")
    emp_counts = filtered_df["Employment Type"].value_counts().reset_index()
    fig_emp = px.bar(
        emp_counts,
        x="Employment Type",
        y="count",
        color="count",
        color_continuous_scale="Viridis",
    )
    fig_emp.update_layout(showlegend=False)
    st.plotly_chart(fig_emp, use_container_width=True)

  with row2_col2:
    st.subheader("📍 Top Job Locations")
    loc_counts = (
        filtered_df["Location"].value_counts().head(10).reset_index()
    )
    loc_counts.columns = ["Location", "count"]
    fig_loc = px.bar(
        loc_counts,
        x="Location",
        y="count",
        color="count",
        color_continuous_scale="Teal",
    )
    fig_loc.update_layout(showlegend=False, xaxis_tickangle=-25)
    st.plotly_chart(fig_loc, use_container_width=True)

  # Application Window Insights
  st.subheader("⏳ Application Window Insights (Days to Deadline)")
  deadline_df = filtered_df.dropna(subset=["Days to Deadline"]).copy()

  if not deadline_df.empty:
    col_insight1, col_insight2 = st.columns(2)

    with col_insight1:
      st.markdown("##### Distribution of Deadline Durations")

      def categorize_window(days):
        if days <= 3:
          return "Urgent (1-3 Days)"
        elif days <= 7:
          return "1 Week (4-7 Days)"
        elif days <= 14:
          return "2 Weeks (8-14 Days)"
        elif days <= 30:
          return "1 Month (15-30 Days)"
        else:
          return "Extended (>30 Days)"

      deadline_df["Window Category"] = deadline_df["Days to Deadline"].apply(
          categorize_window
      )
      category_order = [
          "Urgent (1-3 Days)",
          "1 Week (4-7 Days)",
          "2 Weeks (8-14 Days)",
          "1 Month (15-30 Days)",
          "Extended (>30 Days)",
      ]
      cat_counts = (
          deadline_df["Window Category"]
          .value_counts()
          .reindex(category_order)
          .dropna()
          .reset_index()
      )
      cat_counts.columns = ["Duration Bucket", "Job Count"]

      fig_hist = px.bar(
          cat_counts,
          x="Duration Bucket",
          y="Job Count",
          color="Job Count",
          color_continuous_scale="Purples",
          text="Job Count",
      )
      fig_hist.update_traces(textposition="auto")
      fig_hist.update_layout(showlegend=False, xaxis_title="", yaxis_title="Jobs")
      st.plotly_chart(fig_hist, use_container_width=True)

    with col_insight2:
      st.markdown("##### Avg. Days to Deadline by Location")
      avg_by_location = (
          deadline_df.groupby("Location")["Days to Deadline"]
          .mean()
          .round(1)
          .reset_index()
          .sort_values(by="Days to Deadline", ascending=False)
          .head(8)
      )

      fig_location_days = px.bar(
          avg_by_location,
          x="Location",
          y="Days to Deadline",
          color="Location",
          color_discrete_sequence=px.colors.qualitative.Pastel,
          text="Days to Deadline",
      )
      fig_location_days.update_traces(
          texttemplate="%{text} Days", textposition="auto"
      )
      fig_location_days.update_layout(
          showlegend=False, yaxis_title="Average Days", xaxis_tickangle=-25
      )
      st.plotly_chart(fig_location_days, use_container_width=True)
  else:
    st.info("No valid deadline duration data available for current selection.")

  # Data Table
  st.subheader("📋 Filtered Job Listings")
  st.dataframe(
      filtered_df[
          [
              "Job Title",
              "Workplace Type",
              "Employment Type",
              "Location",
              "Salary",
              "Deadline",
              "Date Fetched",
          ]
      ],
      use_container_width=True,
  )

except Exception as e:
  st.error(f"Error loading dashboard: {e}")