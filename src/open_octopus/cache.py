import json
import os
from dataclasses import asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Any
from .models import Account, Tariff, Consumption, GasTariff, GasConsumption

class DateTimeEncoder(json.JSONEncoder):
    """Custom encoder to handle datetime objects."""
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)

class CacheManager:
    """
    Manages daily file-based caching for Octopus Energy data.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the cache manager.
        
        Args:
            cache_dir: custom cache directory. Defaults to OCTOPUS_CACHE_DIR env var or ~/.open-octopus/cache
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        elif os.environ.get("OCTOPUS_CACHE_DIR"):
            self.cache_dir = Path(os.environ["OCTOPUS_CACHE_DIR"])
        else:
            self.cache_dir = Path.home() / ".open-octopus" / "cache"
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        return self.cache_dir / f"{key}.json"

    def _is_fresh(self, timestamp_iso: str) -> bool:
        """
        Check if the cached data is fresh (flushes at 06:00 daily).
        
        Args:
            timestamp_iso: ISO format timestamp string
        
        Returns:
            True if valid, False if stale.
        """
        try:
            cached_dt = datetime.fromisoformat(timestamp_iso)
            now = datetime.now()
            
            # Determine the last flush point (Today 06:00 or Yesterday 06:00)
            today_6am = now.replace(hour=6, minute=0, second=0, microsecond=0)
            
            if now >= today_6am:
                last_flush = today_6am
            else:
                last_flush = today_6am - timedelta(days=1)
                
            return cached_dt >= last_flush
            
        except (ValueError, TypeError):
            return False

    def _load(self, key: str) -> Optional[Any]:
        """
        Load data from cache if it exists and is fresh.
        
        Returns:
             The 'data' portion of the cached JSON, or None if invalid/stale.
        """
        path = self._get_cache_path(key)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            
            if not isinstance(cached, dict) or "timestamp" not in cached or "data" not in cached:
                return None
            
            if self._is_fresh(cached["timestamp"]):
                return cached["data"]
            
        except (json.JSONDecodeError, IOError):
            return None
        
        return None

    def _save(self, key: str, data: Any):
        """Save data to cache with current timestamp."""
        path = self._get_cache_path(key)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, cls=DateTimeEncoder)
        except IOError:
            pass  # Fail usage silently

    # --- Type-specific caching methods ---

    def get_account(self) -> Optional[Account]:
        """Get cached account data."""
        data = self._load("account")
        if data:
            try:
                # Reconstruct Account object
                return Account(**data)
            except TypeError:
                return None
        return None

    def save_account(self, account: Account):
        """Save account data to cache."""
        self._save("account", asdict(account))

    def get_daily_usage(self) -> Optional[dict[str, float]]:
        """Get cached daily usage data."""
        return self._load("usage")

    def save_daily_usage(self, usage: dict[str, float]):
        """Save daily usage data to cache."""
        self._save("usage", usage)

    def get_tariff(self) -> Optional[Tariff]:
        """Get cached tariff data."""
        data = self._load("tariff")
        if data:
            try:
                # Reconstruct Tariff object
                return Tariff(**data)
            except TypeError:
                return None
        return None

    def save_tariff(self, tariff: Tariff):
        """Save tariff data to cache."""
        self._save("tariff", asdict(tariff))
        
    def get_consumption(self) -> Optional[list[Consumption]]:
        """Get cached granular consumption data."""
        data = self._load("consumption")
        if data:
            try:
                res = []
                for c in data:
                    c_copy = c.copy()
                    c_copy['start'] = datetime.fromisoformat(c_copy['start'])
                    c_copy['end'] = datetime.fromisoformat(c_copy['end'])
                    res.append(Consumption(**c_copy))
                return res
            except (TypeError, ValueError, KeyError):
                return None
        return None

    def save_consumption(self, consumption: list[Consumption]):
        """Save granular consumption data to cache."""
        # asdict will leave datetime objects as is, which DateTimeEncoder handles
        self._save("consumption", [asdict(c) for c in consumption])

    # --- Gas Caching ---

    def get_gas_tariff(self) -> Optional[GasTariff]:
        """Get cached gas tariff data."""
        data = self._load("gas_tariff")
        if data:
            try:
                # Reconstruct GasTariff object (GasTariff needs to be imported if not already)
                from .models import GasTariff
                return GasTariff(**data)
            except (TypeError, ImportError):
                return None
        return None

    def save_gas_tariff(self, tariff: GasTariff):
        """Save gas tariff data to cache."""
        self._save("gas_tariff", asdict(tariff))

    def get_daily_gas_usage(self) -> Optional[dict[str, float]]:
        """Get cached daily gas usage data."""
        return self._load("gas_usage")

    def save_daily_gas_usage(self, usage: dict[str, float]):
        """Save daily gas usage data to cache."""
        self._save("gas_usage", usage)

    def get_gas_consumption(self) -> Optional[list[GasConsumption]]:
        """Get cached granular gas consumption data."""
        data = self._load("gas_consumption")
        if data:
            try:
                from .models import GasConsumption
                res = []
                for c in data:
                    c_copy = c.copy()
                    c_copy['start'] = datetime.fromisoformat(c_copy['start'])
                    c_copy['end'] = datetime.fromisoformat(c_copy['end'])
                    res.append(GasConsumption(**c_copy))
                return res
            except (TypeError, ValueError, KeyError, ImportError):
                return None
        return None

    def save_gas_consumption(self, consumption: list[GasConsumption]):
        """Save granular gas consumption data to cache."""
        self._save("gas_consumption", [asdict(c) for c in consumption])

    def clear(self):
        """Clear all cached files."""
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass
