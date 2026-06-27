# Chartink Multi-Screener Stock Dashboard

Deploy-ready Streamlit package for NSE stock screening, breakout probability scoring, hedge-fund style SWOT analysis, IQ-5000 research workflows, professional chart interpretation, chart replay validation, and stock technical/SWOT cards.

## Files

- `streamlit_app.py` - main Streamlit app
- `requirements.txt` - Python dependencies for Streamlit Cloud

## Run Locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy On Streamlit Cloud

1. Upload this folder to a GitHub repository.
2. In Streamlit Cloud, choose the repository.
3. Set the main file path to:

```text
streamlit_app.py
```

4. Deploy.

## Notes

- The app uses Chartink, NSE, and yfinance data sources.
- Some sections may show fallback or unavailable data if a provider blocks requests or does not return a field.
- This dashboard is for research and screening workflows, not financial advice.
