from datetime import datetime, timedelta
import json
import re
from bs4 import BeautifulSoup
import gspread
import requests
import streamlit as st

CHANNEL_NAME = "freelance_ethio"
BASE_URL = f"https://t.me/s/{CHANNEL_NAME}"

# Initialize Google Sheets via Streamlit Secrets (for Cloud) or credentials.json (for Local)
try:
  if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
    creds_dict = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(creds_dict)
  else:
    gc = gspread.service_account(filename="credentials.json")
except Exception:
  gc = gspread.service_account(filename="credentials.json")

spreadsheet = gc.open("Job Market Database")
sheet = spreadsheet.sheet1

HEADERS = [
    "Job Title",
    "Workplace Type",
    "Employment Type",
    "Location",
    "Salary",
    "Deadline",
    "Date Fetched",
]


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


def run_paginated_scraper(progress_bar=None, status_text=None):
  if status_text:
    status_text.text("Clearing Google Sheet...")
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
    if status_text:
      status_text.text(f"Fetching page {page+1} from Telegram...")
    if progress_bar:
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

  if progress_bar:
    progress_bar.progress(100)
  if status_text:
    status_text.text("Scraping complete!")
  return processed_count


if __name__ == "__main__":
  run_paginated_scraper()
