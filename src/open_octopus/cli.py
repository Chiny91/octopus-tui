"""Command-line interface for Open Octopus."""

import asyncio
import os
import sys
import select
import termios
import tty
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

import typer
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.live import Live
from rich.columns import Columns
from rich.progress import Progress, BarColumn, TextColumn
from rich import box
from collections import defaultdict

from .client import OctopusClient, OctopusError
from .models import DispatchStatus, Rate
from .cache import CacheManager

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = typer.Typer(
    name="octopus",
    help="Open Octopus - CLI for Octopus Energy API",
    no_args_is_help=True
)
screenshot_path = os.environ.get("OCTOPUS_SCREENSHOT")
console = Console(record=bool(screenshot_path))



def get_client() -> OctopusClient:
    """Create client from environment variables."""
    api_key = os.environ.get("OCTOPUS_API_KEY")
    account = os.environ.get("OCTOPUS_ACCOUNT")
    mpan = os.environ.get("OCTOPUS_MPAN")
    meter_serial = os.environ.get("OCTOPUS_METER_SERIAL")
    gas_mprn = os.environ.get("OCTOPUS_GAS_MPRN")
    gas_meter_serial = os.environ.get("OCTOPUS_GAS_METER_SERIAL")
    device_id = os.environ.get("OCTOPUS_DEVICE_ID")

    if not api_key or not account:
        console.print("[red]Error:[/] OCTOPUS_API_KEY and OCTOPUS_ACCOUNT must be set")
        console.print("\nSet environment variables:")
        console.print("  export OCTOPUS_API_KEY='sk_live_xxx'")
        console.print("  export OCTOPUS_ACCOUNT='A-XXXXXXXX'")
        console.print("  export OCTOPUS_ACCOUNT='A-XXXXXXXX'")
        sys.exit(1)

    return OctopusClient(api_key, account, mpan, meter_serial, gas_mprn, gas_meter_serial, device_id)


def run_async(coro):
    """Run an async function."""
    return asyncio.run(coro)


@contextmanager
def raw_mode(file):
    """Put file descriptor into raw mode."""
    if not os.isatty(file.fileno()):
        yield
        return
        
    old_attrs = termios.tcgetattr(file.fileno())
    new_attrs = old_attrs[:]
    # Disable ECHO and ICANON (canonical mode)
    new_attrs[3] = new_attrs[3] & ~(termios.ECHO | termios.ICANON)
    try:
        termios.tcsetattr(file.fileno(), termios.TCSADRAIN, new_attrs)
        yield
    finally:
        termios.tcsetattr(file.fileno(), termios.TCSADRAIN, old_attrs)


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------

@app.command()
def account():
    """Show account balance and info."""
    async def _run():
        async with get_client() as client:
            acc = await client.get_account()

            balance_color = "green" if acc.balance > 0 else "red"
            balance_text = f"£{abs(acc.balance):.2f} {'credit' if acc.balance > 0 else 'debit'}"

            console.print(Panel(
                f"[bold]{acc.name}[/]\n"
                f"Account: {acc.number}\n"
                f"Status: {acc.status}\n"
                f"Balance: [{balance_color}]{balance_text}[/]\n"
                f"Address: {acc.address}",
                title="Octopus Energy Account"
            ))

    run_async(_run())


@app.command()
def rate():
    """Show current electricity rate."""
    async def _run():
        async with get_client() as client:
            tariff = await client.get_tariff()
            if not tariff:
                console.print("[red]Could not fetch tariff info[/]")
                return

            current = client.get_current_rate(tariff)
            time_left = current.period_end - datetime.now()
            hours = int(time_left.total_seconds()) // 3600
            mins = (int(time_left.total_seconds()) % 3600) // 60

            if current.is_off_peak:
                console.print(f"[green]🌙 OFF-PEAK [bold]{current.rate:.1f}p/kWh[/][/]")
                console.print(f"   Ends in {hours}h {mins}m (at 05:30)")
            else:
                console.print(f"[yellow]☀️ PEAK [bold]{current.rate:.1f}p/kWh[/][/]")
                console.print(f"   Cheap rate in {hours}h {mins}m (at 23:30)")

            console.print(f"\nTariff: {tariff.name}", highlight=False)
            console.print(f"Standing charge: {tariff.standing_charge:.1f}p/day", highlight=False)

    run_async(_run())


@app.command()
def dispatch():
    """Show Intelligent Octopus dispatch status."""
    async def _run():
        async with get_client() as client:
            status = await client.get_dispatch_status()

            if status.is_dispatching and status.current_dispatch:
                d = status.current_dispatch
                console.print(f"[green bold]⚡ CHARGING NOW[/]")
                console.print(f"   Until {d.end.strftime('%H:%M')}")
            elif status.next_dispatch:
                d = status.next_dispatch
                now = datetime.now().astimezone(d.start.tzinfo)
                delta = d.start - now
                hours = int(delta.total_seconds()) // 3600
                mins = (int(delta.total_seconds()) % 3600) // 60
                console.print(f"[blue]🔌 Next charge:[/] {d.start.strftime('%H:%M')} - {d.end.strftime('%H:%M')}")
                console.print(f"   In {hours}h {mins}m ({d.duration_minutes}min window)")
            else:
                console.print("[dim]🔌 No dispatches scheduled[/]")

            # Show all upcoming dispatches
            dispatches = await client.get_dispatches()
            if len(dispatches) > 1:
                console.print("\n[bold]Upcoming dispatches:[/]")
                for d in dispatches[:5]:
                    console.print(f"  • {d.start.strftime('%a %H:%M')} - {d.end.strftime('%H:%M')}")

    run_async(_run())


@app.command()
def power():
    """Show live power consumption (requires Home Mini)."""
    async def _run():
        async with get_client() as client:
            live = await client.get_live_power()

            if live:
                watts = live.demand_watts
                if watts >= 1000:
                    power_str = f"{watts/1000:.2f} kW"
                else:
                    power_str = f"{watts} W"

                console.print(f"⚡ {power_str}", highlight=False)
                console.print(f"   Read at {live.read_at.strftime('%H:%M:%S')}", highlight=False)

                # Estimate hourly cost
                tariff = await client.get_tariff()
                if tariff:
                    current = client.get_current_rate(tariff)
                    cost_per_hour = (watts / 1000) * current.rate
                    console.print(f"   ~{cost_per_hour:.1f}p/hour at current rate", highlight=False)
            else:
                console.print("No live power data available", highlight=False)
                console.print("This requires a Home Mini paired with your smart meter.", highlight=False)

    run_async(_run())


@app.command()
def sessions():
    """Show upcoming Saving Sessions (free electricity)."""
    async def _run():
        async with get_client() as client:
            sessions = await client.get_saving_sessions()

            if not sessions:
                console.print("[dim]No upcoming Saving Sessions[/]")
                return

            console.print("[bold]🎁 Saving Sessions[/]\n")
            for s in sessions:
                if s.is_active:
                    console.print(f"[green bold]⚡ ACTIVE NOW[/] until {s.end.strftime('%H:%M')}")
                else:
                    console.print(f"📅 {s.start.strftime('%a %d %b %H:%M')} - {s.end.strftime('%H:%M')}")
                console.print(f"   [dim]{s.reward_per_kwh} Octopoints per kWh saved[/]")

    run_async(_run())


@app.command()
def usage(days: int = typer.Option(7, "--days", "-d", help="Number of days")):
    """Show daily electricity usage."""
    async def _run():
        async with get_client() as client:
            try:
                daily = await client.get_daily_usage(days)
            except Exception as e:
                console.print(f"[red]Error:[/] {e}")
                console.print("[dim]Note: MPAN and meter serial required for consumption data[/]")
                return

            if not daily:
                console.print("[dim]No consumption data available[/]")
                return

            table = Table(title=f"Last {days} Days Usage")
            table.add_column("Date", style="cyan")
            table.add_column("kWh", justify="right")
            table.add_column("Graph", justify="left")

            max_kwh = max(daily.values()) if daily else 1
            for date, kwh in sorted(daily.items(), reverse=True):
                bars = int((kwh / max_kwh) * 20)
                bar_str = "█" * bars
                table.add_row(date, f"{kwh:.1f}", f"[green]{bar_str}[/]")

            console.print(table)

    run_async(_run())


@app.command()
def status():
    """Show complete status overview."""
    async def _run():
        async with get_client() as client:
            console.print("[bold]🐙 Octopus Energy Status[/]\n")

            # Account
            try:
                acc = await client.get_account()
                balance_text = f"£{abs(acc.balance):.2f} {'credit' if acc.balance > 0 else 'debit'}"
                # Apply color to the whole string if needed, or just relying on existing formatting
                # The previous code was: console.print(f"💰 Balance: [bold]{balance_text}[/]")
                # We want the amount/debit part to be red if debit.
                # Let's construct a rich text string with color.
                if acc.balance > 0:
                     console.print(f"💰 Balance: [bold green]{balance_text}[/]")
                else:
                     console.print(f"💰 Balance: [bold red]{balance_text}[/]")
            except OctopusError as e:
                console.print(f"[red]Account error: {e}[/]")

            # Rate
            try:
                tariff = await client.get_tariff()
                if tariff:
                    current = client.get_current_rate(tariff)
                    rate_icon = "🌙" if current.is_off_peak else "☀️"
                    console.print(f"{rate_icon} Rate: [bold]{current.rate:.1f}p/kWh[/]")
            except OctopusError:
                pass

            # Live power
            try:
                live = await client.get_live_power()
                if live:
                    power_str = f"{live.demand_kw:.2f}kW" if live.demand_watts >= 1000 else f"{live.demand_watts}W"
                    console.print(f"⚡ Power: [bold]{power_str}[/]")
            except OctopusError:
                pass

            # Dispatch
            try:
                status = await client.get_dispatch_status()
                if status.is_dispatching:
                    console.print(f"🔌 [green]CHARGING[/]")
                elif status.next_dispatch:
                    console.print(f"🔌 Next: {status.next_dispatch.start.strftime('%H:%M')}")
            except OctopusError:
                pass

            # Sessions
            try:
                sessions = await client.get_saving_sessions()
                if sessions:
                    s = sessions[0]
                    if s.is_active:
                        console.print(f"🎁 [green bold]FREE POWER[/] until {s.end.strftime('%H:%M')}")
                    else:
                        console.print(f"🎁 Session: {s.start.strftime('%a %H:%M')}")
            except OctopusError:
                pass

    run_async(_run())


@app.command()
def watch(interval: int = typer.Option(30, "--interval", "-i", help="Refresh interval in seconds")):
    """Watch live power consumption (Ctrl+C to stop)."""
    async def _run():
        from rich.live import Live

        client = get_client()
        async with client:
            console.print() # Add empty line for visibility
            
            # Timeout logic
            timeout = int(os.environ.get("OCTOPUS_WATCH_TIMEOUT", 300))
            start_time = datetime.now()
            
            with Live(console=console, refresh_per_second=1) as live:
                while True:
                    # Check timeout
                    if timeout > 0:
                        if (datetime.now() - start_time).total_seconds() > timeout:
                            live.update(Panel(f"[yellow]Timeout reached ({timeout}s). Exiting to save API quota.[/]"))
                            await asyncio.sleep(2) # Give user a moment to see it
                            break

                    try:
                        power = await client.get_live_power()
                        tariff = await client.get_tariff()

                        if power and tariff:
                            watts = power.demand_watts
                            current = client.get_current_rate(tariff)
                            cost_per_hour = (watts / 1000) * current.rate

                            if watts >= 1000:
                                power_str = f"{watts/1000:.2f} kW"
                            else:
                                power_str = f"{watts} W"

                            # Use grid for stable layout
                            grid = Table.grid(padding=(0, 2))
                            grid.add_column(justify="right", min_width=12)  # Power
                            grid.add_column(justify="center", min_width=14) # Price (Widened for p/kWh)
                            grid.add_column(justify="left", min_width=10)  # Cost

                            # Use text instead of emojis to prevent "ragged" border width issues
                            rate_text = "OFF" if current.is_off_peak else "PEAK"
                            
                            grid.add_row(
                                f"[bold]Power {power_str}[/]",
                                f"[dim]{rate_text} {current.rate:.1f}p/kWh[/]",
                                f"[dim]~{cost_per_hour:.0f}p/hr[/]"
                            )

                            live.update(Panel(
                                grid,
                                title=f"Live Power ({power.read_at.strftime('%H:%M:%S')})",
                                box=box.ROUNDED,
                                expand=False,
                                padding=(0, 1), # Reduced padding
                                width=52 # Widened to fit Power label
                            ))
                        else:
                            live.update(Panel("[dim]Waiting for data...[/]"))

                        # Sleep logic
                        if timeout > 0:
                            elapsed = (datetime.now() - start_time).total_seconds()
                            remaining = timeout - elapsed
                            if remaining <= 0:
                                break
                            sleep_time = min(interval, remaining)
                            await asyncio.sleep(sleep_time)
                        else:
                            await asyncio.sleep(interval)
                    except KeyboardInterrupt:
                        break

    try:
        run_async(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped[/]")


@app.command()
def tui(refresh: int = typer.Option(60, "--refresh", "-r", help="Refresh interval in seconds")):
    """Interactive terminal dashboard with live updates."""

    # Standard Sparkline Blocks U+2581 to U+2588
    # Using explicit unicode escapes to avoid copy-paste errors
    SPARK_BLOCKS = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"]

    def make_sparkline(values: list, width: int = 24) -> str:
        """Create a sparkline from values."""
        if not values:
            return "─" * width
        # Normalize to width
        # Normalize to width
        if len(values) > width:
            # Downsample using Max Pooling to preserve peaks
            chunk_size = len(values) / width
            new_values = []
            for i in range(width):
                start_idx = int(i * chunk_size)
                end_idx = int((i + 1) * chunk_size)
                # Ensure we have at least one item and don't go out of bounds
                end_idx = max(start_idx + 1, min(end_idx, len(values)))
                chunk = values[start_idx:end_idx]
                new_values.append(max(chunk) if chunk else 0)
            values = new_values
        elif len(values) < width:
            values = values + [0] * (width - len(values))

        if not any(values):
            return "▁" * width

        min_val = min(values)
        max_val = max(values)
        range_val = max_val - min_val if max_val != min_val else 1

        result = ""
        for v in values:
            idx = int((v - min_val) / range_val * 7)
            idx = max(0, min(7, idx))
            result += SPARK_BLOCKS[idx]
        return result

    def make_bar(value: float, max_val: float, width: int = 20, color: str = "green") -> str:
        """Create a progress bar."""
        if max_val == 0:
            return "░" * width
        filled = int((value / max_val) * width)
        filled = max(0, min(width, filled))
        return f"[{color}]{'█' * filled}[/]{'░' * (width - filled)}"

    def format_time_delta(seconds: int) -> str:
        """Format seconds as Xh Xm."""
        if seconds <= 0:
            return "now"
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    async def build_dashboard(client: OctopusClient) -> Table:
        """Build the complete dashboard."""
        
        # --- 1. Define Helper Fetchers (Wraps Cache + Fetch Logic) ---

        async def fetch_account(cache):
            try:
                acc = cache.get_account()
                if not acc:
                    acc = await client.get_account()
                    if acc: cache.save_account(acc)
                return acc
            except:
                return None

        async def fetch_tariff(cache):
            try:
                tariff = cache.get_tariff()
                if not tariff:
                    tariff = await client.get_tariff()
                    if tariff: cache.save_tariff(tariff)
                return tariff
            except:
                return None

        async def fetch_gas_tariff(cache):
            try:
                gt = cache.get_gas_tariff()
                if not gt:
                    gt = await client.get_gas_tariff()
                    if gt: cache.save_gas_tariff(gt)
                return gt
            except:
                return None

        async def fetch_live_history():
            try:
                return await client.get_live_power_history(minutes=30)
            except:
                return []

        async def fetch_dispatches():
            try:
                return await client.get_dispatches()
            except:
                return []

        async def fetch_sessions():
            try:
                return await client.get_saving_sessions()
            except:
                return []

        # --- 2. Phase 1: Parallel Fetch Core Data ---
        
        cache = CacheManager()
        
        results = await asyncio.gather(
            fetch_account(cache),
            fetch_tariff(cache),
            fetch_gas_tariff(cache),
            fetch_live_history(),
            fetch_dispatches(),
            fetch_sessions(),
            return_exceptions=True
        )

        # Unpack results safely
        acc = results[0] if not isinstance(results[0], Exception) else None
        tariff = results[1] if not isinstance(results[1], Exception) else None
        gas_tariff = results[2] if not isinstance(results[2], Exception) else None
        # Validating list types
        live_power_history = results[3] if isinstance(results[3], list) else []
        dispatches = results[4] if isinstance(results[4], list) else []
        if isinstance(results[4], Exception):
            with open("error.log", "a") as f:
                f.write(f"{datetime.now()}: Error fetching dispatches: {results[4]}\n")
            console.print(f"[red]Error: Check error.log[/]")
        sessions = results[5] if isinstance(results[5], list) else []

        # --- 3. Process Phase 1 Results ---

        # Live Power (Latest)
        live_power = live_power_history[-1] if live_power_history else None

        # Dispatch Status (Local Logic - Eliminates redundant API call)
        now = datetime.now()
        cur_dispatch = None
        next_dispatch = None
        
        for d in dispatches:
            try:
                from datetime import timezone
                # Dispatch timestamps are offset-aware (fromisoformat in client handles it)
                # But we ensure comparison works. d.start should have tz info.
                # Client code ensures d.start is aware. 'now' needs to be aware.
                if d.start.tzinfo and now.tzinfo is None:
                    now_tz = now.astimezone(d.start.tzinfo)
                elif now.tzinfo:
                     now_tz = now
                else:
                     # Fallback if both naive (unlikely)
                     now_tz = now

                if d.start <= now_tz <= d.end:
                    cur_dispatch = d
                elif d.start > now_tz and next_dispatch is None:
                    next_dispatch = d
            except: pass
            
        dispatch_status = DispatchStatus(
            is_dispatching=(cur_dispatch is not None),
            current_dispatch=cur_dispatch,
            next_dispatch=next_dispatch
        )

        # Current Rate
        current_rate = None
        if tariff:
            try:
                 current_rate = client.get_current_rate(tariff)
                 # Override if smart charging (Intelligent Octopus Go)
                 if dispatch_status.is_dispatching and dispatch_status.current_dispatch:
                      if not current_rate.is_off_peak:
                           current_rate = Rate(
                               rate=tariff.off_peak_rate or 7.0,
                               is_off_peak=True,
                               period_end=dispatch_status.current_dispatch.end,
                               next_rate=tariff.peak_rate or 30.0
                           )
                 elif dispatch_status.next_dispatch and not current_rate.is_off_peak:
                      # If not currently charging (Peak) but have a scheduled charge coming up sooner than standard off-peak (23:30)
                      # Curtail the "Peak" period to the start of the next charge
                      next_start = dispatch_status.next_dispatch.start
                      # Ensure current_rate.period_end is aware for comparison
                      p_end = current_rate.period_end
                      if p_end.tzinfo is None and next_start.tzinfo:
                           p_end = p_end.replace(tzinfo=next_start.tzinfo) # Assume local/same tz if missing
                      
                      if next_start < p_end:
                           current_rate.period_end = next_start
            except: pass

        # Dispatch logic moved above to support rate override

        # --- 4. Phase 2: Parallel Fetch Consumption (if needed) ---
        
        async def fetch_elec_consumption(cache):
            d_usage = cache.get_daily_usage()
            consump = cache.get_consumption()
            
            if not d_usage or not consump:
                try:
                    start_7d = datetime.now() - timedelta(days=7)
                    start_7d = start_7d.replace(hour=0, minute=0, second=0, microsecond=0)
                    consump = await client.get_consumption(periods=336, start=start_7d)
                    
                    # Process daily
                    d_map = defaultdict(float)
                    for c in consump:
                        day_str = c.start.strftime("%Y-%m-%d")
                        d_map[day_str] += c.kwh
                    d_usage = dict(d_map)
                    
                    cache.save_daily_usage(d_usage)
                    cache.save_consumption(consump)
                except:
                   pass
            return d_usage, consump

        async def fetch_gas_consumption_data(cache):
            g_d_usage = cache.get_daily_gas_usage()
            g_consump = cache.get_gas_consumption()
            
            if not g_d_usage or not g_consump:
                try:
                    start_7d = datetime.now() - timedelta(days=7)
                    start_7d = start_7d.replace(hour=0, minute=0, second=0, microsecond=0)
                    g_consump = await client.get_gas_consumption(periods=336, start=start_7d)
                    
                    g_map = defaultdict(float)
                    for c in g_consump:
                        day_str = c.start.strftime("%Y-%m-%d")
                        g_map[day_str] += c.kwh
                    g_d_usage = dict(g_map)
                    
                    cache.save_daily_gas_usage(g_d_usage)
                    cache.save_gas_consumption(g_consump)
                except:
                    pass
            return g_d_usage, g_consump
            
        (elec_res, gas_res) = await asyncio.gather(
            fetch_elec_consumption(cache), 
            fetch_gas_consumption_data(cache),
            return_exceptions=True
        )
        
        daily_usage, consumption = elec_res if not isinstance(elec_res, Exception) else (None, None)
        gas_daily_usage, gas_consumption = gas_res if not isinstance(gas_res, Exception) else (None, None)

        # --- 5. Data Processing (Hourly Maps) ---
        
        hourly_today = defaultdict(float)
        display_date_str = "Today"
        
        if consumption:
            # Reconstruct hourly map
            hourly_usage_map = defaultdict(lambda: defaultdict(float))
            for c in consumption:
                day_str = c.start.strftime("%Y-%m-%d")
                hourly_usage_map[day_str][c.start.hour] += c.kwh

            if hourly_usage_map:
                latest_day = max(hourly_usage_map.keys())
                hourly_today = hourly_usage_map[latest_day]
                try:
                    display_date_str = datetime.strptime(latest_day, "%Y-%m-%d").strftime("%a %d %b")
                except: pass
        
        gas_hourly_today = defaultdict(float)
        gas_display_date_str = "Today"
        
        if gas_consumption:
             gas_hourly_usage_map = defaultdict(lambda: defaultdict(float))
             for c in gas_consumption:
                 day_str = c.start.strftime("%Y-%m-%d")
                 gas_hourly_usage_map[day_str][c.start.hour] += c.kwh

             if gas_hourly_usage_map:
                 gas_latest_day = max(gas_hourly_usage_map.keys())
                 gas_hourly_today = gas_hourly_usage_map[gas_latest_day]
                 try:
                     gas_display_date_str = datetime.strptime(gas_latest_day, "%Y-%m-%d").strftime("%a %d")
                 except: pass



        # === PANELS ===

        # Balance Panel

        # Balance panel
        # Balance panel
        if acc:
            is_credit = acc.balance > 0
            balance_color = "green" if is_credit else "red"
            balance_text = Text()
            # Header removed from text, moved to Panel title
            balance_text.append(f"£{abs(acc.balance):.2f}", style=f"bold {balance_color}")
            balance_text.append(f" {'credit' if is_credit else 'debit'}", style="bold" if is_credit else "bold red")
            balance_panel = Panel(balance_text, title="[bold]💷 BALANCE[/]", title_align="left", box=box.ROUNDED, height=5)
        else:
            balance_panel = Panel("Balance unavailable", title="[bold]💷 BALANCE[/]", title_align="left", box=box.ROUNDED, height=5)

        # Rate panel
        if current_rate and tariff:
            now = datetime.now()
            if current_rate.period_end.tzinfo:
                now = now.astimezone(current_rate.period_end.tzinfo)
            time_left = format_time_delta(int((current_rate.period_end - now).total_seconds()))
            rate_icon = "🌙" if current_rate.is_off_peak else "☀️"
            rate_text = Text()
            
            rate_icon = "🌙" if current_rate.is_off_peak else "☀️" # Re-declare for safety if needed, or assume available
            rate_title = f"[bold]{rate_icon} TARIFF[/]"
            
            rate_text = Text()
            # Line 0: Electricity Header
            rate_text.append("ELECTRICITY\n", style="cyan bold")
            # Line 1: Time Left
            status_label = "Offpeak" if current_rate.is_off_peak else "Peak"
            rate_text.append(f"{status_label} {time_left} left\n")
            
            # Line 2: Tariff Name
            rate_text.append(f"Tariff: {tariff.name}\n")
            
            # Line 3: Computed Rates
            if tariff.off_peak_rate:
                rate_text.append(f"Peak rate {tariff.peak_rate:.1f}p  Offpeak {tariff.off_peak_rate:.1f}p\n")
            
            # Line 4: Standing Charge
            rate_text.append(f"Standing charge: {tariff.standing_charge:.1f}p/day\n")
            
            # --- GAS SECTION ---
            rate_text.append("GAS\n", style="bold cyan")
            if gas_tariff:
                rate_text.append(f"Today's Rate: {gas_tariff.unit_rate:.2f}p/kWh\n")
                rate_text.append(f"Standing charge: {gas_tariff.standing_charge:.2f}p/day")
            else:
                 rate_text.append("Gas rate unavailable")

            rate_panel = Panel(rate_text, title=rate_title, title_align="left", box=box.ROUNDED, height=None) # Auto height
        else:
            rate_panel = Panel("Rate unavailable", title="[bold]RATE[/]", title_align="left", box=box.ROUNDED, height=5)



        # Live power panel
        if live_power:
            watts = live_power.demand_watts
            power_str = f"{watts/1000:.2f}kW" if watts >= 1000 else f"{watts}W"
            
            # 1. Determine Color (Peak/Off-Peak)
            is_off_peak = False
            if current_rate:
                is_off_peak = current_rate.is_off_peak
            else:
                 # Fallback based on time if rate unavailable (typical 23:30-05:30)
                 now_time = datetime.now().time()
                 if (now_time.hour == 23 and now_time.minute >= 30) or (now_time.hour < 5) or (now_time.hour == 5 and now_time.minute < 30):
                     is_off_peak = True
            
            # 1. Determine Color (Peak/Off-Peak)
            is_off_peak = False
            if current_rate:
                is_off_peak = current_rate.is_off_peak
            else:
                 # Fallback based on time if rate unavailable (typical 23:30-05:30)
                 now_time = datetime.now().time()
                 if (now_time.hour == 23 and now_time.minute >= 30) or (now_time.hour < 5) or (now_time.hour == 5 and now_time.minute < 30):
                     is_off_peak = True
            
            style_color = "green" if is_off_peak else "blue"


            
            # 2. Graph Logic
            # We want to show sparkline for last 30 mins
            # History is a list of LivePower objects
            
            # Extract demand values
            # Normalize list to fixed width for graph (e.g. 60 chars) or simply plot all if few
            # We have roughly 180 points (6 * 30). Graph width around 40-50 chars?
            # Let's resample to 50 points
            points = [p.demand_watts for p in live_power_history]
            
            # Use make_sparkline utility
            # It handles normalization to width
            # Match width of Half-Hourly graph (48 slots/chars)
            spark_line = make_sparkline(points, width=48)
            
            # X-Axis Labels (Fixed Width 48 Chars)
            # -30m (4) ... gap 18 ... -15m (4) ... gap 19 ... Now (3) = 48 chars
            xaxis_label = Text("-30m" + " " * 18 + "-15m" + " " * 19 + "Now")

            # Construct Table for Panel Layout (Side-by-Side)
            power_layout = Table.grid(expand=True, padding=(0, 1))
            power_layout.add_column(justify="left")  # Graph Column (Left)
            power_layout.add_column(justify="right", vertical="middle") # Text Column (Right)
            
            # Left: Graph + Axis (Stacked)
            graph_col = Table.grid()
            graph_col.add_row(f"[{style_color}]{spark_line}[/]")
            graph_col.add_row(xaxis_label)

            # Right: Info Text (Stacked) - Left align to be close to graph "Now"
            info_text = Text(justify="right")
            info_text.append(f"{power_str}\n", style=f"bold {style_color}")
            if current_rate:
                cost_per_hr = (watts / 1000) * current_rate.rate
                cost_str = f"{cost_per_hr:.0f}p/hr"
                info_text.append(cost_str, style=style_color)
            
            power_layout.add_row(graph_col, info_text)

            power_panel = Panel(power_layout, title="[bold]⚡ ELECTRICITY USAGE LIVE[/]", title_align="left", box=box.ROUNDED, height=None)
        else:
            power_panel = Panel("Requires Home Mini", title="[bold]⚡ ELECTRICITY USAGE LIVE[/]", title_align="left", box=box.ROUNDED, height=None)

        # Saving sessions panel

        if sessions:
            session_text = Text()
            # Header removed
            for s in sessions[:3]:
                if s.is_active:
                    session_text.append(f"⚡ ACTIVE until {s.end.strftime('%H:%M')}\n", style="green bold")
                else:
                    session_text.append(f"📅 {s.start.strftime('%a %d %b %H:%M')} - {s.end.strftime('%H:%M')}\n")
                session_text.append(f"   {s.reward_per_kwh} Octopoints/kWh\n")
            session_panel = Panel(session_text, title="[bold]🎁 ELECTRICITY SAVING SESSIONS[/]", title_align="left", box=box.ROUNDED, height=None)
        else:
            session_panel = Panel("No upcoming Saving Sessions", title="[bold]🎁 ELECTRICITY SAVING SESSIONS[/]", title_align="left", box=box.ROUNDED, height=None)

        # === PREPARE USAGE DATA ===

        # 1. Usage by Hour
        today_kwh = sum(hourly_today.values())
        today_cost_p = 0.0
        
        # Calculate today's cost if we have tariff data
        if hourly_today and tariff:
             # Filter consumption for the display date
             today_consump = [c for c in (consumption or []) if c.start.strftime("%Y-%m-%d") == (latest_day if hourly_today else "")]
             
             for c in today_consump:
                 # Check if off-peak
                 is_off_peak = False
                 if tariff.off_peak_start and tariff.off_peak_end:
                     try:
                        t_start = datetime.strptime(tariff.off_peak_start, "%H:%M").time()
                        t_end = datetime.strptime(tariff.off_peak_end, "%H:%M").time()
                        c_time = c.start.time()
                        if t_start > t_end:
                            is_off_peak = c_time >= t_start or c_time < t_end
                        else:
                            is_off_peak = t_start <= c_time < t_end
                     except:
                        pass
                 
                 if not tariff.off_peak_start:
                     h = c.start.hour
                     m = c.start.minute
                     if (h == 23 and m >= 30) or (h < 5) or (h == 5 and m < 30):
                         is_off_peak = True

                 rate = tariff.off_peak_rate if is_off_peak and tariff.off_peak_rate else (tariff.peak_rate or 0)
                 today_cost_p += c.kwh * rate
        
        # If no tariff but we have consumption, ensure we still have data for graph
        if hourly_today and not tariff:
            today_consump = [c for c in (consumption or []) if c.start.strftime("%Y-%m-%d") == (latest_day if hourly_today else "")]

        # Structure Usage By Hour as a Table
        # Removed Date column to give graph full width
        usage_table = Table(box=None, padding=(0, 0), show_header=False, expand=True)
        usage_table.add_column("Usage", ratio=1, justify="center", overflow="crop", no_wrap=True)

        if hourly_today:
            # Map consumption to 48 half-hour slots
            slots = [0.0] * 48
            slot_colors = ["blue"] * 48
            
            # Populate slots from today_consump
            for c in today_consump:
                h = c.start.hour
                m = c.start.minute
                # Calculate slot index 0-47
                idx = h * 2 + (1 if m >= 30 else 0)
                if 0 <= idx < 48:
                    slots[idx] += c.kwh
                    
                    # Determine color based on off-peak
                    is_off_peak = False
                    if tariff and tariff.off_peak_start:
                        # Simple check for now based on typical Go setup or tariff data
                        if (h == 23 and m >= 30) or (h < 5) or (h == 5 and m < 30): 
                            is_off_peak = True
                            
                    if is_off_peak:
                        slot_colors[idx] = "green"

            max_slot = max(slots) if slots else 1
            max_slot = max(0.001, max_slot) # Avoid div/0
            
            # Generate Single-Row Graph (High Precision)
            # Using 0-7 range (8 levels) with Unicode blocks to avoid gaps
            
            hour_bars = ""
            for i, val in enumerate(slots):
                color = slot_colors[i]
                if val > 0:
                    # Normalize to 0-7 range
                    height = int((val / max_slot) * 7)
                    height = max(0, min(7, height))
                    hour_bars += f"[{color}]{SPARK_BLOCKS[height]}[/]"
                else:
                    # Zero usage marker
                    hour_bars += f"[dim]{SPARK_BLOCKS[0]}[/]"

            # Use concise date format "Mon 19"
            try:
                dt_obj = datetime.strptime(latest_day, "%Y-%m-%d") if latest_day else datetime.now()
                display_date = dt_obj.strftime("%a %d")
            except:
                display_date = "Today"

            # Row 1: Graph
            usage_table.add_row(hour_bars)
            
            # Row 2: Axis Labels
            usage_table.add_row("0           6           12          18          24")

            today_panel = Panel(usage_table, title=f"[bold]⚡ ELECTRICITY HALF-HOURLY USAGE - {display_date}[/]", title_align="left", box=box.ROUNDED)
        else:
            today_panel = Panel("No data", title="[bold]⚡ ELECTRICITY HALF-HOURLY USAGE[/]", title_align="left", box=box.ROUNDED)

        # 2. Scheduled Charges (Unlimited List)
        sched_text = Text()
        # Header removed
        
        has_schedule = False
        
        # Current Status
        if dispatch_status and dispatch_status.is_dispatching and dispatch_status.current_dispatch:
            d = dispatch_status.current_dispatch
            sched_text.append(f"⚡ CHARGING NOW until {d.end.strftime('%H:%M')}\n", style="bold green")
            has_schedule = True
        
        # Upcoming List
        all_upcoming = []
        if dispatch_status and dispatch_status.next_dispatch:
             all_upcoming.append(dispatch_status.next_dispatch)
        if dispatches:
            all_upcoming.extend(dispatches)
            
        unique_upcoming = {d.start: d for d in all_upcoming}.values()
        sorted_upcoming = sorted(unique_upcoming, key=lambda x: x.start)
        now = datetime.now().astimezone()
        future_upcoming = [d for d in sorted_upcoming if d.start > now]

        if future_upcoming:
            # Show ALL upcoming slots as requested (dynamic height)
            for d in future_upcoming:
                sched_text.append(f"• {d.start.strftime('%a %H:%M')} - {d.end.strftime('%H:%M')}\n")
            has_schedule = True
        
        if not has_schedule:
             sched_text.append("No charges scheduled")

        sched_panel = Panel(sched_text, title="[bold]🔌 EV SCHEDULED CHARGES[/]", title_align="left", box=box.ROUNDED, height=None)

        # === 7-Day Usage Prep ===



        # 7-Day Usage
        if daily_usage:
            # Create inner table for alignment - Matching widths with Usage By Hour
            week_table = Table(box=None, padding=(0, 1), show_header=True, expand=True)
            week_table.add_column("Date", width=12)
            week_table.add_column("Usage", width=16, overflow="crop", no_wrap=True) # Matches 16
            week_table.add_column("kWh", justify="right", width=8)
            week_table.add_column("Cost", justify="right", width=10)
            week_table.add_column("Av p/kWh", justify="right", width=10)

            sorted_days = sorted(daily_usage.items(), reverse=True)[:7]
            max_daily = max(daily_usage.values()) if daily_usage else 1
            
            total_week_cost_p = 0.0
            total_week_energy_cost_p = 0.0
            
            for date_str, kwh in sorted_days:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    day_name = dt.strftime("%a %d")
                except:
                    day_name = date_str[:6]
                
                # Calculate daily cost
                daily_cost_p = 0.0 # Total cost including standing charge
                daily_energy_cost_p = 0.0 # Energy cost only (for p/kWh calculation)
                
                if consumption and tariff:
                    # Add Standing Charge
                    daily_cost_p += tariff.standing_charge
                    
                    day_consump = [c for c in consumption if c.start.strftime("%Y-%m-%d") == date_str]
                    for c in day_consump:
                         is_off_peak = False
                         if not tariff.off_peak_start:
                             h = c.start.hour
                             m = c.start.minute
                             if (h == 23 and m >= 30) or (h < 5) or (h == 5 and m < 30): is_off_peak = True
                         else:
                             h = c.start.hour
                             m = c.start.minute
                             if (h == 23 and m >= 30) or (h < 5) or (h == 5 and m < 30): is_off_peak = True
                         
                         rate = tariff.off_peak_rate if is_off_peak and tariff.off_peak_rate else (tariff.peak_rate or 0)
                         cost_chunk = c.kwh * rate
                         daily_cost_p += cost_chunk
                         daily_energy_cost_p += cost_chunk
                
                total_week_cost_p += daily_cost_p
                total_week_energy_cost_p += daily_energy_cost_p
                # Average rate is derived from Energy Cost / kWh (excludes standing charge)
                avg_p = (daily_energy_cost_p / kwh) if kwh > 0 else 0
                
                bar = make_bar(kwh, max_daily, 14, "blue") # Width 14 to fit in 16 col
                week_table.add_row(
                    day_name,
                    bar,
                    f"{kwh:.1f}",
                    f"£{daily_cost_p/100:.2f}",
                    f"{avg_p:.1f}p"
                )
            
            # Totals Footer
            total = sum(daily_usage.values())
            avg_kwh = total/len(daily_usage) if daily_usage else 0
            # Week Average Unit Rate = Total Energy Cost / Total kWh (Excluding standing charges)
            avg_cost_p_kwh = (total_week_energy_cost_p / total) if total > 0 else 0
            
            week_table.add_row(
                "Week",
                "",
                f"{total:.1f}",
                f"£{total_week_cost_p/100:.2f}",
                f"{avg_cost_p_kwh:.1f}p",
                style="cyan bold"
            )

            week_panel = Panel(week_table, title="[bold]⚡ 7-DAY ELECTRICITY USAGE[/]", title_align="left", box=box.ROUNDED)
            
        else:
            week_panel = Panel("No data", title="[bold]⚡ 7-DAY ELECTRICITY USAGE[/]", title_align="left", box=box.ROUNDED)

        # Gas 7-Day Usage
        gas_rates = {}
        if gas_daily_usage and gas_tariff:
            try:
                # Determine date range for rates
                # dates are YYYY-MM-DD keys in gas_daily_usage
                dates = sorted(gas_daily_usage.keys())
                if dates:
                     start_dt = datetime.strptime(min(dates), "%Y-%m-%d")
                     end_dt = datetime.strptime(max(dates), "%Y-%m-%d") + timedelta(days=1)
                     gas_rates = await client.get_gas_rates(gas_tariff, start=start_dt, end=end_dt)
            except Exception as e:
                pass

        if gas_daily_usage:
            gas_week_table = Table(box=None, padding=(0, 1), show_header=True, expand=True)
            gas_week_table.add_column("Date", width=12)
            gas_week_table.add_column("Usage", width=16, overflow="crop", no_wrap=True)
            gas_week_table.add_column("kWh", justify="right", width=8)
            gas_week_table.add_column("Cost", justify="right", width=10)
            gas_week_table.add_column("p/kWh", justify="right", width=10)

            sorted_gas_days = sorted(gas_daily_usage.items(), reverse=True)[:7]
            max_gas_daily = max(gas_daily_usage.values()) if gas_daily_usage else 1
            
            total_gas_week_cost_p = 0.0
            total_gas_week_kwh = 0.0
            total_gas_energy_cost_p = 0.0 # Cost dependent on usage only (kwh * rate)
            
            for date_str, kwh in sorted_gas_days:
                total_gas_week_kwh += kwh
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    day_name = dt.strftime("%a %d")
                except:
                    day_name = date_str[:6]
                
                # Daily Cost: Standing Charge + (kWh * Rate)
                daily_gas_cost_p = 0.0
                daily_rate = 0.0
                
                if gas_tariff:
                    # Standing charge is daily
                    daily_gas_cost_p += gas_tariff.standing_charge
                    
                    # Unit rate - try specific day rate first, else fall back to current
                    daily_rate = gas_rates.get(date_str, gas_tariff.unit_rate)
                    daily_gas_cost_p += kwh * daily_rate
                    total_gas_energy_cost_p += kwh * daily_rate
                
                total_gas_week_cost_p += daily_gas_cost_p
                # distinct from average, we show the actual rate used
                display_rate = daily_rate
                
                bar = make_bar(kwh, max_gas_daily, 14, "#D97706")
                gas_week_table.add_row(
                    day_name,
                    bar,
                    f"{kwh:.1f}",
                    f"£{daily_gas_cost_p/100:.2f}",
                    f"{display_rate:.1f}p"
                )
            
            # Totals
            # Calculate average UNIT RATE (excluding standing charges) to match daily column
            avg_gas_cost_p_kwh = (total_gas_energy_cost_p / total_gas_week_kwh) if total_gas_week_kwh > 0 else 0
            
            gas_week_table.add_row(
                "Week",
                "",
                f"{total_gas_week_kwh:.1f}",
                f"£{total_gas_week_cost_p/100:.2f}",
                f"{avg_gas_cost_p_kwh:.1f}p",
                style="cyan bold"
            )
            
            gas_week_panel = Panel(gas_week_table, title="[bold]🔥 7-DAY GAS USAGE[/]", title_align="left", box=box.ROUNDED)
        else:
            gas_week_panel = Panel("No data", title="[bold]🔥 7-DAY GAS USAGE[/]", title_align="left", box=box.ROUNDED)

        # Gas Usage by Hour (Half-Hourly)
        gas_today_usage_table = Table(box=None, padding=(0, 0), show_header=False, expand=True)
        gas_today_usage_table.add_column("Usage", ratio=1, justify="center", overflow="crop", no_wrap=True)
        
        if gas_hourly_today:
            # We need the actual consumption objects for the latest day to get half-hourly precision
            # Reuse logic from electricity
            gas_today_consump = []
            if gas_consumption:
                 # Find latest day string again or reuse gas_latest_day if accessible (it was local)
                 # Re-derive safely
                 dates = sorted(list(set(c.start.strftime("%Y-%m-%d") for c in gas_consumption)))
                 if dates:
                     tgt_date = dates[-1]
                     gas_today_consump = [c for c in gas_consumption if c.start.strftime("%Y-%m-%d") == tgt_date]

            # Slots 0-47
            g_slots = [0.0] * 48
            
            for c in gas_today_consump:
                h = c.start.hour
                m = c.start.minute
                idx = h * 2 + (1 if m >= 30 else 0)
                if 0 <= idx < 48:
                    g_slots[idx] += c.kwh

            g_max_slot = max(g_slots) if g_slots else 1
            g_max_slot = max(0.001, g_max_slot)

            g_hour_bars = ""
            for val in g_slots:
                if val > 0:
                    height = int((val / g_max_slot) * 7)
                    height = max(0, min(7, height))
                    g_hour_bars += f"[#D97706]{SPARK_BLOCKS[height]}[/]"
                else:
                    g_hour_bars += f"[dim]{SPARK_BLOCKS[0]}[/]"
            
            gas_today_usage_table.add_row(g_hour_bars)
            gas_today_usage_table.add_row("0           6           12          18          24")
            
            gas_today_panel = Panel(gas_today_usage_table, title=f"[bold]🔥 GAS HALF-HOURLY USAGE - {gas_display_date_str}[/]", title_align="left", box=box.ROUNDED)
        else:
            gas_today_panel = Panel("No data", title="[bold]🔥 GAS HALF-HOURLY USAGE[/]", title_align="left", box=box.ROUNDED)

        # === ASSEMBLE GRID ===

        # Main Layout Grid: 2 Columns
        main_grid = Table.grid(expand=True)
        main_grid.add_column(ratio=3)
        main_grid.add_column(ratio=2)
        
        # Left Stack
        left_stack = Table.grid(expand=True)
        left_stack.add_row(power_panel) # Live Power Moved Here
        left_stack.add_row(today_panel)
        left_stack.add_row(week_panel)
        left_stack.add_row(gas_today_panel)
        left_stack.add_row(gas_week_panel)
        
        # Right Stack
        right_stack = Table.grid(expand=True)
        right_stack.add_row(balance_panel)
        right_stack.add_row(rate_panel)
        # power_panel was here
        right_stack.add_row(session_panel)
        right_stack.add_row(sched_panel)
        
        main_grid.add_row(left_stack, right_stack)
        
        # Footer
        footer = Table.grid(expand=True)
        footer.add_column(justify="left")
        footer.add_column(justify="right")
        footer.add_row(
            Text("f to flush cache   q to quit", style="dim"),
            Text(f"Updated {datetime.now().strftime('%H:%M:%S')}", style="dim")
        )

        # Add Header and Main Grid to Root Grid
        # Header
        header_text = Text()
        header_text.append("🐙 OCTOPUS ENERGY", style="bold cyan")
        
        # Add Header FIRST
        final_grid = Table.grid(expand=True)
        final_grid.add_row(Panel(header_text, box=box.ROUNDED))
        final_grid.add_row(main_grid)
        final_grid.add_row(footer)
        
        return final_grid
        
    def build_loading_dashboard() -> Table:
        """Builds a temporary dashboard to show while flushing cache."""
        # Create empty/loading panels
        balance_panel = Panel("...", title="[bold]💷 BALANCE[/]", title_align="left", box=box.ROUNDED, height=5)
        power_panel = Panel("...", title="[bold]⚡ ELECTRICITY USAGE LIVE[/]", title_align="left", box=box.ROUNDED, height=None)
        
        rate_panel = Panel("...", title="[bold]ELECTRICITY RATE[/]", title_align="left", box=box.ROUNDED, height=None)
        
        session_panel = Panel("...", title="[bold]🎁 ELECTRICITY SAVING SESSIONS[/]", title_align="left", box=box.ROUNDED, height=None)
        
        today_panel = Panel("...", title="[bold]⚡ ELECTRICITY HALF-HOURLY USAGE[/]", title_align="left", box=box.ROUNDED)
        week_panel = Panel("...", title="[bold]⚡ 7-DAY ELECTRICITY USAGE[/]", title_align="left", box=box.ROUNDED)
        gas_today_panel = Panel("...", title="[bold]🔥 GAS HALF-HOURLY USAGE[/]", title_align="left", box=box.ROUNDED)
        gas_week_panel = Panel("...", title="[bold]🔥 7-DAY GAS USAGE[/]", title_align="left", box=box.ROUNDED)
        
        sched_panel = Panel("...", title="[bold]🔌 EV SCHEDULED CHARGES[/]", title_align="left", box=box.ROUNDED, height=None)

        # Main Layout Grid: 2 Columns
        main_grid = Table.grid(expand=True)
        main_grid.add_column(ratio=3)
        main_grid.add_column(ratio=2)
        
        # Left Stack
        left_stack = Table.grid(expand=True)
        left_stack.add_row(today_panel)
        left_stack.add_row(week_panel)
        left_stack.add_row(gas_today_panel)
        left_stack.add_row(gas_week_panel)
        
        # Right Stack
        right_stack = Table.grid(expand=True)
        right_stack.add_row(balance_panel)
        right_stack.add_row(rate_panel)
        right_stack.add_row(power_panel)
        right_stack.add_row(session_panel)
        right_stack.add_row(sched_panel)
        
        main_grid.add_row(left_stack, right_stack)
        
        # Footer
        footer = Table.grid(expand=True)
        footer.add_column(justify="left")
        footer.add_column(justify="right")
        footer.add_row(
            Text("Flushing cache... please wait.", style="bold yellow"),
            Text(f"Updated {datetime.now().strftime('%H:%M:%S')}", style="dim")
        )

        # Header
        header_text = Text()
        header_text.append("🐙 OCTOPUS ENERGY", style="bold cyan")
        
        final_grid = Table.grid(expand=True)
        final_grid.add_row(Panel(header_text, box=box.ROUNDED))
        final_grid.add_row(main_grid)
        final_grid.add_row(footer)
        
        return final_grid

    async def _run():
        client = get_client()

        # Input listener setup - no background thread needed
        stop_event = asyncio.Event()

        async with client:
            # Put stdin in raw mode so we can catch single keypresses
            with raw_mode(sys.stdin):
                with Live(console=console, refresh_per_second=0.5, screen=True) as live:
                    while not stop_event.is_set():
                        try:
                            # 1. Update Dashboard
                            dashboard = await build_dashboard(client)
                            
                            if os.environ.get("OCTOPUS_SCREENSHOT"):
                                console.print(dashboard)
                                if os.environ.get("OCTOPUS_SCREENSHOT").endswith(".html"):
                                    console.save_html(os.environ.get("OCTOPUS_SCREENSHOT"))
                                else:
                                    console.save_svg(os.environ.get("OCTOPUS_SCREENSHOT"))
                                return

                            live.update(dashboard)
                            
                            # 2. Check for input (q to quit) non-blocking
                            # Wait for refresh interval, checking input frequently
                            # We break the sleep into small chunks to check for input
                            start_time = datetime.now()
                            while (datetime.now() - start_time).total_seconds() < refresh:
                                if select.select([sys.stdin], [], [], 0.0)[0]:
                                    ch = sys.stdin.read(1)
                                    if ch.lower() == 'q':
                                        stop_event.set()
                                        break
                                    elif ch.lower() == 'f':
                                        # Show loading state immediately
                                        live.update(build_loading_dashboard())
                                        await asyncio.sleep(0.1) # Brief pause to allow render
                                        
                                        # Flush cache
                                        CacheManager().clear()
                                        
                                        # Force quicker refresh
                                        break
                                await asyncio.sleep(0.1)

                        except KeyboardInterrupt:
                            break
                        except Exception as e:
                            with open("error.log", "a") as f:
                                f.write(f"{datetime.now()}: Layout Error: {e}\n")
                            console.print(f"[red]Error: {e}[/]")
                            # Sleep in chunks to allowing quitting
                            err_start = datetime.now()
                            while (datetime.now() - err_start).total_seconds() < 5:
                                if select.select([sys.stdin], [], [], 0.0)[0]:
                                     ch = sys.stdin.read(1)
                                     if ch.lower() == 'q':
                                         stop_event.set()
                                         break
                                await asyncio.sleep(0.1)

    try:
        run_async(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard closed[/]")


def main():
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
