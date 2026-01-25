"""
Main entry point for the Cost Monitor Dashboard when run as a module.
Usage: python -m src.visualization.dashboard
"""

import asyncio
import os
import sys
import traceback

# Add the project root to Python path to ensure imports work
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def main_entry():
    """Main entry point for the dashboard."""
    try:
        # Import after path setup to avoid import issues
        from src.visualization.dashboard import main

        # Run the async main function
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to start dashboard: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main_entry()
