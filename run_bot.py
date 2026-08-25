import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

from app.bot.telegram_bot import get_bot_app
from app.db.session import init_db


async def main():
    print("=================================================================")
    print("🚀 Starting Autonomous Business Analytics Telegram Bot (@Analyst131Bot)...")
    print("=================================================================")
    await init_db()
    app = get_bot_app()
    if not app:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    print("✅ Bot is online and listening for messages and uploaded files!")
    print("👉 Open Telegram and chat with @Analyst131Bot")
    print("Press Ctrl+C to stop.\n")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Keep running until interrupted
    stop_signal = asyncio.Event()
    try:
        await stop_signal.wait()
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        print("\nStopping bot gracefully...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        print("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
