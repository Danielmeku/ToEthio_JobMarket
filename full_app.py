from datetime import datetime, timedelta
import re
import os
from dotenv import load_dotenv
from dateutil import parser
import gspread
import pandas as pd
import plotly.express as px
import requests
from bs4 import BeautifulSoup
import streamlit as st

# Page configuration
st.set_page_config(
    page_title="Ethiopian Job Market Analytics", page_icon="🇪🇹", layout="wide"
)

CHANNEL_NAME = "freelance_ethio"
BASE_URL = f"https://t.me/s/{CHANNEL_NAME}"

HEADERS = [
    "Job Title",
    "Workplace Type",
    "Employment Type",
    "Location",
    "Salary",
    "Deadline",
    "Date Fetched",
]


# Helper function to clean text
def clean_text(text):
  if not text:
    return "N/A"
  cleaned = text.replace("**", "").replace("*", "").strip()
  return cleaned if cleaned else "N/A"


def parse_telegram_web_post(full_text):
  clean_full_text = re.sub(r"\s+", " ", full_text).strip()

  def extract_field(pattern, text):
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
      return "N/A"
    val = match.group(1)
    for next_label in [
        "Job Type",
        "Type",
        "Work Location",
        "Location",
        "Place",
        "Salary",
        "Compensation",
        "Deadline",
        "Applicants",
        "Description",
        "Req",
    ]:
      if next_label.lower() in val.lower():
        val = re.split(rf"\b{next_label}\b", val, flags=re.IGNORECASE)[0]
    return clean_text(val)

  title = extract_field(
      r"(?:Job Title|Title)[:\s]*(.*?)(?=\s*(?:Job Type|Work Location|Location|Salary|Deadline|Description|$))",
      clean_full_text,
  )
  if title == "N/A" or len(title) > 60:
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    title = lines[0][:57] + "..." if lines else "N/A"

  raw_job_type = extract_field(
      r"(?:Job Type|Type)[:\s]*(.*?)(?=\s*(?:Work Location|Location|Salary|Deadline|Description|$))",
      clean_full_text,
  )
  location = extract_field(
      r"(?:Work Location|Location|Place)[:\s]*(.*?)(?=\s*(?:Salary|Deadline|Job Type|Description|$))",
      clean_full_text,
  )
  salary = extract_field(
      r"(?:Salary/Compensation|Salary|Compensation|Pay)[:\s]*(.*?)(?=\s*(?:Deadline|Location|Job Type|Description|$))",
      clean_full_text,
  )
  deadline = extract_field(
      r"(?:Deadline|Ends)[:\s]*(.*?)(?=\s*(?:Description|Req|Salary|Location|Job Type|$))",
      clean_full_text,
  )

  fetched_date = datetime.now().strftime("%Y-%m-%d")

  if " - " in raw_job_type and not raw_job_type.startswith("On-site -"):
    parts = raw_job_type.split(" - ", 1)
    workplace_type = parts[0].strip()
    employment_type = parts[1].strip()
  elif raw_job_type.startswith("On-site"):
    workplace_type = "On-site"
    employment_type = raw_job_type.replace("On-site", "").strip(" -").strip()
  else:
    workplace_type = raw_job_type
    employment_type = "N/A"

  return [
      title,
      workplace_type,
      employment_type,
      location,
      salary,
      deadline,
      fetched_date,
  ]


# Web Scraper function with progress tracking for Streamlit
def run_paginated_scraper(progress_bar, status_text):
  gc = gspread.service_account(filename="credentials.json")
  spreadsheet = gc.open("Job Market Database")
  sheet = spreadsheet.sheet1

  sheet.clear()
  sheet.append_row(HEADERS)

  http_headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  one_week_ago = datetime.now() - timedelta(days=7)
  rows_to_append = []
  processed_count = 0

  current_url = BASE_URL
  max_pages = 30

  for page in range(max_pages):
    status_text.text(f"Fetching page {page+1} from Telegram...")
    progress_bar.progress(int(((page + 1) / max_pages) * 100))

    response = requests.get(current_url, headers=http_headers)
    if response.status_code != 200:
      break

    soup = BeautifulSoup(response.text, "html.parser")
    message_divs = soup.find_all("div", class_="tgme_widget_message")
    if not message_divs:
      break

    oldest_message_id = None
    reached_time_limit = False

    for msg in message_divs:
      try:
        data_post = msg.get("data-post")
        if not data_post:
          link_tag = msg.find(
              "a", class_="tgme_widget_message_date", href=True
          )
          if link_tag and "/" in link_tag["href"]:
            data_post = link_tag["href"].split("/")[-2] + "/" + link_tag["href"].split("/")[-1]

        if data_post:
          try:
            msg_id = int(data_post.split("/")[-1])
            if oldest_message_id is None or msg_id < oldest_message_id:
              oldest_message_id = msg_id
          except ValueError:
            pass

        text_element = msg.find("div", class_="tgme_widget_message_text")
        if not text_element:
          continue

        full_text = text_element.get_text(separator="\n")
        if not re.search(
            r"(?:Job Title|Title|Job Type|Location)", full_text, re.IGNORECASE
        ):
          continue

        date_element = msg.find("time", class_="tgme_widget_message_date")
        if date_element and date_element.has_attr("datetime"):
          iso_str = date_element["datetime"]
          dt = datetime.fromisoformat(
              iso_str.replace("Z", "+00:00")
          ).replace(tzinfo=None)
          if dt < one_week_ago:
            reached_time_limit = True
            continue

        row = parse_telegram_web_post(full_text)
        if row[0] != "N/A":
          rows_to_append.append(row)
          processed_count += 1
      except Exception:
        pass

    if reached_time_limit or not oldest_message_id:
      break
    current_url = f"{BASE_URL}?before={oldest_message_id}"

  if rows_to_append:
    sheet.append_rows(rows_to_append)

  progress_bar.progress(100)
  status_text.text("Scraping complete!")
  return processed_count


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

    # Use Date Fetched for timeline analysis since Post Date column was removed
    df["Fetched Parsed"] = df["Date Fetched"].apply(parse_flexible_date)
    df["Day of Week"] = df["Fetched Parsed"].dt.day_name()
    df["Day with Date"] = (
        df["Day of Week"]
        + " ("
        + df["Fetched Parsed"].dt.strftime("%b %d")
        + ")"
    )

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

  valid_dates = raw_df["Fetched Parsed"].dropna().sort_values()
  start_date_str = (
      valid_dates.iloc[0].strftime("%B %d, %Y")
      if not valid_dates.empty
      else "N/A"
  )
  last_date_str = (
      valid_dates.iloc[-1].strftime("%B %d, %Y")
      if not valid_dates.empty
      else "N/A"
  )

  st.markdown(
      f"#### 📅 Data Coverage: **{last_date_str}**"
  )
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