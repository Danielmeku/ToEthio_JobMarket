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

# --- CUSTOM CSS FOR HIGH-TECH DARK DASHBOARD & FILTER STYLING ---
st.markdown(
    """
    <style>
        /* Main background & font */
        .stApp {
            background-color: #0E1117;
            color: #FAFAFA;
        }
        
        /* Metric Card Containers */
        div.stMetric {
            background-color: #161B22;
            border: 1px solid #30363D;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        div.stMetric:hover {
            border-color: #00E5FF;
            transform: translateY(-2px);
        }
        div.stMetric label {
            color: #8B949E !important;
            font-weight: 500;
            font-size: 0.9rem !important;
        }
        div.stMetric [data-testid="stMetricValue"] {
            color: #00E5FF !important;
            font-weight: 700;
            font-size: 1.8rem !important;
        }

        /* Section headers */
        h2, h3 {
            color: #E6EDF3;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-weight: 600;
            letter-spacing: -0.5px;
            border-bottom: 1px solid #21262D;
            padding-bottom: 8px;
            margin-top: 24px;
        }

        /* Sidebar styling & Multiselect matching background */
        section[data-testid="stSidebar"] {
            background-color: #090C10;
            border-right: 1px solid #21262D;
        }
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
            background-color: #161B22 !important;
            border-color: #30363D !important;
            color: #FAFAFA !important;
        }
        section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] {
            background-color: #1F6FEB !important;
            color: #FFFFFF !important;
        }

        /* Action buttons */
        section[data-testid="stSidebar"] .stButton button {
            background: linear-gradient(135deg, #00E5FF 0%, #007ACC 100%);
            color: #0E1117;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            width: 100%;
            transition: opacity 0.2s ease;
        }
        section[data-testid="stSidebar"] .stButton button:hover {
            opacity: 0.85;
        }
    </style>
""",
    unsafe_allow_html=True,
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
  try:
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
      creds_dict = dict(st.secrets["gcp_service_account"])
      gc = gspread.service_account_from_dict(creds_dict)
    else:
      gc = gspread.service_account(filename="credentials.json")
  except Exception:
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
# SIDEBAR CONTROLS & FILTERS
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
st.markdown(
    """
    <div style='display: flex; align-items: center; gap: 14px; margin-bottom: 20px;'>
        <img src='https://upload.wikimedia.org/wikipedia/commons/7/71/Flag_of_Ethiopia.svg' width='45' style='border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);'/>
        <h1 style='color: #FFFFFF; font-weight: 600; margin: 0; font-size: 2.2rem;'>Ethiopian Job Market Dashboard</h1>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
  raw_df = load_data()

  if raw_df.empty:
    st.warning("No job data found in your Google Sheet.")
    st.stop()

  st.markdown(
      f"#### Total Active Listings Analyzed: **{len(raw_df)}** &nbsp;|&nbsp;"
      " Real-Time Intelligence Pipeline"
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
  st.sidebar.markdown("---")
  st.sidebar.markdown(
      """
      <div style='text-align: center; color: #8B949E; font-size: 0.85rem;'>
          Developed with ❤️ by <b>Dani mek</b><br>
          <a href='https://github.com/Danielmeku/ToEthio_JobMarket/' target='_blank' style='color: #00E5FF; text-decoration: none;'>GitHub Profile</a>
      </div>
      """,
      unsafe_allow_html=True,
  )

  # Key Metric Cards
  col1, col2, col3, col4 = st.columns(4)
  col1.metric("TOTAL JOBS", len(filtered_df))
  col2.metric(
      "REMOTE ROLES",
      len(
          filtered_df[
              filtered_df["Workplace Type"].str.contains(
                  "Remote", case=False, na=False
              )
          ]
      ),
  )
  col3.metric(
      "ON-SITE ROLES",
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
      "AVG. DEADLINE",
      f"{avg_days} Days" if avg_days != "N/A" else "N/A",
  )

  st.markdown("---")

  # --- ANALYTICS CHARTS ---
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
        color_continuous_scale=[[0, "#007ACC"], [1, "#00E5FF"]],
    )
    fig_titles.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis={"categoryorder": "total ascending"},
        showlegend=False,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_titles, use_container_width=True)

  with row1_col2:
    st.subheader("🏢 Workplace Flexibility")
    workplace_counts = (
        filtered_df["Workplace Type"].value_counts().reset_index()
    )
    # Distinct neon colors for On-site, Remote, and Hybrid to prevent overlap
    fig_donut = px.pie(
        workplace_counts,
        names="Workplace Type",
        values="count",
        hole=0.5,
        color_discrete_sequence=["#00E5FF", "#FF4081", "#FFEA00"],
    )
    fig_donut.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=20, b=10),
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
        color_continuous_scale=[[0, "#7C4DFF"], [1, "#FF4081"]],
    )
    fig_emp.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig_emp, use_container_width=True)

  with row2_col2:
    st.subheader("📍 Top Job Locations")
    loc_counts = (
        filtered_df["Location"].value_counts().head(10).reset_index()
    )
    loc_counts.columns = ["Location", "count"]
    # Multi-stop color scale to show distinct min/max contrast on legend
    fig_loc = px.bar(
        loc_counts,
        x="Location",
        y="count",
        color="count",
        color_continuous_scale=[
            [0.0, "#7C4DFF"],
            [0.5, "#00E5FF"],
            [1.0, "#00E676"],
        ],
    )
    fig_loc.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis_tickangle=-25,
        margin=dict(l=10, r=10, t=20, b=10),
    )
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
          color_continuous_scale=[[0, "#7C4DFF"], [1, "#00E5FF"]],
          text="Job Count",
      )
      fig_hist.update_traces(textposition="auto")
      fig_hist.update_layout(
          template="plotly_dark",
          paper_bgcolor="rgba(0,0,0,0)",
          plot_bgcolor="rgba(0,0,0,0)",
          showlegend=False,
          xaxis_title="",
          yaxis_title="Jobs",
          margin=dict(l=10, r=10, t=20, b=10),
      )
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
          color_discrete_sequence=["#FF4081", "#00E5FF", "#00E676", "#7C4DFF"],
          text="Days to Deadline",
      )
      fig_location_days.update_traces(
          texttemplate="%{text} Days", textposition="auto"
      )
      fig_location_days.update_layout(
          template="plotly_dark",
          paper_bgcolor="rgba(0,0,0,0)",
          plot_bgcolor="rgba(0,0,0,0)",
          showlegend=False,
          yaxis_title="Average Days",
          xaxis_tickangle=-25,
          margin=dict(l=10, r=10, t=20, b=10),
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
