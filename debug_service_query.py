#!/usr/bin/env python3
"""
Debug script to test the service query that's failing in the API
"""

import asyncio
import asyncpg
import os
from datetime import date

async def test_service_query():
    # Database connection (same as used in API)
    database_url = "postgresql://cost_monitor_user:cZU8ZP2xBHeIwiNp5Sop%2FXrF3C3XJ2OBagoz1y2wrK4%3D@postgresql:5432/cost_monitor"

    try:
        # Connect to database
        conn = await asyncpg.connect(database_url)
        print("✅ Connected to database")

        # Test parameters (same as API call)
        start_date = date(2026, 1, 19)
        end_date = date(2026, 1, 20)
        providers = ['aws', 'azure', 'gcp']

        print(f"📅 Date range: {start_date} to {end_date}")
        print(f"🔍 Providers: {providers}")

        # Build service query (exactly like the API)
        service_query = """
            SELECT p.name as provider, cdp.service_name, SUM(cdp.cost) as cost, cdp.currency
            FROM cost_data_points cdp
            JOIN providers p ON cdp.provider_id = p.id
            WHERE cdp.date BETWEEN $1 AND $2
        """

        service_params = [start_date, end_date]

        if providers:
            service_query += " AND p.name = ANY($3)"
            service_params.append(providers if isinstance(providers, list) else [providers])

        service_query += " GROUP BY p.name, cdp.service_name, cdp.currency ORDER BY p.name, cost DESC"

        print(f"\n🔍 Service Query:")
        print(service_query)
        print(f"\n📊 Service Params: {service_params}")
        print(f"📊 Params types: {[type(p) for p in service_params]}")

        # Execute the query
        print(f"\n⚡ Executing service query...")
        service_rows = await conn.fetch(service_query, *service_params)

        print(f"✅ Service query returned {len(service_rows)} rows")

        if service_rows:
            print(f"\n📋 First 10 service rows:")
            for i, row in enumerate(service_rows[:10]):
                print(f"  {i+1}. {row['provider']} | {row['service_name']} | ${row['cost']:.2f} | {row['currency']}")
        else:
            print(f"\n❌ No service rows returned!")

            # Let's test without the providers filter
            print(f"\n🔍 Testing query without providers filter...")
            test_query = """
                SELECT p.name as provider, cdp.service_name, SUM(cdp.cost) as cost, cdp.currency
                FROM cost_data_points cdp
                JOIN providers p ON cdp.provider_id = p.id
                WHERE cdp.date BETWEEN $1 AND $2
                GROUP BY p.name, cdp.service_name, cdp.currency ORDER BY p.name, cost DESC
                LIMIT 5
            """
            test_rows = await conn.fetch(test_query, start_date, end_date)
            print(f"✅ Query without filter returned {len(test_rows)} rows")
            for row in test_rows:
                print(f"  {row['provider']} | {row['service_name']} | ${row['cost']:.2f}")

        # Test the providers array specifically
        print(f"\n🔍 Testing ANY clause with providers array...")
        test_any_query = """
            SELECT p.name as provider, COUNT(*) as count
            FROM cost_data_points cdp
            JOIN providers p ON cdp.provider_id = p.id
            WHERE cdp.date BETWEEN $1 AND $2 AND p.name = ANY($3)
            GROUP BY p.name
        """
        any_rows = await conn.fetch(test_any_query, start_date, end_date, providers)
        print(f"✅ ANY clause test returned {len(any_rows)} rows")
        for row in any_rows:
            print(f"  {row['provider']}: {row['count']} records")

        await conn.close()
        print(f"\n✅ Database connection closed")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_service_query())