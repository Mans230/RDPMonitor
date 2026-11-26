# -*- coding: utf-8 -*-
# For the interface: Summon telegram_mgr.wait_pending_uploads() before termination --now
# (put --now It was exiting before the upload was completed because the transmission fire-and-forget —
#  The function waits for all... Futures Pending until the file actually arrives).
"""Telegram integration via Pyrogram (pyrofork) — True parallel upload with multiple connections.

Why? Pyrogram?
Telegram determines the speed of each connection individually (~3 Mbps). Pyrogram It opens several connections
Separate (workers) One file is uploaded into parallel parts — The speed
It is multiplied by the number of connections, and the file is delivered to the client in one piece without any manual merging.

Bot messages sent to the customer in English only (User decision) — Do not translate.

Usage experience:
    /menu           ← List of buttons (Copy now / Status / List / Resend / Help)
    /backup /status /list /resend /help ← Same commands textually
    While lifting: A single status message is updated in place (Live progress bar) Allowance
    Send a new message at every step.

Bot commands:
    /backup   → Instant backup
    /status   → Latest Backup Status + Last login
    /list     → Copies available locally and on the cloud
    /resend   → Resend the last local copy
    /help     → Help
"""

import os
import time
import asyncio
import threading

from logger_utils import log, read_recent_logs
from i18n import tr

MAX_WORKERS = 8  # Number of connections connected to Telegram

MENU_TEXT = "**Backup bot** — pick an action:"
PROGRESS_BAR_LEN = 20


def _bar(percent):
    filled = max(0, min(PROGRESS_BAR_LEN, int(PROGRESS_BAR_LEN * percent / 100)))
    return "█" * filled + "░" * (PROGRESS_BAR_LEN - filled)


class TelegramManager:
    def __init__(self, cfg, job_runner=None, session_name="bot_session_pyro", temp_session=False):
        self.cfg = cfg
        self.job_runner = job_runner  # Full back-up function (Injected from main)
        self.session_name = session_name
        self.temp_session = temp_session  # Temporary connection to a window that does not have a bot — Cloud reports are written to the log only
        self.client = None
        self.loop = None
        self.thread = None
        self._running = False
        self.active_uploads = 0  # Number of current lifts — To prevent the tool from locking during lifting
        self._pending = set()           # Futures Outstanding (Messages + Lifts) — To keep track of what is not completed
        self._pending_lock = threading.Lock()
        self._ready = threading.Event()  # Set after the bot has actually connected
        try:
            import scheduler
            saved = scheduler.last_summary()
        except Exception:
            saved = ""
        self.last_backup_info = saved or "No backup has been run yet."
        # Live status messages, keyed per upload so concurrent uploads do not
        # overwrite each other's progress message.
        self._live_msgs = {}
        self._live_last = {}
        self._stop_event = None
        self.delivery_success = 0
        self.delivery_failures = 0

    # ---------- Setting ----------
    def is_configured(self):
        t = self.cfg.get("telegram", {})
        if not t.get("bot_enabled", True):
            # Retired: the unified monitor bot relays backup results instead.
            return False
        return bool(t.get("bot_token") and t.get("api_id") and t.get("api_hash") and t.get("chat_id"))

    def _chat(self):
        chat = str(self.cfg["telegram"]["chat_id"]).strip()
        return int(chat) if chat.lstrip("-").isdigit() else chat

    def wait_ready(self, timeout=60):
        """Waits for the bot to connect (So that startup messages are not lost)."""
        if not self._running:
            return False
        return self._ready.wait(timeout)

    def stop(self, timeout=30):
        """Stop the bot and close the session Pyrogram Cleanly (For example, a temporary browsing interface)."""
        self._running = False
        self._ready.clear()
        loop, thread = self.loop, self.thread
        try:
            if loop and self.client:
                asyncio.run_coroutine_threadsafe(self._stop_client(), loop).result(timeout)
        except Exception as e:
            log(f"Telegram client stop failed: {e}", "WARN")
        # Unblock _run_bot and stop the loop so the thread can exit and be joined.
        try:
            if loop and self._stop_event is not None:
                loop.call_soon_threadsafe(self._stop_event.set)
        except Exception:
            pass
        try:
            if loop:
                loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        if thread is not None:
            thread.join(timeout)
        self.client = None
        self.loop = None
        self.thread = None

    async def _stop_client(self):
        try:
            await self.client.stop()
        except Exception:
            pass

    def start(self):
        """Run the bot in a separate thread with Event Loop Special."""
        if not self.cfg.get("telegram", {}).get("bot_enabled", True):
            log("Telegram bot is retired (bot_enabled=false); the unified monitor bot reports instead.")
            return False
        if not self.is_configured():
            log(tr("core.tg.not_configured"), "WARN")
            return False
        try:
            import importlib.util
            if importlib.util.find_spec("pyrogram") is None:
                raise ImportError("pyrogram is not installed")
        except ImportError:
            log(tr("core.tg.no_pyrogram"), "ERROR")
            return False
        self._running = True
        self._stop_event = asyncio.Event()
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()
        return True

    def _thread_main(self):
        # Automatic restart loop — If the bot crashes for any reason, it will start working on its own
        while self._running:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._run_bot())
                break  # Natural exit
            except Exception as e:
                self._ready.clear()
                log(tr("core.tg.bot_error", err=e), "ERROR")
                time.sleep(60)

    async def _run_bot(self):
        from pyrogram import Client, filters
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        t = self.cfg["telegram"]
        session_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", self.session_name)
        app = Client(
            session_path,
            api_id=int(t["api_id"]),
            api_hash=t["api_hash"],
            bot_token=t["bot_token"],
            workers=MAX_WORKERS,
            max_concurrent_transmissions=MAX_WORKERS,
        )
        self.client = app
        allowed_chat = str(t["chat_id"]).strip()

        def _is_allowed(chat_id):
            return not allowed_chat or str(chat_id) == allowed_chat

        def _menu_markup():
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("Backup now", callback_data="menu_backup"),
                 InlineKeyboardButton("Status", callback_data="menu_status")],
                [InlineKeyboardButton("List backups", callback_data="menu_list"),
                 InlineKeyboardButton("Resend latest", callback_data="menu_resend")],
                [InlineKeyboardButton("Help", callback_data="menu_help")],
            ])

        # ---------- Commands (Text or from menu buttons) ----------
        async def _do_backup(message):
            if not _is_allowed(message.chat.id):
                return
            await message.reply("Running an on-demand backup... I will send you the result once it finishes.")
            if self.job_runner:
                threading.Thread(target=self.job_runner, kwargs={"manual": True}, daemon=True).start()

        async def _do_status(message):
            if not _is_allowed(message.chat.id):
                return
            tail = read_recent_logs(15)
            await message.reply(
                f"**Status:**\n{self.last_backup_info}\n\nRecent log:\n`{tail[-3500:]}`")

        async def _do_list(message):
            if not _is_allowed(message.chat.id):
                return
            import backup_engine, cloud_uploader
            if self.cfg["backup"].get("engine", "zip") == "restic":
                import restic_engine
                snaps = restic_engine.list_snapshots(self.cfg)
                await message.reply(("**Restic snapshots (latest 20):**\n" +
                                     ("\n".join(snaps) if snaps else "none"))[:4000])
                return
            local = backup_engine.list_local_backups()
            remote_map = cloud_uploader.list_remote_backups(self.cfg) if cloud_uploader.is_available() else {}
            msg = "**Local backups on this VPS:**\n" + ("\n".join(local) if local else "none")
            msg += "\n\n**Cloud backups:**\n"
            if remote_map:
                for remote, lines in remote_map.items():
                    msg += f"— {remote}\n" + ("\n".join(lines) if lines else "none") + "\n"
            else:
                msg += "none"
            await message.reply(msg[:4000])

        async def _do_resend(message):
            if not _is_allowed(message.chat.id):
                return
            import backup_engine
            if self.cfg["backup"].get("engine", "zip") == "restic":
                await message.reply("The restic engine keeps snapshots in its repository — "
                                    "there is no single file to resend. Use /list to see snapshots.")
                return
            local = backup_engine.list_local_backups()
            if not local:
                await message.reply("No local backup available to resend.")
                return
            path = os.path.join(backup_engine.BACKUP_DIR, local[0])
            await message.reply(f"Resending: {local[0]}")
            await self.send_file_async(path)

        async def _do_help(message):
            if not _is_allowed(message.chat.id):
                return
            await message.reply(
                "**Backup bot commands:**\n"
                "/menu — button menu\n"
                "/backup — run a backup now\n"
                "/status — last backup status\n"
                "/list — backups available locally and on the cloud\n"
                "/resend — resend the latest local backup\n"
                "/help — this help message")

        @app.on_message(filters.command(["menu", "start"]))
        async def _menu(_client, message):
            if not _is_allowed(message.chat.id):
                return
            m = await message.reply(MENU_TEXT, reply_markup=_menu_markup())
            try:
                await m.pin(disable_notification=True)  # The menu is always pinned to the top of the conversation
            except Exception:
                pass  # Some conversations do not allow the bot to install

        @app.on_message(filters.command("backup"))
        async def _backup(_client, message):
            await _do_backup(message)

        @app.on_message(filters.command("status"))
        async def _status(_client, message):
            await _do_status(message)

        @app.on_message(filters.command("list"))
        async def _list(_client, message):
            await _do_list(message)

        @app.on_message(filters.command("resend"))
        async def _resend(_client, message):
            await _do_resend(message)

        @app.on_message(filters.command("help"))
        async def _help(_client, message):
            await _do_help(message)

        @app.on_callback_query()
        async def _callbacks(_client, query):
            # Buttons apply the same permission rules (Registered chat only)
            chat_id = query.message.chat.id if query.message else None
            if not _is_allowed(chat_id):
                await query.answer("Not allowed.", show_alert=False)
                return
            await query.answer()
            route = {
                "menu_backup": _do_backup,
                "menu_status": _do_status,
                "menu_list": _do_list,
                "menu_resend": _do_resend,
                "menu_help": _do_help,
            }.get(query.data)
            if route:
                await route(query.message)

        await app.start()
        self._ready.set()
        log(tr("core.tg.bot_started", workers=MAX_WORKERS))
        # Stay alive until stop() sets the event (the outage is handled by the
        # external supervisor). A private event is used so the loop can be
        # stopped and the thread joined cleanly.
        if self._stop_event is not None:
            await self._stop_event.wait()
        else:
            await asyncio.Event().wait()

    # ---------- Transmission (Called from any thread) ----------
    def _submit(self, coro):
        if not self._running or not self.loop:
            return False
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        with self._pending_lock:
            self._pending.add(fut)

        def _done(f):
            with self._pending_lock:
                self._pending.discard(f)
            try:
                f.result()
            except BaseException as e:
                # Records any silent failure (Cancel due to tool lock / Connection interruption / Raising error)
                log(tr("core.tg.task_failed", err=f"{type(e).__name__}: {e}"), "ERROR")
        fut.add_done_callback(_done)
        return True

    def wait_pending_uploads(self, timeout=1800):
        """Waiting for all pending Telegram tasks to complete (Messages and uploads) Before going out.

        For the interface/Status --now: Call it before exiting the program so that it does not exit before the file arrives.
        You come back True If all tasks are completed, False When the deadline expires (timeout In seconds).
        """
        deadline = time.time() + max(0, timeout)
        while True:
            with self._pending_lock:
                pending = [f for f in self._pending if not f.done()]
            if not pending and self.active_uploads == 0:
                return True
            if time.time() >= deadline:
                log(tr("core.tg.wait_timeout"), "WARN")
                return False
            time.sleep(0.5)

    def send_message(self, text):
        """Send a text message to the customer."""
        if not self.cfg.get("telegram", {}).get("bot_enabled", True):
            return False  # retired: the unified monitor bot relays instead
        if not self.is_configured() or not self._running:
            log(tr("core.tg.not_ready_msg"), "WARN")
            return False
        return self._submit(self._send_message_async(text))

    async def _send_message_async(self, text):
        try:
            await self.client.send_message(self._chat(), text)
        except Exception as e:
            log(tr("core.tg.msg_failed", err=e), "ERROR")

    # ---------- Live status message ----------
    async def _live_status(self, text, force=False, slot=""):
        """Create or update a status message in place, keyed by slot.
        Limited to 5 Seconds between adjustments so as not to violate the limits of causes."""
        try:
            now = time.time()
            if not force and now - self._live_last.get(slot, 0) < 5:
                return
            msg_id = self._live_msgs.get(slot)
            if msg_id:
                await self.client.edit_message_text(self._chat(), msg_id, text)
            else:
                m = await self.client.send_message(self._chat(), text)
                self._live_msgs[slot] = m.id
            self._live_last[slot] = now
        except Exception as e:
            if "not modified" in str(e).lower():
                self._live_last[slot] = time.time()  # Same text — Nothing breaks
                return
            # The message has been deleted or the modification has been rejected — Start a new message at the next opportunity
            self._live_msgs.pop(slot, None)

    async def _finish_live_status(self, text, slot=""):
        """Close the live status message for a slot with a final status."""
        try:
            msg_id = self._live_msgs.get(slot)
            if msg_id:
                await self.client.edit_message_text(self._chat(), msg_id, text)
        except Exception:
            pass
        self._live_msgs.pop(slot, None)

    def send_file(self, path):
        """Send file (It splits automatically only if it is greater than 2 Giga)."""
        if not self.cfg.get("telegram", {}).get("bot_enabled", True):
            return False  # retired: the unified monitor bot relays instead
        if not self.is_configured() or not self._running:
            log(tr("core.tg.not_ready_file"), "WARN")
            return False
        return self._submit(self.send_file_async(path))

    async def send_file_async(self, path):
        import backup_engine
        backup_engine.mark_in_use(path)  # Protect the file from deletion while uploading
        self.active_uploads += 1
        try:
            chat = self._chat()
            size = os.path.getsize(path)
            size_mb = size / 1024 / 1024
            name = os.path.basename(path)

            _split_logged = set()

            def _split_progress(pct, _msg):
                # Brief recording of each 10% During partition + Update status message
                try:
                    mark = pct // 10 * 10
                    if mark and mark not in _split_logged and mark < 100:
                        _split_logged.add(mark)
                        log(tr("core.tg.split_progress", percent=pct))
                    if pct - getattr(_split_progress, "_last_live", 0) >= 10:
                        _split_progress._last_live = pct
                        # callback Works in thread pyrogram — Pass the edit to the bot loop
                        asyncio.run_coroutine_threadsafe(
                            self._live_status(f"Splitting {name}... {pct}% {_bar(pct)}",
                                              slot=path), self.loop)
                except Exception:
                    pass  # Display problems never cancel copies

            _split_progress._last_live = 0
            await self._live_status(f"Preparing {name} ({size_mb:.1f} MB)...", force=True, slot=path)
            # Run the blocking split in a worker thread so the bot loop stays
            # responsive; the progress callback hops back with run_coroutine_threadsafe.
            parts = await asyncio.to_thread(
                backup_engine.split_file, path, progress_cb=_split_progress)
            if not parts:
                log(tr("core.tg.split_aborted"), "WARN")
                await self._finish_live_status(f"Splitting {name} aborted.", slot=path)
                return

            for i, part in enumerate(parts, 1):
                pmb = os.path.getsize(part) / 1024 / 1024
                caption = f"{os.path.basename(part)} ({pmb:.1f} MB)"
                if len(parts) > 1:
                    caption += f" — part {i}/{len(parts)}"

                logged = set()

                def _progress(current, total, _logged=logged, _pname=os.path.basename(part)):
                    # callback Works in thread pyrogram — No exception is allowed here
                    try:
                        pct = int(current * 100 / total) if total else 0
                        mark = pct // 25 * 25
                        if mark and mark not in _logged and mark < 100:
                            _logged.add(mark)
                            log(tr("core.tg.upload_progress", name=_pname, percent=pct))
                        if pct - getattr(_progress, "_last_live", 0) >= 5 or pct >= 100:
                            _progress._last_live = pct
                            asyncio.run_coroutine_threadsafe(
                                self._live_status(
                                    f"Uploading {_pname} ({pmb:.1f} MB)\n"
                                    f"{pct}% {_bar(pct)}", slot=path), self.loop)
                    except Exception:
                        pass

                _progress._last_live = 0
                log(tr("core.tg.sending", name=os.path.basename(part),
                       size_mb=f"{pmb:.1f}", workers=MAX_WORKERS))
                await self.client.send_document(chat, part, caption=caption, progress=_progress)
                log(tr("core.tg.uploaded", name=os.path.basename(part), size_mb=f"{pmb:.1f}"))

            if len(parts) > 1:
                await self.client.send_message(
                    chat,
                    "The file is larger than 2 GB, so it was split into parts. "
                    "To merge them on Windows, run in CMD:\n"
                    f"`copy /b {name}.part* {name}`")
            backup_engine.cleanup_parts(path)
            await self._finish_live_status(f"{name} ({size_mb:.1f} MB) delivered to Telegram.", slot=path)
            self.delivery_success += 1
            log(tr("core.tg.send_ok"))
        except Exception as e:
            self.delivery_failures += 1
            await self._finish_live_status(f"Sending {os.path.basename(path)} failed: {e}", slot=path)
            log(tr("core.tg.send_failed", err=e), "ERROR")
        finally:
            self.active_uploads -= 1
            backup_engine.unmark_in_use(path)

    def reset_delivery(self):
        """Begin a fresh delivery-verification window for this run."""
        self.delivery_success = 0
        self.delivery_failures = 0

    def wait_delivery(self, timeout=3600):
        """Block until in-flight uploads finish; return (delivered, failed) for this run.

        If the deadline passes with uploads still pending, they are counted as
        failed so a queued-but-undelivered backup is never reported as delivered.
        """
        deadline = time.time() + max(0, timeout)
        while time.time() < deadline:
            with self._pending_lock:
                pending = [f for f in self._pending if not f.done()]
            if self.active_uploads == 0 and not pending:
                break
            time.sleep(2)
        with self._pending_lock:
            pending = [f for f in self._pending if not f.done()]
        if self.active_uploads > 0 or pending:
            self.delivery_failures += max(1, len(pending) + self.active_uploads)
        return self.delivery_success, self.delivery_failures
