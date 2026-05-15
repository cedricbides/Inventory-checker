# &#x09;Future Development

## Google Chat Notification

Send a summary to a Google Chat space after every run using a webhook

Webhook URL stored in credentials.py (already gitignored)

Message should include: brand, channel, matched count, mismatched count, report filename

## Desktop App (.exe)

Package with PyInstaller so the team can run it without Python installed

Double-click to open, no terminal needed

## Web App

Rewrite GUI in Flask so anyone on the network can use it in a browser

Upload files via browser, download report as Excel

## Auto-run / Scheduling

Schedule daily runs via Windows Task Scheduler

No need to manually run it every day

## Alerts

## Run Summary

Print a quick summary in terminal after each run: matched vs mismatched per brand

No need to open Excel just to check if everything is fine

## Mismatch History

Log results to a CSV or SQLite database after every run

Useful for tracking which SKUs keep mismatching over time

## More Channels

Shopify

TikTok Shop

Lazada live API (currently reading file exports)

## Auto-upload Results

Push the Excel report to Google Drive or SharePoint after generation

