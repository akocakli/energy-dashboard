"""
Enerji / Altyapı Portföy Dashboard
Python 3.10+ / Streamlit

Çalıştırma:
    pip install -r requirements.txt
    streamlit run app.py
"""

import datetime as dt
from urllib.parse import quote

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# --------------------------------------------------------------------------------
# SAYFA AYARLARI
# --------------------------------------------------------------------------------
st.set_page_config(
    page_title="Enerji / Altyapı Portföy Dashboard",
    layout="wide",
)

# --------------------------------------------------------------------------------
# BASİT ŞİFRE KORUMASI
# --------------------------------------------------------------------------------


def check_password() -> bool:
    """Kullanıcı doğru şifreyi girene kadar devam etmesini engeller."""

    def password_entered():
        if st.session_state["password"] == st.secrets.get("dashboard_password", ""):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("Şifre", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("Şifre hatalı.")
    return False


if not check_password():
    st.stop()

ASSETS = ["ICLN", "RENW.L", "XLE", "UNG", "LNG"]
DEFAULT_WEIGHTS = {
    "ICLN": 0.30,
    "RENW.L": 0.20,
    "XLE": 0.25,
    "UNG": 0.15,
    "LNG": 0.10,
}

FRED_SERIES = {
    "ABD 10Y Faiz": "DGS10",
    "WTI Petrol": "DCOILWTICO",
    "Brent Petrol": "DCOILBRENTEU",
    "Henry Hub Doğal Gaz": "DHHNGSP",
}

# Stooq sembolü; dolar endeksi için farklı kaynaklarda değişebilir, gerekirse güncelle.
STOOQ_SYMBOLS = {
    "Dolar Endeksi (DXY proxy)": "usdx",
}

MIDAS_GUIDE = [
    {
        "Ticker": "FRO",
        "Temel Gösterge": "VLCC spot navlun / BDTI",
        "Anahtar Kelimeler": "tanker navlun, VLCC rate, spot freight, BDTI",
        "Nasıl Okunur": "Navlun oranları yükseliyorsa taşıma geliri artar.",
        "Tipik İlişki": "Pozitif: navlun ↑ → FRO geliri ↑",
    },
    {
        "Ticker": "TRMD",
        "Temel Gösterge": "Product tanker TCE",
        "Anahtar Kelimeler": "product tanker, TCE, navlun endeksi",
        "Nasıl Okunur": "TCE (time-charter equivalent) yükseldikçe karlılık artar.",
        "Tipik İlişki": "Pozitif: TCE ↑ → TRMD marjı ↑",
    },
    {
        "Ticker": "EPD",
        "Temel Gösterge": "Throughput / terminal doluluk",
        "Anahtar Kelimeler": "throughput, terminal utilization, doluluk oranı, midstream",
        "Nasıl Okunur": "Yüksek doluluk oranı istikrarlı nakit akışına işaret eder.",
        "Tipik İlişki": "Pozitif: doluluk ↑ → nakit akışı istikrarı ↑",
    },
    {
        "Ticker": "TUPRS",
        "Temel Gösterge": "Crack spread / rafineri marjı",
        "Anahtar Kelimeler": "crack spread, rafineri marjı, refining margin",
        "Nasıl Okunur": "Crack spread genişledikçe rafineri karlılığı artar.",
        "Tipik İlişki": "Pozitif: crack spread ↑ → TUPRS marjı ↑",
    },
    {
        "Ticker": "OIH",
        "Temel Gösterge": "Rig count / E&P CAPEX",
        "Anahtar Kelimeler": "rig count, drilling activity, E&P capex",
        "Nasıl Okunur": "Artan rig sayısı, servis şirketlerine talep artışı demektir.",
        "Tipik İlişki": "Pozitif: rig count ↑ → OIH gelirleri ↑",
    },
]

STRATEGIC_GUIDE = [
    {
        "Ticker": "ICLN",
        "Temel Gösterge": "Temiz enerji endeksi performansı",
        "İzleme Mantığı": "Küresel temiz enerji hisse sepetini takip eder.",
        "Tipik İlişki": "Faiz oranlarıyla negatif korelasyon eğilimi.",
    },
    {
        "Ticker": "RENW.L",
        "Temel Gösterge": "Avrupa temiz enerji performansı",
        "İzleme Mantığı": "Londra listeli, Avrupa ağırlıklı temiz enerji sepeti.",
        "Tipik İlişki": "Avrupa enerji politikalarıyla pozitif ilişkili.",
    },
    {
        "Ticker": "XLE",
        "Temel Gösterge": "ABD enerji sektörü (S&P Energy)",
        "İzleme Mantığı": "Büyük ABD enerji şirketlerini kapsar.",
        "Tipik İlişki": "WTI/Brent fiyatlarıyla pozitif korelasyon.",
    },
    {
        "Ticker": "UNG",
        "Temel Gösterge": "Doğal gaz fiyat takibi",
        "İzleme Mantığı": "Henry Hub vadeli işlemlerini takip eder.",
        "Tipik İlişki": "Henry Hub fiyatlarıyla doğrudan pozitif ilişki.",
    },
    {
        "Ticker": "LNG",
        "Temel Gösterge": "Cheniere Energy operasyonel performansı",
        "İzleme Mantığı": "LNG ihracat kapasitesi ve sözleşme gelirleri.",
        "Tipik İlişki": "Küresel LNG spot fiyatlarıyla pozitif ilişki.",
    },
]

# --------------------------------------------------------------------------------
# VERİ ÇEKME FONKSİYONLARI
# --------------------------------------------------------------------------------


@st.cache_data(ttl=8 * 3600, show_spinner=False)
def fetch_yahoo_prices(ticker: str, start_date: dt.date) -> pd.DataFrame:
    """Yahoo Finance chart endpoint üzerinden günlük adj-close verisi çeker."""
    period1 = int(dt.datetime.combine(start_date, dt.time.min).timestamp())
    period2 = int(dt.datetime.now().timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
    params = {
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "div,splits",
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"{ticker} için veri bulunamadı.")

    result = result[0]
    timestamps = result.get("timestamp")
    if not timestamps:
        raise ValueError(f"{ticker} için zaman serisi boş.")

    indicators = result["indicators"]
    adjclose = indicators.get("adjclose", [{}])[0].get("adjclose")
    close = indicators["quote"][0].get("close")
    prices = adjclose if adjclose else close

    df = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s").date, "close": prices})
    df = df.dropna(subset=["close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset="date").set_index("date")
    return df


@st.cache_data(ttl=8 * 3600, show_spinner=False)
def fetch_fred_series(series_id: str, start_date: dt.date) -> pd.DataFrame:
    """FRED'in API-key gerektirmeyen CSV export endpoint'inden seri çeker."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df[df["date"] >= pd.to_datetime(start_date)]
    return df.set_index("date")


@st.cache_data(ttl=8 * 3600, show_spinner=False)
def fetch_stooq_series(symbol: str, start_date: dt.date) -> pd.DataFrame:
    """Stooq CSV download endpoint'inden günlük seri çeker."""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    from io import StringIO

    df = pd.read_csv(StringIO(resp.text))
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.to_datetime(start_date)]
    return df.set_index("date")[["close"]]


# --------------------------------------------------------------------------------
# HESAPLAMA FONKSİYONLARI
# --------------------------------------------------------------------------------


def compute_returns(price_df: pd.DataFrame) -> pd.DataFrame:
    return price_df.pct_change().dropna()


def compute_portfolio_index(returns: pd.DataFrame, weights: dict) -> pd.Series:
    w = pd.Series(weights)
    w = w / w.sum()
    port_returns = (returns[w.index] * w).sum(axis=1)
    port_index = (1 + port_returns).cumprod() * 100
    return port_index


def base_100(series: pd.Series) -> pd.Series:
    return series / series.iloc[0] * 100


def annualized_volatility(returns: pd.Series) -> float:
    return returns.std() * np.sqrt(252)


def max_drawdown(index_series: pd.Series) -> float:
    peak = index_series.cummax()
    dd = index_series / peak - 1
    return dd.min()


def total_return(index_series: pd.Series) -> float:
    return index_series.iloc[-1] / index_series.iloc[0] - 1


# --------------------------------------------------------------------------------
# KARAR DESTEK PANELİ - SABİTLER
# --------------------------------------------------------------------------------

DECISION_ASSETS = ["FRO", "TRMD", "OIH", "TUPRS.IS"]
PROXY_TICKERS = {"WTI": "CL=F", "RBOB": "RB=F", "HeatingOil": "HO=F"}
TRANSACTION_COST = 0.0005  # %0.05


# --------------------------------------------------------------------------------
# KARAR DESTEK PANELİ - HESAPLAMA FONKSİYONLARI
# --------------------------------------------------------------------------------


def sma_trend_signal(price: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """SMA(fast) > SMA(slow) ise True (AL/TUT), değilse False (AZALT/SAT)."""
    sma_fast = price.rolling(fast).mean()
    sma_slow = price.rolling(slow).mean()
    return sma_fast > sma_slow


def confidence_label(ratio: float) -> str:
    """Operasyonel güven oranını Yüksek/Orta/Düşük etiketine çevirir."""
    if ratio is None or pd.isna(ratio):
        return "Veri yok"
    if ratio > 0.67:
        return "Yüksek"
    if ratio > 0.34:
        return "Orta"
    return "Düşük"


def align_bool_to_index(bool_series: pd.Series, target_index: pd.DatetimeIndex) -> pd.Series:
    """Proxy boolean serisini hedef varlığın tarih indeksine hizalar (ileri doldurma)."""
    return bool_series.reindex(target_index, method="ffill")


def run_backtest(price: pd.Series, signal: pd.Series, cost: float = TRANSACTION_COST) -> dict:
    """
    Basit long/flat backtest: sinyal True iken pozisyon 1 (varlıkta), False iken 0 (nakit).
    İşlem maliyeti, pozisyon değiştiğinde uygulanır. Bu bir in-sample backtest'tir;
    walk-forward / out-of-sample doğrulama sonraki aşamada eklenmelidir.
    """
    asset_returns = price.pct_change().fillna(0)
    position = signal.shift(1).fillna(False).astype(int)
    strat_returns = position * asset_returns
    trades = position.diff().abs().fillna(0)
    strat_returns = strat_returns - trades * cost

    equity = (1 + strat_returns).cumprod() * 100
    bh_equity = (1 + asset_returns).cumprod() * 100

    n_days = len(equity)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (252 / n_days) - 1 if n_days > 0 else np.nan
    maxdd = max_drawdown(equity)
    vol = strat_returns.std()
    sharpe = (strat_returns.mean() / vol) * np.sqrt(252) if vol and vol > 0 else np.nan

    return {
        "equity": equity,
        "bh_equity": bh_equity,
        "cagr": cagr,
        "maxdd": maxdd,
        "sharpe": sharpe,
    }


# --------------------------------------------------------------------------------
# SIDEBAR
# --------------------------------------------------------------------------------

st.sidebar.header("Ayarlar")

portfolio_value = st.sidebar.number_input(
    "Toplam portföy tutarı (USD)", min_value=0.0, value=1_000_000.0, step=10_000.0
)
energy_weight_pct = st.sidebar.selectbox("Enerji/altyapı ağırlığı", [15, 20, 25], index=1)
start_date = st.sidebar.date_input(
    "Başlangıç tarihi", value=dt.date.today() - dt.timedelta(days=5 * 365)
)

st.sidebar.caption("Sepet içi varlık ağırlıkları sabit: ICLN %30, RENW.L %20, XLE %25, UNG %15, LNG %10")

st.title("Enerji / Altyapı Portföy Dashboard")

# --------------------------------------------------------------------------------
# FİYAT VERİSİ ÇEKME
# --------------------------------------------------------------------------------

price_data = {}
failed_assets = []

with st.spinner("Fiyat verileri çekiliyor..."):
    for ticker in ASSETS:
        try:
            df = fetch_yahoo_prices(ticker, start_date)
            price_data[ticker] = df["close"]
        except Exception:
            failed_assets.append(ticker)

if len(price_data) < 3:
    st.error(
        "Veri alınamadı, API/bağlantı kontrol edilmelidir. "
        f"Başarısız olan varlıklar: {', '.join(failed_assets) if failed_assets else 'bilinmiyor'}"
    )
    st.stop()

if failed_assets:
    st.warning(f"Şu varlıklar için veri alınamadı ve hesaplamalara dahil edilmedi: {', '.join(failed_assets)}")

price_df = pd.DataFrame(price_data).dropna(how="all").ffill().dropna()
available_assets = list(price_df.columns)
weights = {k: v for k, v in DEFAULT_WEIGHTS.items() if k in available_assets}

returns = compute_returns(price_df)
portfolio_index = compute_portfolio_index(returns, weights)

# --------------------------------------------------------------------------------
# KPI KUTULARI
# --------------------------------------------------------------------------------

energy_basket_amount = portfolio_value * (energy_weight_pct / 100)
port_total_return = total_return(portfolio_index)
port_vol = annualized_volatility(portfolio_index.pct_change().dropna())
port_max_dd = max_drawdown(portfolio_index)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Enerji Sepeti Tutarı", f"${energy_basket_amount:,.0f}")
col2.metric("5Y Toplam Getiri", f"{port_total_return * 100:.1f}%")
col3.metric("Yıllık Volatilite", f"{port_vol * 100:.1f}%")
col4.metric("Maks. Düşüş", f"{port_max_dd * 100:.1f}%")

# --------------------------------------------------------------------------------
# ANA GRAFİK: BAZ 100 PERFORMANS
# --------------------------------------------------------------------------------

st.subheader("Baz 100 Performans Karşılaştırması")

fig = go.Figure()
fig.add_trace(
    go.Scatter(x=portfolio_index.index, y=portfolio_index.values, name="Portföy", line=dict(width=3))
)
for ticker in available_assets:
    series_100 = base_100(price_df[ticker])
    fig.add_trace(go.Scatter(x=series_100.index, y=series_100.values, name=ticker, line=dict(width=1.5)))

fig.update_layout(height=500, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------------
# KORELASYON + ÖZET TABLO
# --------------------------------------------------------------------------------

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Korelasyon Matrisi")
    corr = returns.corr()
    heatmap = go.Figure(
        data=go.Heatmap(
            z=corr.values,
            x=corr.columns,
            y=corr.columns,
            zmin=-1,
            zmax=1,
            colorscale="RdBu",
            text=np.round(corr.values, 2),
            texttemplate="%{text}",
        )
    )
    heatmap.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(heatmap, use_container_width=True)

with col_right:
    st.subheader("Varlık Özeti")
    summary_rows = []
    for ticker in available_assets:
        series_100 = base_100(price_df[ticker])
        summary_rows.append(
            {
                "Varlık": ticker,
                "Ağırlık": f"{weights.get(ticker, 0) * 100:.0f}%",
                "Son Fiyat": f"{price_df[ticker].iloc[-1]:.2f}",
                "5Y Getiri": f"{total_return(series_100) * 100:.1f}%",
                "Volatilite": f"{annualized_volatility(returns[ticker]) * 100:.1f}%",
                "Maks. Düşüş": f"{max_drawdown(series_100) * 100:.1f}%",
            }
        )
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------------
# GETİRİ VS VOLATİLİTE (RİSK) SCATTER
# --------------------------------------------------------------------------------

st.subheader("Getiri vs Volatilite")
st.caption("Her varlığın 5Y toplam getirisi ile yıllık volatilitesi (risk) karşılaştırması.")

scatter_points = []
for ticker in available_assets:
    series_100 = base_100(price_df[ticker])
    scatter_points.append(
        {
            "Varlık": ticker,
            "Volatilite": annualized_volatility(returns[ticker]) * 100,
            "Getiri": total_return(series_100) * 100,
        }
    )
scatter_points.append(
    {
        "Varlık": "Portföy",
        "Volatilite": port_vol * 100,
        "Getiri": port_total_return * 100,
    }
)

scatter_df = pd.DataFrame(scatter_points)

fig_scatter = go.Figure()
for _, row in scatter_df.iterrows():
    is_portfolio = row["Varlık"] == "Portföy"
    fig_scatter.add_trace(
        go.Scatter(
            x=[row["Volatilite"]],
            y=[row["Getiri"]],
            mode="markers+text",
            text=[row["Varlık"]],
            textposition="top center",
            marker=dict(
                size=16 if is_portfolio else 12,
                symbol="diamond" if is_portfolio else "circle",
                color="#FFD700" if is_portfolio else None,
            ),
            name=row["Varlık"],
            showlegend=False,
        )
    )

fig_scatter.update_layout(
    height=450,
    margin=dict(l=10, r=10, t=10, b=10),
    xaxis_title="Yıllık Volatilite (%)",
    yaxis_title="5Y Toplam Getiri (%)",
)
st.plotly_chart(fig_scatter, use_container_width=True)

# --------------------------------------------------------------------------------
# SEKMELER
# --------------------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "Makro Göstergeler",
        "Gösterge Rehberi",
        "Midas Takip Ekranı",
        "Karar Destek Paneli",
        "Ham Veri / Export",
    ]
)

with tab1:
    st.caption("FRED ve Stooq üzerinden çekilen makro seriler.")
    for label, series_id in FRED_SERIES.items():
        try:
            fred_df = fetch_fred_series(series_id, start_date)
            fig_macro = go.Figure(go.Scatter(x=fred_df.index, y=fred_df["value"], name=label))
            fig_macro.update_layout(title=label, height=250, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig_macro, use_container_width=True)
        except Exception:
            st.warning(f"{label} verisi şu anda çekilemedi (FRED bağlantı sorunu).")

    for label, symbol in STOOQ_SYMBOLS.items():
        try:
            stooq_df = fetch_stooq_series(symbol, start_date)
            fig_macro = go.Figure(go.Scatter(x=stooq_df.index, y=stooq_df["close"], name=label))
            fig_macro.update_layout(title=label, height=250, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig_macro, use_container_width=True)
        except Exception:
            st.warning(f"{label} verisi şu anda çekilemedi (Stooq bağlantı sorunu / sembol kontrol edilmeli).")

with tab2:
    st.caption("Stratejik portföydeki varlıklar için temel izleme göstergeleri.")
    st.dataframe(pd.DataFrame(STRATEGIC_GUIDE), use_container_width=True, hide_index=True)

with tab3:
    st.caption("Midas'ta arama yaparken kullanılacak anahtar kelime rehberi.")
    st.dataframe(pd.DataFrame(MIDAS_GUIDE), use_container_width=True, hide_index=True)
    st.markdown(
        """
**Kısa özet:**
- FRO / TRMD → navlun / TCE sinyali
- EPD → hacim / doluluk
- TUPRS → crack spread
- OIH → CAPEX / rig count
"""
    )

with tab4:
    st.subheader("Karar Destek Paneli — Midas Takip Listesi")
    st.info(
        "**Nasıl okunur:** \"Aksiyon\" sütunu, varlığın kendi fiyatındaki 50/200 günlük hareketli "
        "ortalama trendine dayanır (AL/TUT = kısa vadeli ortalama uzun vadelinin üzerinde). "
        "\"Operasyonel Güven\" ise WTI/RBOB/Heating Oil türevli proxy göstergelerden hesaplanan "
        "ek bir bağlam katmanıdır ve Aksiyon'u **asla değiştirmez veya bloklamaz** — sadece pozisyon "
        "büyüklüğü kararında ek bilgi sağlar. Gösterilen 5Y strateji getirisi in-sample bir "
        "backtest sonucudur; ileri aşamada walk-forward / out-of-sample doğrulama eklenmesi planlanmaktadır."
    )
    st.caption(
        "Not: Operasyonel filtreler gerçek sektör verisi değil, WTI/RBOB/Heating Oil türevli proxy "
        "göstergelerdir. Gerçek BDTI navlun endeksi, TUPRS resmi crack margin verisi ve Baker Hughes "
        "rig count entegrasyonu ikinci faz olarak planlanmaktadır."
    )

    # Proxy verilerini çek (WTI, RBOB, Heating Oil)
    proxy_prices = {}
    proxy_failed = []
    with st.spinner("Operasyonel proxy verileri çekiliyor..."):
        for label, ticker in PROXY_TICKERS.items():
            try:
                proxy_df = fetch_yahoo_prices(ticker, start_date)
                proxy_prices[label] = proxy_df["close"]
            except Exception:
                proxy_failed.append(label)

    if proxy_failed:
        st.warning(
            f"Şu proxy veriler çekilemedi, ilgili güven filtreleri 'Veri yok' gösterecek: {', '.join(proxy_failed)}"
        )

    wti = proxy_prices.get("WTI")
    rbob = proxy_prices.get("RBOB")
    heating_oil = proxy_prices.get("HeatingOil")

    op_filter_freight = None
    op_filter_oih = None
    op_filter_tuprs = None

    if wti is not None:
        wti_returns = wti.pct_change()
        vol20 = wti_returns.rolling(20).std()
        vol60_avg = vol20.rolling(60).mean()
        op_filter_freight = vol20 > vol60_avg

        wti_sma50 = wti.rolling(50).mean()
        wti_sma200 = wti.rolling(200).mean()
        op_filter_oih = wti_sma50 > wti_sma200

    if wti is not None and rbob is not None and heating_oil is not None:
        crack = (rbob * 42 + heating_oil * 42) - 2 * wti * 42
        op_filter_tuprs = crack > 0

    confidence_filter_map = {
        "FRO": op_filter_freight,
        "TRMD": op_filter_freight,
        "OIH": op_filter_oih,
        "TUPRS.IS": op_filter_tuprs,
    }

    # Karar destek varlıkları için fiyat/sinyal/backtest hesapla
    decision_rows = []
    equity_curves = {}
    backtest_export_rows = []

    with st.spinner("Midas takip listesi verileri çekiliyor..."):
        for ticker in DECISION_ASSETS:
            try:
                asset_df = fetch_yahoo_prices(ticker, start_date)
                asset_price = asset_df["close"]
            except Exception:
                decision_rows.append(
                    {
                        "Varlık": ticker,
                        "Son Fiyat": "Veri yok",
                        "Aksiyon": "Veri yok",
                        "Operasyonel Güven": "Veri yok",
                        "5Y Strateji Getirisi": "Veri yok",
                    }
                )
                continue

            signal = sma_trend_signal(asset_price)
            valid_signal = signal.dropna()
            last_signal = valid_signal.iloc[-1] if len(valid_signal) > 0 else None
            if last_signal is None:
                aksiyon = "Veri yok"
            else:
                aksiyon = "AL / TUT" if last_signal else "AZALT / SAT"

            op_filter = confidence_filter_map.get(ticker)
            if op_filter is not None:
                op_aligned = align_bool_to_index(op_filter, asset_price.index)
                ratio = op_aligned.rolling(5).mean().iloc[-1]
                confidence = confidence_label(ratio)
            else:
                confidence = "Veri yok"

            bt = run_backtest(asset_price, signal)
            equity_curves[ticker] = bt["equity"]
            strat_return_5y = bt["equity"].iloc[-1] / bt["equity"].iloc[0] - 1
            bh_return_5y = bt["bh_equity"].iloc[-1] / bt["bh_equity"].iloc[0] - 1

            decision_rows.append(
                {
                    "Varlık": ticker,
                    "Son Fiyat": f"{asset_price.iloc[-1]:.2f}",
                    "Aksiyon": aksiyon,
                    "Operasyonel Güven": confidence,
                    "5Y Strateji Getirisi": f"{strat_return_5y * 100:.1f}%",
                }
            )
            backtest_export_rows.append(
                {
                    "Varlık": ticker,
                    "Aksiyon": aksiyon,
                    "Operasyonel Güven": confidence,
                    "Strateji CAGR (%)": round(bt["cagr"] * 100, 2) if pd.notna(bt["cagr"]) else None,
                    "Strateji Maks. Düşüş (%)": round(bt["maxdd"] * 100, 2) if pd.notna(bt["maxdd"]) else None,
                    "Strateji Sharpe": round(bt["sharpe"], 2) if pd.notna(bt["sharpe"]) else None,
                    "Strateji 5Y Getiri (%)": round(strat_return_5y * 100, 2),
                    "Buy&Hold 5Y Getiri (%)": round(bh_return_5y * 100, 2),
                }
            )

    def _aksiyon_color(value: str) -> str:
        if value == "AL / TUT":
            return "#1b4332"  # yeşil ton
        if value == "AZALT / SAT":
            return "#4a1942"  # bordo/mor ton
        return "#333333"

    def _confidence_color(value: str) -> str:
        if value == "Yüksek":
            return "#1b4332"  # yeşil
        if value == "Orta":
            return "#5c4d1b"  # sarı/hardal
        if value == "Düşük":
            return "#333333"  # gri
        return "#222222"

    html_rows = ""
    for row in decision_rows:
        html_rows += (
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #444;'>{row['Varlık']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #444;'>{row['Son Fiyat']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #444;background-color:{_aksiyon_color(row['Aksiyon'])};color:white;'>{row['Aksiyon']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #444;background-color:{_confidence_color(row['Operasyonel Güven'])};color:white;'>{row['Operasyonel Güven']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #444;'>{row['5Y Strateji Getirisi']}</td>"
            "</tr>"
        )

    table_html = f"""
    <table style='width:100%;border-collapse:collapse;'>
        <thead>
            <tr style='text-align:left;border-bottom:2px solid #666;'>
                <th style='padding:8px;'>Varlık</th>
                <th style='padding:8px;'>Son Fiyat</th>
                <th style='padding:8px;'>Aksiyon</th>
                <th style='padding:8px;'>Operasyonel Güven</th>
                <th style='padding:8px;'>5Y Strateji Getirisi</th>
            </tr>
        </thead>
        <tbody>
            {html_rows}
        </tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

    if equity_curves:
        st.markdown("#### Strateji Equity Eğrisi")
        selected_for_chart = st.multiselect(
            "Grafikte gösterilecek varlıklar",
            options=list(equity_curves.keys()),
            default=list(equity_curves.keys()),
        )
        fig_equity = go.Figure()
        for ticker in selected_for_chart:
            eq = equity_curves[ticker]
            fig_equity.add_trace(go.Scatter(x=eq.index, y=eq.values, name=ticker))
        fig_equity.update_layout(
            height=400, margin=dict(l=10, r=10, t=20, b=10), hovermode="x unified", yaxis_title="Baz 100"
        )
        st.plotly_chart(fig_equity, use_container_width=True)

    if backtest_export_rows:
        backtest_df = pd.DataFrame(backtest_export_rows)
        csv_bt = backtest_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Backtest sonuçlarını CSV olarak indir",
            data=csv_bt,
            file_name="karar_destek_backtest.csv",
            mime="text/csv",
        )

with tab5:
    st.caption("Fiyat serileri ve portföy endeksi.")
    export_df = price_df.copy()
    export_df["Portföy Endeksi"] = portfolio_index
    st.dataframe(export_df.tail(30), use_container_width=True)

    csv_data = export_df.to_csv().encode("utf-8")
    st.download_button(
        "CSV olarak indir",
        data=csv_data,
        file_name="portfoy_verisi.csv",
        mime="text/csv",
    )
