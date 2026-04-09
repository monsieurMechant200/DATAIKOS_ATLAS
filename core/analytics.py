"""
core/analytics.py
~~~~~~~~~~~~~~~~~
Analyse de séries temporelles (ARIMA / SARIMAX).
"""
from __future__ import annotations
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.stattools   import adfuller, kpss, acf, pacf
    from statsmodels.tsa.seasonal    import seasonal_decompose
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    from statsmodels.stats.diagnostic import acorr_ljungbox
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

from config   import AtlasConfig
from database import AtlasDatabase

class AtlasTimeSeriesAnalyzer:
    def __init__(self, data: pd.Series, freq: str = 'D'):
        self.data = data.dropna()
        self.freq = freq
        self.model_fit = None
        self.forecast_result = None
        self.decomposition = None
        self.adf_result = None
        self.kpss_result = None
        self.best_aic = np.inf
        self.best_order = None
        self.best_seasonal_order = None

    def test_stationarity(self):
        if len(self.data) < 10:
            return {
                'adf_statistic': np.nan,
                'adf_pvalue': np.nan,
                'kpss_statistic': np.nan,
                'kpss_pvalue': np.nan,
                'is_stationary': False
            }
        self.adf_result = adfuller(self.data, autolag='AIC')
        self.kpss_result = kpss(self.data, regression='c', nlags='auto')
        return {
            'adf_statistic': self.adf_result[0],
            'adf_pvalue': self.adf_result[1],
            'kpss_statistic': self.kpss_result[0],
            'kpss_pvalue': self.kpss_result[1],
            'is_stationary': (self.adf_result[1] < 0.05) and (self.kpss_result[1] > 0.05)
        }

    def detect_seasonality(self):
        try:
            period = AtlasConfig.settings.get('seasonality_period', 12)
            self.decomposition = seasonal_decompose(self.data, model='additive', period=period)
            return self.decomposition.seasonal
        except:
            return None

    def auto_sarima_manual(self, max_p=3, max_d=1, max_q=3, max_P=1, max_D=1, max_Q=1, m=None):
        if m is None:
            m = AtlasConfig.settings.get('seasonality_period', 12)
        best_aic = np.inf
        best_order = None
        best_seasonal_order = None
        best_model = None

        for p in range(max_p+1):
            for d in range(max_d+1):
                for q in range(max_q+1):
                    try:
                        model = ARIMA(self.data, order=(p,d,q))
                        results = model.fit(method_kwargs={'maxiter':200})
                        if results.aic < best_aic:
                            best_aic = results.aic
                            best_order = (p,d,q)
                            best_seasonal_order = None
                            best_model = results
                    except:
                        pass
                    for P in range(max_P+1):
                        for D in range(max_D+1):
                            for Q in range(max_Q+1):
                                try:
                                    model = SARIMAX(self.data, order=(p,d,q), seasonal_order=(P,D,Q,m),
                                                    enforce_stationarity=False, enforce_invertibility=False)
                                    results = model.fit(disp=False, method='lbfgs', maxiter=200)
                                    if results.aic < best_aic:
                                        best_aic = results.aic
                                        best_order = (p,d,q)
                                        best_seasonal_order = (P,D,Q,m)
                                        best_model = results
                                except:
                                    continue
        if best_model is not None:
            self.model_fit = best_model
            self.best_aic = best_aic
            self.best_order = best_order
            self.best_seasonal_order = best_seasonal_order
        return best_order, best_seasonal_order, best_aic

    def fit_sarimax(self, order, seasonal_order=None):
        model = SARIMAX(self.data, order=order, seasonal_order=seasonal_order,
                        enforce_stationarity=False, enforce_invertibility=False)
        self.model_fit = model.fit(disp=False)
        return self.model_fit

    def forecast(self, steps: int = 30, alpha: float = 0.05):
        if self.model_fit is None:
            raise ValueError("Aucun modèle n'a été ajusté")
        forecast_result = self.model_fit.get_forecast(steps=steps)
        forecast = forecast_result.predicted_mean
        conf_int = forecast_result.conf_int(alpha=alpha)
        self.forecast_result = {
            'forecast': forecast,
            'conf_int': conf_int
        }
        return self.forecast_result

    def plot_components(self, figure, plot_type='all'):
        figure.clear()
        if plot_type == 'acf_pacf':
            ax1 = figure.add_subplot(211)
            ax2 = figure.add_subplot(212)
            lags = min(40, len(self.data)//2-1)
            acf_vals = acf(self.data, nlags=lags)
            pacf_vals = pacf(self.data, nlags=lags)
            ax1.stem(range(len(acf_vals)), acf_vals, linefmt=AtlasConfig.COLORS['primary'], markerfmt='o', basefmt='gray')
            ax1.axhline(y=0, linestyle='--', color='gray')
            ax1.axhline(y=-1.96/np.sqrt(len(self.data)), linestyle='--', color=AtlasConfig.COLORS['danger'])
            ax1.axhline(y=1.96/np.sqrt(len(self.data)), linestyle='--', color=AtlasConfig.COLORS['danger'])
            ax1.set_title('ACF')
            ax2.stem(range(len(pacf_vals)), pacf_vals, linefmt=AtlasConfig.COLORS['primary'], markerfmt='o', basefmt='gray')
            ax2.axhline(y=0, linestyle='--', color='gray')
            ax2.axhline(y=-1.96/np.sqrt(len(self.data)), linestyle='--', color=AtlasConfig.COLORS['danger'])
            ax2.axhline(y=1.96/np.sqrt(len(self.data)), linestyle='--', color=AtlasConfig.COLORS['danger'])
            ax2.set_title('PACF')
        elif plot_type == 'residuals' and self.model_fit is not None:
            ax = figure.add_subplot(111)
            residuals = self.model_fit.resid
            ax.plot(residuals, color=AtlasConfig.COLORS['secondary'])
            ax.axhline(y=0, linestyle='--', color=AtlasConfig.COLORS['danger'])
            ax.set_title('Résidus')
            lb = acorr_ljungbox(residuals, lags=[10], return_df=True)
            ax.text(0.5, 0.9, f"Ljung-Box p-value: {lb.loc[10, 'lb_pvalue']:.3f}", transform=ax.transAxes)
        elif plot_type == 'decomposition' and self.decomposition is not None:
            ax1 = figure.add_subplot(411)
            ax2 = figure.add_subplot(412)
            ax3 = figure.add_subplot(413)
            ax4 = figure.add_subplot(414)
            self.decomposition.observed.plot(ax=ax1, color=AtlasConfig.COLORS['secondary'])
            ax1.set_title('Observé')
            self.decomposition.trend.plot(ax=ax2, color=AtlasConfig.COLORS['primary'])
            ax2.set_title('Tendance')
            self.decomposition.seasonal.plot(ax=ax3, color=AtlasConfig.COLORS['warning'])
            ax3.set_title('Saisonnier')
            self.decomposition.resid.plot(ax=ax4, color='gray')
            ax4.set_title('Résidu')
        elif plot_type == 'forecast':
            ax = figure.add_subplot(111)
            x_vals = np.array(self.data.index)
            y_vals = self.data.values
            ax.plot(x_vals, y_vals, label='Historique', color=AtlasConfig.COLORS['secondary'])
            if self.forecast_result:
                last_date = self.data.index[-1]
                forecast_index = pd.date_range(start=last_date + timedelta(days=1), periods=len(self.forecast_result['forecast']), freq=self.freq)
                ax.plot(np.array(forecast_index), self.forecast_result['forecast'], label='Prévision', color=AtlasConfig.COLORS['warning'])
                ax.fill_between(np.array(forecast_index),
                                self.forecast_result['conf_int'][:, 0],
                                self.forecast_result['conf_int'][:, 1],
                                color=AtlasConfig.COLORS['warning'], alpha=0.2)
            ax.legend()
        else:
            ax = figure.add_subplot(111)
            ax.plot(np.array(self.data.index), self.data.values, color=AtlasConfig.COLORS['secondary'])
            ax.set_title('Série temporelle')
        figure.tight_layout()

# ========================
# INTELLIGENCE ENGINE (inchangé)
# ========================
