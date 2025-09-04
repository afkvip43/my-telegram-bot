import logging
import random
import datetime
import asyncio
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ====== CẤU HÌNH (THAY TOKEN & ADMINS) ======
TOKEN = "8425555736:AAFMu78_-x_sIKzyDeZu3V1di1W4UESqwvg"
ADMINS = {6251713157}  # <-- thay bằng Telegram user ID admin (có thể nhiều IDs)
ADMIN_TELEGRAM_LINK = "https://t.me/frog024" # Thay @frog024 bằng username của bạn

# Ảnh menu chính (banner)
MENU_PHOTO = "https://i.postimg.cc/Y90NyGD7/photo-2025-08-30-10-13-55.jpg"

# Thông tin thanh toán
PAYMENT_INFO_TEXT = (
    "💳 THÔNG TIN THANH TOÁN\n\n"
    "• MoMo: 0862425144 (QUANG VAN TRUONG)\n"
    "• MB Bank: 08624251 (QUANG VAN TRUONG))\n\n"
    "👉 Vui lòng ghi đúng MÃ GD đã cho vào phần nỗi dung chuyển khoản trước khi chuyển tiền ."
    "lưu ý nếu ghi sai mã GD hoặc nhầm lẫn hãy liên hệ admin ngay!"
    "sau 30p kể từ lúc bạn sãy ra nhầm lẫn trong hay ghi sai mã admin sẽ không hộ trợ được."
    "nếu có thắc mắc gì liên hệ admin để được hộ trợ."
)

# Danh sách gói (mã => label)
PACKAGES = {
    "15p": "15 phút – 199k",
    "30p": "30 phút – 399k",
    "1h": "1 giờ – 799K",
    "3h": "3 giờ – 1TR444K",
    "8h": "Nguyên đêm (8h) – 1TR999K",
}

# Thời lượng từng gói (giây)
PACKAGE_SECONDS = {
    "15p": 15 * 60,
    "30p": 30 * 60,
    "1h": 60 * 60,
    "3h": 3 * 60 * 60,
    "8h": 8 * 60 * 60,
}

# Danh sách người (key => dữ liệu)
PEOPLE = {
    "ngocnhi": {
        "name": "🔞🔞🥵YUMI call show cực múp🥵🔞🔞",
        "desc": "🔞🔞thân thiện - lồn múp còn hồng - nói chuyện vui tính - hiểu ý🔞🔞",
        "photo": "https://i.postimg.cc/pVB0mmrB/YUMI.jpg",
        "contact": "tele : @TieuKhaAi2005"
    },
    "anhnguyet": {
        "name": "chưa có ",
        "desc": "chưa có",
        "photo": MENU_PHOTO,
        "contact": "chưa có"
    },
    "minhhuyen": {
        "name": "chưa có ",
        "desc": "chưa có",
        "photo": MENU_PHOTO,
        "contact": "chưa có"
    },
    "caothi": {
        "name": "chưa có",
        "desc": "chưa có",
        "photo": MENU_PHOTO,
        "contact": "chưa có"
    },
    "ngocanh": {
        "name": "chưa có",
        "desc": "chưa có.",
        "photo": MENU_PHOTO,
        "contact": "chưa có"
    },
}

# ORDERS: lưu các đơn tạm, chờ user xác nhận thanh toán
ORDERS: Dict[str, Dict[str, Any]] = {}

# TRANSACTION_HISTORY: lưu các đơn đã được admin duyệt/từ chối
TRANSACTION_HISTORY: Dict[str, Dict[str, Any]] = {}

# SESSIONS tạm user_id -> {package, person, tx}
SESSIONS: Dict[int, Dict[str, Any]] = {}

# ACTIVE_COUNTDOWNS: tx -> {user_id, msg_id, ends_at_ts, contact_text, task}
ACTIVE_COUNTDOWNS: Dict[str, Dict[str, Any]] = {}

# ====== Anti-spam ======
# Lưu timestamps các action của user để giới hạn tốc độ
USER_ACTIONS: Dict[int, list] = {}
# Strike counts, block_until timestamp
USER_STRIKES: Dict[int, Dict[str, Any]] = {}
SPAM_WINDOW = 60  # seconds window
SPAM_MAX_ACTIONS = 12  # max callback presses per window
STRIKE_LIMIT = 3  # sau 3 lần vi phạm -> block 10 min
BLOCK_SECONDS = 10 * 60

# ====== Logging ======
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Helpers ======
def gen_transaction_id() -> str:
    return "GD" + str(random.randint(100000, 999999))

def is_person_busy(person_key: str) -> bool:
    """Kiểm tra xem một người có đang có phiên hoạt động không."""
    for session in ACTIVE_COUNTDOWNS.values():
        if session.get("person") == person_key:
            return True
    return False

def kb_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔞🔞thuê người call sex🌚 / trò chuyện về đêm🌚 🔞🔞", callback_data="menu|packages")],
        # Đã thay đổi thành callback_data để có thể kiểm soát trạng thái cấm
        [InlineKeyboardButton("💌 Liên hệ Admin", callback_data="menu|contact_admin")]
    ])

def kb_packages():
    rows = [[InlineKeyboardButton(label, callback_data=f"packages|{code}")] for code, label in PACKAGES.items()]
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="back|main")])
    return InlineKeyboardMarkup(rows)

def kb_people(package_code: str):
    rows = []
    for k, v in PEOPLE.items():
        person_name = v["name"]
        if is_person_busy(k):
            label = f"🚫 {person_name} (Đang bận)"
            rows.append([InlineKeyboardButton(label, callback_data="disabled")])
        else:
            label = person_name
            rows.append([InlineKeyboardButton(label, callback_data=f"people|{package_code}|{k}")])
    rows.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="back|packages")])
    return InlineKeyboardMarkup(rows)

def kb_person_detail(package_code: str, person_key: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💖 Thuê bé này", callback_data=f"hire|{package_code}|{person_key}")],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data=f"back|people|{package_code}")]
    ])

def kb_payment(package_code: str, person_key: str, tx: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 ĐÃ XÁC NHẬN THANH TOÁN", callback_data=f"userconfirm|{tx}")],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data=f"back|person|{package_code}|{person_key}")]
    ])

def kb_admin_for_tx(tx: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Thành công", callback_data=f"admin|ok|{tx}"),
            InlineKeyboardButton("❌ Thất bại", callback_data=f"admin|fail|{tx}")
        ]
    ])

def format_hms(seconds: int) -> str:
    hrs, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hrs:
        return f"{hrs:d}h {mins:02d}m {secs:02d}s"
    return f"{mins:d}m {secs:02d}s"

# ====== Anti-spam utilities ======
def is_user_blocked(user_id: int) -> tuple[bool, int]:
    
    rec = USER_STRIKES.get(user_id)
    if not rec:
        return False, 0
    until = rec.get("blocked_until", 0)
    if until and datetime.datetime.utcnow().timestamp() < until:
        return True, int(until - datetime.datetime.utcnow().timestamp())
    return False, 0

def record_user_action(user_id: int):
    now = datetime.datetime.utcnow().timestamp()
    arr = USER_ACTIONS.setdefault(user_id, [])
    # remove old
    cutoff = now - SPAM_WINDOW
    while arr and arr[0] < cutoff:
        arr.pop(0)
    arr.append(now)
    USER_ACTIONS[user_id] = arr
    # check violation
    if len(arr) > SPAM_MAX_ACTIONS:
        # increment strike
        rec = USER_STRIKES.setdefault(user_id, {"strikes": 0, "blocked_until": 0})
        rec["strikes"] += 1
        if rec["strikes"] >= STRIKE_LIMIT:
            rec["blocked_until"] = now + BLOCK_SECONDS
            rec["strikes"] = 0  # reset strikes after block
        USER_STRIKES[user_id] = rec
        return True, rec
    return False, USER_STRIKES.get(user_id, {"strikes": 0, "blocked_until": 0})

# ====== Countdown task ======
async def countdown_and_expire(context: ContextTypes.DEFAULT_TYPE, tx: str):
    """Cập nhật thời gian còn lại và thu hồi khi hết"""
    session = ACTIVE_COUNTDOWNS.get(tx)
    if not session:
        return
    user_id = session["user_id"]
    msg_id = session["msg_id"]
    ends_at = session["ends_at"]  # timestamp
    contact_text = session.get("contact_text", "")
    update_interval = 15  # seconds

    while True:
        now = datetime.datetime.utcnow().timestamp()
        remaining = int(ends_at - now)
        if remaining <= 0:
            # delete message with contact if exists
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass
            try:
                await context.bot.send_message(chat_id=user_id, text="⏰ Thời gian thuê đã hết, thông tin liên lạc đã bị thu hồi. Cảm ơn bạn !")
            except Exception:
                pass
            ACTIVE_COUNTDOWNS.pop(tx, None)
            return

        # edit message to show remaining
        try:
            new_text = f"{contact_text}\n\n⏳ Thời gian còn lại: {format_hms(remaining)}"
            await context.bot.edit_message_text(chat_id=user_id, message_id=msg_id, text=new_text, parse_mode="Markdown")
        except Exception:
            # user may have deleted it; ignore
            pass

        await asyncio.sleep(update_interval)

# ====== Handlers ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info("User %s started bot", user.id)
    if update.message:
        try:
            await update.message.reply_photo(
                photo=MENU_PHOTO,
                caption="🌸 *🔞MENU dịch vụ call sex🌚* 🌸\n\n🔞🌚chọn người nói chuyện ban đêm cung nào🌚🔞:",
                reply_markup=kb_main_menu(),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning("Không gửi được ảnh menu: %s", e)
            await update.message.reply_text("🌸 *🔞MENU dịch vụ call sex 🔞* 🌸\n\n 🔞🌚chọn người nói chuyện ban đêm cung nào🌚🔞 :", reply_markup=kb_main_menu())

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    
    # Check for contact admin button first to bypass ban
    if query.data == "menu|contact_admin":
        await query.answer("Vui lòng liên hệ Admin qua Telegram.", show_alert=True)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Bạn có thể liên hệ admin tại đây: {ADMIN_TELEGRAM_LINK}\n\n"
                 "Nếu bạn đang bị cấm tạm thời, vui lòng đợi hết thời gian cấm hoặc liên hệ admin để được hỗ trợ."
        )
        return
        
    # Anti-spam pre-check for all other buttons
    blocked, secs_left = is_user_blocked(user_id)
    if blocked:
        await query.answer(f"Bạn bị chặn tạm thời do spam. Thử lại sau {secs_left}s.", show_alert=True)
        return

    # Handle disabled button click
    if query.data == "disabled":
        await query.answer("bé này hiện đang có khách , vui lòng chọn bé khác hoặc quay lại .", show_alert=True)
        return

    await query.answer()
    
    # Record action & check violation
    violated, rec = record_user_action(user_id)
    if violated:
        # give warning or block info
        if rec.get("blocked_until", 0) and rec["blocked_until"] > datetime.datetime.utcnow().timestamp():
            await query.answer("Bạn đã bị chặn tạm do spam (tự động).", show_alert=True)
            return
        else:
            await query.answer("Hành động quá nhanh — bạn đã bị cảnh cáo. Giảm tốc đi bạn nhé!", show_alert=True)
            # continue but warn

    data = query.data
    parts = data.split("|")
    action = parts[0]

    # MENU -> packages
    if action == "menu" and len(parts) > 1 and parts[1] == "packages":
        try:
            await query.edit_message_caption(caption=" *🔞Danh sách gói thuê theo giờ 🔞*:", reply_markup=kb_packages(), parse_mode="Markdown")
        except Exception:
            await query.edit_message_text(text=" *🔞 Danh sách gói thuê theo giờ🔞*:", reply_markup=kb_packages())

    # package selected -> show people
    elif action == "packages" and len(parts) == 2:
        pkg_code = parts[1]
        SESSIONS[query.from_user.id] = {"package": pkg_code}
        text = f"⏳ *Bạn đã chọn gói:* {PACKAGES.get(pkg_code, pkg_code)}\n\nChọn người bạn muốn thuê:"
        try:
            await query.edit_message_caption(caption=text, reply_markup=kb_people(pkg_code), parse_mode="Markdown")
        except Exception:
            await query.edit_message_text(text=text, reply_markup=kb_people(pkg_code), parse_mode="Markdown")

    # person selected -> show photo + detail
    elif action == "people" and len(parts) == 3:
        pkg_code = parts[1]
        person_key = parts[2]
        person = PEOPLE.get(person_key)
        if not person:
            await query.edit_message_text("⚠️ Người không tồn tại.")
            return
        SESSIONS[query.from_user.id] = {"package": pkg_code, "person": person_key}
        try:
            await query.message.delete()
        except Exception:
            pass
        caption = f"👤 *{person['name']}*\n\n{person['desc']}\n\n⏳ *Gói:* {PACKAGES.get(pkg_code)}"
        await context.bot.send_photo(chat_id=query.from_user.id, photo=person["photo"], caption=caption,
                                     reply_markup=kb_person_detail(pkg_code, person_key), parse_mode="Markdown")

    # hire -> create tx + payment instructions
    elif action == "hire" and len(parts) == 3:
        pkg_code = parts[1]; person_key = parts[2]; user = query.from_user
        tx = gen_transaction_id()
        ORDERS[tx] = {
            "user_id": user.id,
            "username": user.username or user.full_name,
            "package": pkg_code,
            "person": person_key,
            "created_at": datetime.datetime.now().isoformat()
        }
        SESSIONS[user.id] = {"package": pkg_code, "person": person_key, "tx": tx}
        payment_msg = (
            f"💳 *THANH TOÁN*\n\n"
            f"Bạn đang thuê *{PEOPLE[person_key]['name']}* — {PACKAGES[pkg_code]}\n\n"
            f"🔑 *Mã giao dịch*: `{tx}`\n\n"
            f"{PAYMENT_INFO_TEXT}\n\n"
            "➡️ Sau khi chuyển tiền, bấm **📩 ĐÃ XÁC NHẬN THANH TOÁN**. Admin sẽ kiểm tra và xác nhận.\n"
            "Khi admin xác nhận *Thành công*, bot sẽ gửi thông tin và bắt đầu đếm thời gian."
        )
        try:
            await query.edit_message_text(text=payment_msg, parse_mode="Markdown", reply_markup=kb_payment(pkg_code, person_key, tx))
        except Exception:
            await context.bot.send_message(chat_id=user.id, text=payment_msg, parse_mode="Markdown", reply_markup=kb_payment(pkg_code, person_key, tx))

    # user confirms payment -> notify admins
    elif action == "userconfirm" and len(parts) == 2:
        tx = parts[1]
        order = ORDERS.get(tx)
        if not order:
            await query.answer("⚠️ Mã giao dịch không tồn tại hoặc đã bị xóa.", show_alert=True)
            return
        try:
            await query.edit_message_text("⏳ Vui lòng chờ admin kiểm tra và xác nhận thanh toán. Bạn sẽ được thông báo khi admin duyệt.")
        except Exception:
            await context.bot.send_message(chat_id=query.from_user.id, text="⏳ Vui lòng chờ admin kiểm tra và xác nhận thanh toán.")
        
        # GỬI THÔNG BÁO TỚI ADMIN CHỈ SAU KHI USER XÁC NHẬN
        admin_notice_user_confirm = (
            f"📢 *ĐƠN HÀNG ĐÃ XÁC NHẬN*\n\n"
            f"User: @{order['username']} (ID: {order['user_id']})\n"
            f"Gói: {PACKAGES[order['package']]}\n"
            f"Người: {PEOPLE[order['person']]['name']}\n"
            f"Mã GD: `{tx}`\n"
            f"Thời gian: {order['created_at']}\n\n"
            "Người dùng đã bấm nút **'ĐÃ XÁC NHẬN THANH TOÁN'**."
        )
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_notice_user_confirm, parse_mode="Markdown", reply_markup=kb_admin_for_tx(tx))
            except Exception:
                pass

    # admin confirm ok/fail -> if ok send contact + start countdown
    elif action == "admin" and len(parts) == 3:
        result = parts[1]; tx = parts[2]
        order = ORDERS.get(tx)
        if not order:
            await query.answer("⚠️ Đơn không tồn tại hoặc đã xử lý.", show_alert=True)
            try:
                await query.edit_message_text("⚠️ Đơn đã không tồn tại hoặc đã được xử lý.")
            except Exception:
                pass
            return
        if query.from_user.id not in ADMINS:
            await query.answer("🚫 Bạn không có quyền thực hiện thao tác này.", show_alert=True)
            return
        user_id = order["user_id"]; person_key = order["person"]; pkg_code = order["package"]
        
        # Thêm trạng thái vào order trước khi lưu vào lịch sử
        order["status"] = "success" if result == "ok" else "failed"
        order["processed_by_admin"] = query.from_user.id
        TRANSACTION_HISTORY[tx] = order
        
        if result == "ok":
            contact_text = (
                f"🎉 *Thanh toán thành công!*\n\n"
                f"Bạn đã thuê *{PEOPLE[person_key]['name']}* — {PACKAGES[pkg_code]}\n\n"
                f"📬 *Thông tin liên lạc*:\n{PEOPLE[person_key]['contact']}\n\n"
                "Chúc bạn có khoảng thời gian vui vẻ ❤️"
            )
            # send contact text and create an updating message for countdown
            try:
                sent = await context.bot.send_message(chat_id=user_id, text=contact_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning("Không gửi được contact tới user %s: %s", user_id, e)
                sent = None
            duration = PACKAGE_SECONDS.get(pkg_code, 0)
            if sent and duration > 0:
                ends_at = datetime.datetime.utcnow().timestamp() + duration
                # store active countdown under tx
                # If user already has active session, we preserve separate tx keys.
                # Cancel existing countdown for same tx if any
                old = ACTIVE_COUNTDOWNS.get(tx)
                if old and old.get("task"):
                    try:
                        old["task"].cancel()
                    except Exception:
                        pass
                task = context.application.create_task(countdown_and_expire(context, tx))
                ACTIVE_COUNTDOWNS[tx] = {
                    "user_id": user_id,
                    "msg_id": sent.message_id,
                    "ends_at": ends_at,
                    "contact_text": contact_text,
                    "task": task,
                    "package": pkg_code,
                    "person": person_key, # Thêm person_key vào đây để kiểm tra trạng thái bận
                }
            # update admin message
            try:
                await query.edit_message_text(f"✅ Đã xác nhận *Thành công* cho GD `{tx}`", parse_mode="Markdown")
            except Exception:
                pass
        else:
            # fail
            try:
                await context.bot.send_message(chat_id=user_id, text=f"❌ Thanh toán thất bại cho mã GD `{tx}`. Vui lòng liên hệ admin để biết lý do.")
            except Exception:
                pass
            try:
                await query.edit_message_text(f"❌ Đã đánh dấu *Thất bại* cho GD `{tx}`", parse_mode="Markdown")
            except Exception:
                pass
        # Xóa khỏi danh sách đơn tạm
        ORDERS.pop(tx, None)

    # back handlers
    elif action == "back" and len(parts) >= 2:
        where = parts[1]
        if where == "main":
            try:
                await query.edit_message_caption(caption="🌸 *🔞MENU dịch vụ call sex 🔞* 🌸\n\n 🔞🌚chọn người nói chuyện ban đêm cung nào🌚🔞:", reply_markup=kb_main_menu(), parse_mode="Markdown")
            except Exception:
                try:
                    await query.edit_message_text(text="🌸 *🔞MENU dịch vụ call sex 🔞* 🌸\n\n 🔞🌚chọn người nói chuyện ban đêm cung nào🌚🔞:", reply_markup=kb_main_menu(), parse_mode="Markdown")
                except Exception:
                    await context.bot.send_photo(chat_id=query.from_user.id, photo=MENU_PHOTO, caption="🌸 *MENU CHÍNH* 🌸\n\nChọn dịch vụ bên dưới:", reply_markup=kb_main_menu(), parse_mode="Markdown")
        elif where == "packages":
            try:
                await query.edit_message_caption(caption="📦 *🔞 Danh sách gói thuê theo giờ🔞*:", reply_markup=kb_packages(), parse_mode="Markdown")
            except Exception:
                await query.edit_message_text(text="📦 *🔞 Danh sách gói thuê theo giờ🔞*:", reply_markup=kb_packages(), parse_mode="Markdown")
        elif where == "people" and len(parts) == 3:
            pkg_code = parts[2]
            try:
                await query.edit_message_caption(caption=f"⏳ *Bạn đã chọn gói:* {PACKAGES.get(pkg_code)}\n\nChọn người bạn muốn thuê:", reply_markup=kb_people(pkg_code), parse_mode="Markdown")
            except Exception:
                await query.edit_message_text(text=f"⏳ Bạn đã chọn gói: {PACKAGES.get(pkg_code)}\n\nChọn người bạn muốn thuê:", reply_markup=kb_people(pkg_code), parse_mode="Markdown")
        elif where == "person" and len(parts) == 4:
            pkg_code = parts[2]; person_key = parts[3]
            person = PEOPLE.get(person_key)
            if person:
                caption = f"👤 *{person['name']}*\n\n{person['desc']}\n\n⏳ *Gói:* {PACKAGES.get(pkg_code)}"
                try:
                    await query.edit_message_caption(caption=caption, reply_markup=kb_person_detail(pkg_code, person_key), parse_mode="Markdown")
                except Exception:
                    try:
                        await context.bot.send_photo(chat_id=query.from_user.id, photo=person['photo'], caption=caption, reply_markup=kb_person_detail(pkg_code, person_key), parse_mode="Markdown")
                    except Exception:
                        pass
    else:
        await query.answer()

# ====== Admin Commands & Utilities ======
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền xem thống kê.")
        return
    total_orders = len(ORDERS)
    active_sessions = len(ACTIVE_COUNTDOWNS)
    completed_transactions = len(TRANSACTION_HISTORY)
    total_users_with_sessions = len({v["user_id"] for v in ACTIVE_COUNTDOWNS.values()})
    total_known_users = len(SESSIONS)
    text = (
        f"📊 *Thống kê hệ thống*\n\n"
        f"Đơn chờ xử lý (ORDERS): {total_orders}\n"
        f"Giao dịch đã hoàn tất: {completed_transactions}\n"
        f"Phiên đang hoạt động (ACTIVE_COUNTDOWNS): {active_sessions}\n"
        f"Người dùng có session: {total_users_with_sessions}\n"
        f"Tổng người dùng đã tương tác (tạm lưu): {total_known_users}\n\n"
        f"Chi tiết Active:\n"
    )
    for tx, s in ACTIVE_COUNTDOWNS.items():
        ends_at = s.get("ends_at", 0)
        remain = int(max(0, ends_at - datetime.datetime.utcnow().timestamp()))
        text += f"- {tx} user={s.get('user_id')} remain={format_hms(remain)} pkg={s.get('package')}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view transaction history"""
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền xem lịch sử giao dịch.")
        return
    
    if not TRANSACTION_HISTORY:
        await update.message.reply_text("Lịch sử giao dịch trống.")
        return
        
    text = "📜 *Lịch sử giao dịch đã hoàn tất:*\n\n"
    for tx, order in TRANSACTION_HISTORY.items():
        status_icon = "✅" if order["status"] == "success" else "❌"
        text += (
            f"{status_icon} GD `{tx}`\n"
            f"  - User: @{order['username']} (ID: {order['user_id']})\n"
            f"  - Gói: {PACKAGES[order['package']]}\n"
            f"  - Trạng thái: *{order['status'].upper()}*\n"
            f"  - Thời gian: {order['created_at'].split('T')[0]}\n\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def addtime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addtime <tx> <minutes>  OR /addtime_user <user_id> <minutes>"""
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /addtime <tx> <minutes>")
        return
    tx = args[0]
    try:
        minutes = int(args[1])
    except Exception:
        await update.message.reply_text("Minutes phải là số nguyên.")
        return
    session = ACTIVE_COUNTDOWNS.get(tx)
    if not session:
        await update.message.reply_text("Không tìm thấy phiên hoạt động cho mã GD này.")
        return
    session["ends_at"] += minutes * 60
    await update.message.reply_text(f"Đã cộng {minutes} phút vào GD {tx}. Thời gian còn lại: {format_hms(int(session['ends_at']-datetime.datetime.utcnow().timestamp()))}")

async def addtime_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addtime_user <user_id> <minutes>"""
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /addtime_user <user_id> <minutes>")
        return
    try:
        target = int(args[0])
        minutes = int(args[1])
    except Exception:
        await update.message.reply_text("Tham số không hợp lệ.")
        return
    # tìm session cho user
    found = None
    for tx, s in ACTIVE_COUNTDOWNS.items():
        if s.get("user_id") == target:
            found = (tx, s); break
    if not found:
        await update.message.reply_text("Không tìm thấy phiên hoạt động cho user này.")
        return
    tx, s = found
    s["ends_at"] += minutes * 60
    await update.message.reply_text(f"Đã cộng {minutes} phút cho user {target} (GD {tx}).")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin broadcast: /broadcast message..."""
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền.")
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Cú pháp: /broadcast <message>")
        return
    # broadcast to all users in SESSIONS keys
    targets = list(SESSIONS.keys())
    sent = 0
    for uid in targets:
        try:
            await context.bot.send_message(chat_id=uid, text=f"[Broadcast]\n\n{text}")
        except Exception:
            pass
    await update.message.reply_text(f"Đã gửi tới {sent} người (danh sách dựa trên session tạm).")

async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin chat to user: /chat <user_id> <message>"""
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /chat <user_id> <nội dung tin nhắn>")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("ID người dùng không hợp lệ. Vui lòng sử dụng số.")
        return
    message_text = " ".join(args[1:])
    try:
        await context.bot.send_message(chat_id=target_id, text=f"💬 *Tin nhắn từ Admin*:\n\n{message_text}", parse_mode="Markdown")
        await update.message.reply_text(f"Đã gửi tin nhắn tới người dùng {target_id} thành công.")
    except Exception as e:
        await update.message.reply_text(f"Không thể gửi tin nhắn tới người dùng {target_id}. Lỗi: {e}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin unbans a user: /unban <user_id>"""
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    if not context.args:
        await update.message.reply_text("Cú pháp: /unban <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID người dùng không hợp lệ. Vui lòng sử dụng số.")
        return
    if target_id in USER_STRIKES:
        del USER_STRIKES[target_id]
        await update.message.reply_text(f"Đã gỡ cấm cho người dùng {target_id} thành công.")
    else:
        await update.message.reply_text(f"Người dùng {target_id} không có trong danh sách cấm.")

# ====== User helper commands ======
async def mysession_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    sid = user.id
    sess = SESSIONS.get(sid)
    if not sess:
        await update.message.reply_text("Bạn chưa thao tác gói nào.")
        return
    text = f"Phiên tạm của bạn: {sess}"
    await update.message.reply_text(text)

# ====== Misc (help) ======
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - mở menu\n"
        "/help - trợ giúp\n"
        "/mysession - xem session tạm\n\n"
        "*(Lệnh Admin)*\n"
        "/stats - xem thống kê\n"
        "/history - xem lịch sử giao dịch đã hoàn tất\n"
        "/addtime <tx> <phút> - cộng thêm thời gian cho phiên đã thuê\n"
        "/chat <id_user> <tin nhắn> - nhắn tin cho người dùng qua bot\n"
        "/unban <id_user> - gỡ bỏ cấm tạm thời"
    )

# ====== Main ======
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command)) # Thêm lệnh history
    app.add_handler(CommandHandler("addtime", addtime_command))
    app.add_handler(CommandHandler("addtime_user", addtime_user_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("chat", chat_command)) # Thêm lệnh chat
    app.add_handler(CommandHandler("unban", unban_command)) # Thêm lệnh unban
    app.add_handler(CallbackQueryHandler(callback_router))
    logger.info("Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
