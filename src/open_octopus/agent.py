#!/usr/bin/env python3
"""Gemini Agent SDK integration for natural language energy queries.

Ask questions about your Octopus Energy account in plain English:
- "What's my current energy usage?"
- "When is my next charging window?"
- "How much did I use yesterday?"
- "Am I on off-peak rates right now?"

Usage:
    octopus-ask "What's my current power draw?"

Or as a library:
    from open_octopus.agent import OctopusAgent

    agent = OctopusAgent()
    response = await agent.ask("What's my balance?")
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Optional, Any

from google import genai
from google.genai import types

from .client import OctopusClient
from .models import Account, Tariff, Rate, DispatchStatus, LivePower, SavingSession


class OctopusAgent:
    """Gemini-powered agent for natural language energy queries."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        account: Optional[str] = None,
        mpan: Optional[str] = None,
        meter_serial: Optional[str] = None,
        gas_mprn: Optional[str] = None,
        gas_meter_serial: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash"
    ):
        """
        Initialize the Octopus Agent.

        Args:
            api_key: Octopus API key (or OCTOPUS_API_KEY env var)
            account: Account number (or OCTOPUS_ACCOUNT env var)
            mpan: MPAN (or OCTOPUS_MPAN env var)
            meter_serial: Meter serial (or OCTOPUS_METER_SERIAL env var)
            gas_mprn: Gas MPRN (or OCTOPUS_GAS_MPRN env var)
            gas_meter_serial: Gas meter serial (or OCTOPUS_GAS_METER_SERIAL env var)
            gemini_api_key: Google AI Studio API key (or GEMINI_API_KEY env var)
            model_name: Gemini model to use (default: gemini-1.5-flash)
        """
        self.octopus = OctopusClient(
            api_key=api_key or os.environ.get("OCTOPUS_API_KEY", ""),
            account=account or os.environ.get("OCTOPUS_ACCOUNT", ""),
            mpan=mpan or os.environ.get("OCTOPUS_MPAN"),
            meter_serial=meter_serial or os.environ.get("OCTOPUS_METER_SERIAL"),
            gas_mprn=gas_mprn or os.environ.get("OCTOPUS_GAS_MPRN"),
            gas_meter_serial=gas_meter_serial or os.environ.get("OCTOPUS_GAS_METER_SERIAL")
        )

        key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            print("\n❌ Error: Missing Google Gemini API Key.")
            print("Please set your key in the .env file or environment variables:")
            print('export GEMINI_API_KEY="AIzaSy...your-actual-key-here"\n')
            print("Get a free key here: https://aistudio.google.com/app/apikey")
            sys.exit(1)

        self.client = genai.Client(api_key=key)
        self.model_name = model_name

        # --- Define Tools for Gemini ---
        self.tools = [
            self._get_account_info,
            self._get_current_rate,
            self._get_live_power,
            self._get_charging_status,
            self._get_daily_usage,
            self._get_saving_sessions,
            self._get_tariff_info,
            self._get_gas_usage,
            self._get_gas_tariff,
        ]

    # --- Tool Implementations (Private) ---

    async def _execute_tool(self, name: str, args: dict) -> dict:
        """Execute a tool dynamically."""
        async with self.octopus:
            if name == "_get_account_info":
                return await self._impl_get_account_info()
            elif name == "_get_current_rate":
                return await self._impl_get_current_rate()
            elif name == "_get_live_power":
                return await self._impl_get_live_power()
            elif name == "_get_charging_status":
                return await self._impl_get_charging_status()
            elif name == "_get_daily_usage":
                return await self._impl_get_daily_usage(args.get("days", 7))
            elif name == "_get_saving_sessions":
                return await self._impl_get_saving_sessions()
            elif name == "_get_tariff_info":
                return await self._impl_get_tariff_info()
            elif name == "_get_gas_usage":
                return await self._impl_get_gas_usage(args.get("days", 7))
            elif name == "_get_gas_tariff":
                return await self._impl_get_gas_tariff()
            else:
                return {"error": f"Unknown tool: {name}"}

    async def _impl_get_account_info(self):
        account = await self.octopus.get_account()
        return {
            "balance": account.balance,
            "balance_status": "credit" if account.balance > 0 else "debit",
            "name": account.name,
            "status": account.status,
            "address": account.address
        }

    async def _impl_get_current_rate(self):
        tariff = await self.octopus.get_tariff()
        if not tariff: return {"error": "Could not fetch tariff information"}
        rate = self.octopus.get_current_rate(tariff)
        now = datetime.now()
        time_left = rate.period_end - now
        hours = int(time_left.total_seconds()) // 3600
        mins = (int(time_left.total_seconds()) % 3600) // 60
        return {
            "current_rate_pence": rate.rate,
            "is_off_peak": rate.is_off_peak,
            "rate_type": "off-peak" if rate.is_off_peak else "peak",
            "changes_in": f"{hours}h {mins}m",
            "changes_at": rate.period_end.strftime("%H:%M"),
            "next_rate_pence": rate.next_rate
        }

    async def _impl_get_live_power(self):
        power = await self.octopus.get_live_power()
        if not power: return {"error": "Live power data unavailable. Requires Home Mini device."}
        tariff = await self.octopus.get_tariff()
        rate = self.octopus.get_current_rate(tariff) if tariff else None
        cost_per_hour = (power.demand_watts / 1000 * rate.rate) if rate else 0
        return {
            "demand_watts": power.demand_watts,
            "demand_kw": power.demand_watts / 1000,
            "read_at": power.read_at.isoformat(),
            "cost_per_hour_pence": round(cost_per_hour, 1)
        }

    async def _impl_get_charging_status(self):
        status = await self.octopus.get_dispatch_status()
        result = {"is_charging": status.is_dispatching}
        if status.is_dispatching and status.current_dispatch:
            result["charging_ends"] = status.current_dispatch.end.strftime("%H:%M")
        if status.next_dispatch:
            result["next_charge_start"] = status.next_dispatch.start.strftime("%H:%M")
            result["next_charge_end"] = status.next_dispatch.end.strftime("%H:%M")
            result["next_charge_duration_mins"] = status.next_dispatch.duration_minutes
        else:
            result["next_charge"] = None
        return result

    async def _impl_get_daily_usage(self, days: int):
        daily = await self.octopus.get_daily_usage(days=days)
        return {
            "usage_by_day": {date: round(kwh, 2) for date, kwh in sorted(daily.items(), reverse=True)},
            "total_kwh": round(sum(daily.values()), 2),
            "average_kwh": round(sum(daily.values()) / len(daily), 2) if daily else 0
        }

    async def _impl_get_saving_sessions(self):
        sessions = await self.octopus.get_saving_sessions()
        return {
            "sessions": [{
                "start": s.start.strftime("%Y-%m-%d %H:%M"),
                "end": s.end.strftime("%H:%M"),
                "is_active": s.is_active,
                "is_upcoming": s.is_upcoming,
                "reward_per_kwh": s.reward_per_kwh
            } for s in sessions],
            "count": len(sessions),
            "has_active": any(s.is_active for s in sessions)
        }

    async def _impl_get_tariff_info(self):
        tariff = await self.octopus.get_tariff()
        if not tariff: return {"error": "Could not fetch electricity tariff information"}
        return {
            "fuel_type": "electricity",
            "name": tariff.name,
            "product_code": tariff.product_code,
            "standing_charge_pence": tariff.standing_charge,
            "off_peak_rate_pence": tariff.off_peak_rate,
            "peak_rate_pence": tariff.peak_rate,
            "off_peak_hours": f"{tariff.off_peak_start} - {tariff.off_peak_end}"
        }

    async def _impl_get_gas_usage(self, days: int):
        if not self.octopus.gas_mprn: return {"error": "Gas meter not configured."}
        daily = await self.octopus.get_daily_gas_usage(days=days)
        return {
            "fuel_type": "gas",
            "usage_by_day": {date: round(kwh, 2) for date, kwh in sorted(daily.items(), reverse=True)},
            "total_kwh": round(sum(daily.values()), 2),
            "average_kwh": round(sum(daily.values()) / len(daily), 2) if daily else 0
        }

    async def _impl_get_gas_tariff(self):
        if not self.octopus.gas_mprn: return {"error": "Gas meter not configured."}
        tariff = await self.octopus.get_gas_tariff()
        if not tariff: return {"error": "Could not fetch gas tariff information"}
        return {
            "fuel_type": "gas",
            "name": tariff.name,
            "product_code": tariff.product_code,
            "standing_charge_pence": tariff.standing_charge,
            "unit_rate_pence": tariff.unit_rate
        }

    # --- Tool Declarations (for Gemini Schema) ---
    # These methods are critical! They provide the function definitions (names, docstrings, args)
    # that the Gemini SDK uses to generate the JSON schema for the model.
    # The actual implementation logic is in the `_impl_*` methods above.
    # DO NOT DELETE or rename these unless you update the schema accordingly.

    def _get_account_info(self):
        """Get Octopus Energy account information including balance, billing name, and status"""
        pass

    def _get_current_rate(self):
        """Get the current electricity rate, whether it's off-peak or peak, and when it changes"""
        pass
    
    def _get_live_power(self):
        """Get real-time power consumption from the Home Mini device in watts and calculated cost per hour"""
        pass

    def _get_charging_status(self):
        """Get Intelligent Octopus charging status - whether currently charging and when the next scheduled charge is"""
        pass

    def _get_daily_usage(self, days: int = 7):
        """Get electricity usage for recent days in kWh.
        
        Args:
            days: Number of days to get usage for (default 7)
        """
        pass

    def _get_saving_sessions(self):
        """Get upcoming Saving Sessions (free electricity events)"""
        pass

    def _get_tariff_info(self):
        """Get electricity tariff details including name, standing charge, and unit rates"""
        pass

    def _get_gas_usage(self, days: int = 7):
        """Get gas consumption for recent days in kWh.
        
        Args:
            days: Number of days to get gas usage for (default 7)
        """
        pass

    def _get_gas_tariff(self):
        """Get gas tariff details including name, standing charge, and unit rate"""
        pass


    async def ask(self, question: str) -> str:
        """Ask a natural language question about your energy data."""
        
        SYSTEM_INSTRUCTION = """You are an expert assistant for Octopus Energy customers in the UK.
Key context:
- Intelligent Octopus Go: cheap rates 23:30-05:30 (6 hrs).
- Home Mini: provides real-time power data.
- Balance: positive = credit, negative = debit.
- Convert pence to pounds (e.g. 500p -> £5.00).
- Be concise. Use tools to fetch real data.
- ALWAYS use the `_get_daily_usage` tool to fetch data before answering questions about usage.
"""

        chat = self.client.aio.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                tools=self.tools,
                system_instruction=SYSTEM_INSTRUCTION,
                automatic_function_calling={"disable": True}
            )
        )
        
        # 1. Send user message
        response = await chat.send_message(question)
        
        # 2. Handle function calls loop
        while True:
            function_calls = []
            if response.parts:
                for part in response.parts:
                    if part.function_call:
                        function_calls.append(part.function_call)
            
            if not function_calls:
                return response.text or "No text response."
            
            responses_parts = []
            for call in function_calls:
                name = call.name
                # Gemini args are dict-like in new SDK
                args = call.args
                
                # Execute tool
                tool_result = await self._execute_tool(name, args)
                
                # Create response part
                responses_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": tool_result}
                    )
                )
            
            # Send results back to model
            response = await chat.send_message(responses_parts)


async def ask(question: str) -> str:
    """Convenience function to ask a question."""
    agent = OctopusAgent()
    return await agent.ask(question)


def main():
    """CLI entry point for octopus-ask."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: octopus-ask \"Your question about energy\"")
        print("\nExamples:")
        print('  octopus-ask "What\'s my current power usage?"')
        print('  octopus-ask "When is my next charging window?"')
        print('  octopus-ask "How much did I use yesterday?"')
        sys.exit(0)

    question = " ".join(sys.argv[1:])

    try:
        response = asyncio.run(ask(question))
        print(response)
    except Exception as e:
        error_str = str(e)
        if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
            print("\n❌ Rate Limit Exceeded (429)")
            print("You have exceeded the free tier quota for the Gemini API.")
            print("Please wait a few moments before trying again.")
            sys.exit(1)

        print(f"\n❌ Prediction Error: {e}")
        if "API Key" in error_str or "400" in error_str or "403" in error_str:
             print("Check your GEMINI_API_KEY environment variable.")
             print("Get a key: https://aistudio.google.com/app/apikey")
        sys.exit(1)


if __name__ == "__main__":
    main()
