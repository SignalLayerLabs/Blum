"""Bounded dependency compatibility checks. Never silently select an execution backend."""
from importlib.metadata import PackageNotFoundError, version

SUPPORTED_VERSION='1.230.0'


def native_health() -> dict:
    try:
        actual=version('nautilus_trader')
        if actual!=SUPPORTED_VERSION:
            return dict(status='INCOMPATIBLE',version=actual,required=SUPPORTED_VERSION)
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.backtest.config import BacktestEngineConfig
        from nautilus_trader.common.config import LoggingConfig
        engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
        engine.dispose()
        return dict(status='AVAILABLE',version=actual,authority='compatibility_check_only',default_backend='declared_bar_scenario')
    except (ImportError,PackageNotFoundError):
        return dict(status='UNAVAILABLE',version=None,required=SUPPORTED_VERSION)
