# -*- coding: utf-8 -*-
import asyncio
import logging
from telegram import Bot, Update, constants, File
from telegram.error import TelegramError, BadRequest, InvalidToken, NetworkError, RetryAfter
import sys
import os
import configparser
import time
from pathlib import Path
import re
try:
    import pyperclip
except ImportError:
    pyperclip = None
from textual.validation import Number, ValidationResult, Validator


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='BotController.log',
    filemode='a'
)
logger = logging.getLogger(__name__)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


from textual.app import App, ComposeResult, RenderResult
from textual.containers import Container, VerticalScroll, Horizontal, Grid
from textual.widgets import Button, Header, Footer, Static, Input, Label, Log, Pretty
from textual.reactive import var
from textual.screen import Screen, ModalScreen
from textual.binding import Binding


CONFIG_FILE = 'config.ini'
CONFIG_SECTION = 'BotSettings'
CONFIG_TOKEN_KEY = 'token'
LOG_FOLDER = Path("bot_logs")
RECEIVED_DATA_LOG = LOG_FOLDER / "received_data.log"

def ensure_log_folder():
    try:
        LOG_FOLDER.mkdir(parents=True, exist_ok=True)
        logger.info(f"Папка для логов {LOG_FOLDER.absolute()} готова.")
    except Exception as e:
        logger.error(f"Не могу создать папку для логов {LOG_FOLDER.absolute()}: {e}")

def log_received_data(log_line: str):
    ensure_log_folder()
    try:
        with open(RECEIVED_DATA_LOG, 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {log_line}\n")
    except Exception as e:
        logger.error(f"Ошибка при записи в {RECEIVED_DATA_LOG}: {e}")

def load_token_from_config() -> str | None:
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try:
            config.read(CONFIG_FILE, encoding='utf-8')
            return config.get(CONFIG_SECTION, CONFIG_TOKEN_KEY, fallback=None)
        except Exception as e:
            logger.error(f"Ошибка при чтении конфига {CONFIG_FILE}: {e}")
            return None
    return None

def save_token_to_config(token: str) -> bool:
    config = configparser.ConfigParser()
    try:
        if os.path.exists(CONFIG_FILE):
            config.read(CONFIG_FILE, encoding='utf-8')

        if CONFIG_SECTION not in config:
            config[CONFIG_SECTION] = {}
        config[CONFIG_SECTION][CONFIG_TOKEN_KEY] = token
        with open(CONFIG_FILE, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        logger.info(f"Токен сохранен в {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении конфига {CONFIG_FILE}: {e}")
        return False

BOT_TOKEN = os.getenv('BotController_TOKEN', 'DEFAULT_TOKEN_PLACEHOLDER')


async def set_bot_name(bot: Bot, new_name: str):
    try:
        await bot.set_my_name(name=new_name)
        msg = f"Имя бота успешно изменено на: {new_name}"
        logger.info(msg)
        return True, msg
    except TelegramError as e:
        msg = f"Ошибка при смене имени: {e}"
        logger.error(msg)
        return False, msg

async def set_bot_description(bot: Bot, new_description: str):
    try:
        await bot.set_my_description(description=new_description[:constants.BotDescriptionLimit.MAX_DESCRIPTION_LENGTH])
        msg = "Описание бота успешно изменено."
        logger.info(msg)
        return True, msg
    except TelegramError as e:
        msg = f"Ошибка при смене описания: {e}"
        logger.error(msg)
        return False, msg

async def set_bot_about(bot: Bot, new_about: str):
    try:
        await bot.set_my_short_description(short_description=new_about[:constants.BotDescriptionLimit.MAX_SHORT_DESCRIPTION_LENGTH])
        msg = "Короткое описание ('О себе') бота успешно изменено."
        logger.info(msg)
        return True, msg
    except TelegramError as e:
        msg = f"Ошибка при смене короткого описания: {e}"
        logger.error(msg)
        return False, msg

async def set_bot_profile_photo(bot: Bot, photo_path: str) -> tuple[bool, str]:
    photo_file = Path(photo_path)
    if not photo_file.is_file():
        msg = f"Файл аватара не найден по пути: {photo_path}"
        logger.error(msg)
        return False, msg

    try:
        with open(photo_file, 'rb') as photo_stream:
            await bot.set_chat_photo(photo=photo_stream)
        msg = f"Аватарка бота успешно установлена из файла: {photo_path}"
        logger.info(msg)
        return True, msg
    except FileNotFoundError:
        msg = f"Ошибка! Файл не найден: {photo_path}"
        logger.error(msg)
        return False, msg
    except TelegramError as e:
        msg = f"Ошибка при установке аватарки: {e}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Непредвиденная ошибка при установке аватарки: {e}"
        logger.error(msg, exc_info=True)
        return False, msg

async def send_message_to_chat(bot: Bot, chat_id_str: str, message_text: str, parse_mode: str | None = constants.ParseMode.HTML, is_mass_spam: bool = False) -> tuple[bool, str]:
    if not chat_id_str:
        return False, "ID чата не указан."
    if not message_text:
        return False, "Текст сообщения пустой."

    processed_chat_id: int | str
    try:
        processed_chat_id = int(chat_id_str)
    except ValueError:
        if not chat_id_str.startswith('@'):
             processed_chat_id = '@' + chat_id_str
        else:
             processed_chat_id = chat_id_str
    try:
        sent_message = await bot.send_message(chat_id=processed_chat_id, text=message_text, parse_mode=parse_mode)
        msg = f"Сообщение отправлено в чат {processed_chat_id}"

        if not is_mass_spam:
            logger.info(msg)
            try:
                log_entry = (
                    f"OUTGOING; "
                    f"Chat: {processed_chat_id}; "
                    f"Content: Text: '{message_text[:150]}{'...' if len(message_text) > 150 else ''}'"
                )
                log_received_data(log_entry)
            except Exception as log_e:
                 logger.error(f"Ошибка при логировании ИСХОДЯЩЕГО сообщения в {processed_chat_id}: {log_e}")

        return True, msg
    except RetryAfter as e:
        retry_delay = e.retry_after
        msg = f"Ошибка, Rate Limit! Телеграм просит подождать {retry_delay} сек. для чата {processed_chat_id}"
        logger.warning(msg)
        return False, f"RATE_LIMIT:{retry_delay}"
    except BadRequest as e:
        msg = f"Ошибка BadRequest при отправке в {processed_chat_id}: {e}."
        if not is_mass_spam:
            msg += " Проверь ID/юзернейм и права бота."
            logger.error(msg)
        return False, msg
    except InvalidToken:
        msg = "Ошибка! Токен стал недействительным во время отправки."
        logger.error(msg)
        return False, msg
    except NetworkError as e:
        msg = f"Ошибка с сетью при отправке в {processed_chat_id}: {e}"
        logger.error(msg)
        return False, msg
    except TelegramError as e:
        msg = f"Другая ошибка Telegram при отправке в чат {processed_chat_id}: {e}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Непредвиденная ошибка при отправке в {processed_chat_id}: {e}"
        logger.error(msg, exc_info=True)
        return False, msg


async def get_bot_info(bot: Bot):
    try:
        me = await bot.get_me()
        info = (
            f"[b]Инфа о боте:[/]\n"
            f"ID: [cyan]{me.id}[/]\n"
            f"Имя: [green]{me.first_name}[/]\n"
            f"Юзернейм: [yellow]@{me.username}[/]\n"
            f"Может присоединяться к группам: {'[green]Да[/]' if me.can_join_groups else '[red]Нет[/]'}\n"
            f"Читает все сообщения в группе: {'[green]Да[/]' if me.can_read_all_group_messages else '[red]Нет[/]'}\n"
            f"Поддерживает инлайн-запросы: {'[green]Да[/]' if me.supports_inline_queries else '[red]Нет[/]'}"
        )
        logger.info(f"Получена инфа о боте @{me.username}")
        return True, info
    except InvalidToken:
        msg = "Ошибка! Токен недействительный. Проверь и введи правильный."
        logger.error(msg)
        return False, msg
    except TelegramError as e:
        msg = f"Ошибка при получении инфы о боте: {e}"
        logger.error(msg)
        return False, msg

async def spam_chat(bot: Bot, chat_id_str: str, message_text: str, count: int, delay: float, app_log_callback) -> tuple[bool, str]:
    if not chat_id_str: return False, "ID чата для спама не указан."
    if not message_text: return False, "Текст для спама пустой."
    if count <= 0: return False, "Количество сообщений должно быть больше нуля."
    if delay < 0: return False, "Задержка не может быть отрицательной."

    app_log_callback(f"Начинаю спам в чат {chat_id_str}: {count} сообщений с задержкой {delay} сек.", success=None)
    success_count = 0
    last_error = ""
    start_time = time.monotonic()

    for i in range(count):
        if not bot:
            msg = "Ошибка! Объект бота пропал во время спама."
            app_log_callback(msg, success=False)
            return False, msg

        success, result_msg = await send_message_to_chat(bot, chat_id_str, message_text, parse_mode=None, is_mass_spam=True)
        current_delay = delay
        if success:
            success_count += 1
            app_log_callback(f"Спам {i+1}/{count}: Сообщение в {chat_id_str} отправлено.", success=True)
        else:
            last_error = result_msg
            if result_msg.startswith("RATE_LIMIT"):
                try:
                    wait_time = float(result_msg.split(":")[1])
                    app_log_callback(f"Спам {i+1}/{count}: Поймали Rate Limit для {chat_id_str}. Жду {wait_time:.1f} сек...", warning=True)
                    await asyncio.sleep(wait_time)
                    current_delay = 0
                    success, result_msg = await send_message_to_chat(bot, chat_id_str, message_text, parse_mode=None, is_mass_spam=True)
                    if success:
                        success_count += 1
                        app_log_callback(f"Спам {i+1}/{count}: Повторно отправлено в {chat_id_str} после Rate Limit.", success=True)
                        last_error = ""
                    else:
                         app_log_callback(f"Спам {i+1}/{count}: Повторная отправка в {chat_id_str} не удалась: {result_msg}", success=False)
                         last_error = result_msg
                except Exception as e_wait:
                     app_log_callback(f"Спам {i+1}/{count}: Ошибка при ожидании Rate Limit: {e_wait}", success=False)

            else:
                 app_log_callback(f"Спам {i+1}/{count}: Ошибка отправки в {chat_id_str} - {result_msg}", success=False)

            if "недействителен" in result_msg:
                 app_log_callback("Критическая ошибка (токен), прекращаю спам.", success=False)
                 break

        if i < count - 1 and current_delay > 0:
            await asyncio.sleep(current_delay)

    end_time = time.monotonic()
    total_time = end_time - start_time
    final_msg = f"Спам завершен за {total_time:.2f} сек. Успешно отправлено: {success_count}/{count}. Ошибок: {len(last_error.split(':')) - 1 if last_error else 0}."
    if last_error:
        final_msg += f" Последняя ошибка: {last_error}"

    app_log_callback(final_msg, success=(success_count > 0))
    logger.info(final_msg.replace("[red]", "").replace("[/]", ""))
    return success_count > 0, final_msg

def extract_chat_ids_from_log() -> set[str]:
    chat_ids = set()
    if not RECEIVED_DATA_LOG.exists():
        logger.warning(f"Файл лога {RECEIVED_DATA_LOG} не найден для извлечения ID.")
        return chat_ids

    chat_id_pattern = re.compile(r"Chat: (-?\d+)")
    chat_username_pattern = re.compile(r"Chat: [^)]+\(@([^)]+)\)")
    sender_id_pattern = re.compile(r"Sender: (\d+)")
    sender_username_pattern = re.compile(r"Sender: [^)]+\(@([^)]+)\)")
    callback_from_id_pattern = re.compile(r"CallbackQuery: From=(\d+)")
    callback_from_username_pattern = re.compile(r"CallbackQuery: From=[^)]+\(@([^)]+)\)")

    try:
        with open(RECEIVED_DATA_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                match = chat_id_pattern.search(line)
                if match: chat_ids.add(match.group(1))
                match = chat_username_pattern.search(line)
                if match: chat_ids.add(f"@{match.group(1)}")

                match = sender_id_pattern.search(line)
                if match: chat_ids.add(match.group(1))
                match = sender_username_pattern.search(line)
                if match: chat_ids.add(f"@{match.group(1)}")

                match = callback_from_id_pattern.search(line)
                if match: chat_ids.add(match.group(1))
                match = callback_from_username_pattern.search(line)
                if match: chat_ids.add(f"@{match.group(1)}")

    except Exception as e:
        logger.error(f"Ошибка при чтении или парсинге лога {RECEIVED_DATA_LOG}: {e}")

    logger.info(f"Извлечено {len(chat_ids)} уникальных ID/юзернеймов из лога: {chat_ids}")
    return chat_ids

async def spam_all_known_chats(bot: Bot, message_text: str, delay: float, duration_minutes: float, app_log_callback) -> tuple[bool, str]:
    app_log_callback(f"[red]!!! НАЧИНАЮ МАССОВЫЙ СПАМ ПО ЛОГАМ НА {duration_minutes} МИНУТ !!![/]", warning=True)
    app_log_callback("[red]!!! ЭТО МОЖЕТ ПРИВЕСТИ К БАНУ БОТА !!![/]", warning=True)

    chat_ids = extract_chat_ids_from_log()
    if not chat_ids:
        msg = "Не найдено ни одного ID чата в логе. Запусти 'Лог Апдейтов', чтобы собрать их."
        app_log_callback(msg, warning=True)
        return False, msg

    app_log_callback(f"Найдено {len(chat_ids)} уникальных ID/юзернеймов. Начинаю рассылку с задержкой {delay} сек. на {duration_minutes} мин...", success=None)

    success_count = 0
    error_count = 0
    rate_limit_waits = 0
    total_sent_attempts = 0
    start_time = time.monotonic()
    end_time = start_time + duration_minutes * 60
    last_error = ""
    stopped_by_time = False

    chat_ids_list = list(chat_ids)

    while time.monotonic() < end_time:
        app_log_callback(f"Начинаю новый цикл рассылки (осталось {(end_time - time.monotonic()) / 60:.1f} мин)...", success=None)
        current_cycle_start_time = time.monotonic()

        for i, chat_id in enumerate(chat_ids_list):
            if time.monotonic() >= end_time:
                stopped_by_time = True
                app_log_callback("Время спама истекло, останавливаю текущий цикл.", warning=True)
                break

            if not bot:
                 msg = "Ошибка! Объект бота пропал во время массового спама."
                 app_log_callback(msg, success=False)
                 return False, msg

            total_sent_attempts += 1
            success, result_msg = await send_message_to_chat(bot, chat_id, message_text, parse_mode=None, is_mass_spam=True)
            current_iter_delay = delay

            if success:
                success_count += 1
            else:
                error_count += 1
                last_error = f"{chat_id}: {result_msg}"
                if result_msg.startswith("RATE_LIMIT"):
                    try:
                        wait_time = float(result_msg.split(":")[1])
                        rate_limit_waits += 1
                        app_log_callback(f"Масс-спам: Поймали Rate Limit для {chat_id}. Жду {wait_time:.1f} сек...", warning=True)

                        wait_start = time.monotonic()
                        while time.monotonic() < wait_start + wait_time:
                             if time.monotonic() >= end_time:
                                 stopped_by_time = True
                                 app_log_callback("Время спама истекло во время ожидания Rate Limit.", warning=True)
                                 break
                             await asyncio.sleep(0.1)

                        if stopped_by_time: break

                        current_iter_delay = 0

                        app_log_callback(f"Масс-спам: Повторная отправка в {chat_id} после Rate Limit...", success=None)
                        success, result_msg = await send_message_to_chat(bot, chat_id, message_text, parse_mode=None, is_mass_spam=True)
                        if success:
                            success_count += 1
                            error_count -= 1
                            last_error = ""
                            app_log_callback(f"Масс-спам: Повторно отправлено в {chat_id}.", success=True)
                        else:
                            last_error = f"{chat_id}: {result_msg} (после ожидания)"
                            app_log_callback(f"Масс-спам: Повторная отправка в {chat_id} не удалась: {result_msg}", success=False)

                    except Exception as e_wait:
                         app_log_callback(f"Масс-спам: Ошибка при ожидании Rate Limit: {e_wait}", success=False)
                else:
                    pass

                if "недействителен" in result_msg:
                     app_log_callback("Критическая ошибка (токен), прекращаю массовый спам.", success=False)
                     stopped_by_time = True
                     break

            if time.monotonic() >= end_time:
                 stopped_by_time = True
                 app_log_callback("Время спама истекло после отправки/ошибки.", warning=True)
                 break

            if i < len(chat_ids_list) - 1 and current_iter_delay > 0:
                wait_start = time.monotonic()
                while time.monotonic() < wait_start + current_iter_delay:
                    if time.monotonic() >= end_time:
                         stopped_by_time = True
                         app_log_callback("Время спама истекло во время задержки между чатами.", warning=True)
                         break
                    await asyncio.sleep(0.1)
                if stopped_by_time: break

        if stopped_by_time:
            break

        cycle_duration = time.monotonic() - current_cycle_start_time
        if cycle_duration < 1.0 and time.monotonic() < end_time:
            await asyncio.sleep(1.0 - cycle_duration)


    actual_duration_sec = time.monotonic() - start_time
    final_msg = f"Массовый спам {'ЗАВЕРШЕН ПО ВРЕМЕНИ' if stopped_by_time else 'ЗАВЕРШЕН'} за {actual_duration_sec:.2f} сек. ({actual_duration_sec / 60:.1f} мин)."
    final_msg += f" Всего попыток: {total_sent_attempts}. Успешно: {success_count}. Ошибок: {error_count}. Ожиданий Rate Limit: {rate_limit_waits}."
    if last_error:
        final_msg += f" Последняя ошибка: {last_error}"

    app_log_callback(final_msg, success=(success_count > 0))
    logger.info(final_msg.replace("[red]", "").replace("[/]", ""))
    return success_count > 0, final_msg

async def get_and_log_updates(bot: Bot, limit: int = 100, timeout: int = 10, app_log_callback = None) -> tuple[bool, str]:
    processed_count = 0
    last_update_id = 0
    log_lines = []
    try:
        updates = await bot.get_updates(limit=limit, timeout=timeout)
        logger.info(f"Запрошено {limit} обновлений, получено {len(updates)}.")

        if not updates:
            return True, "Новых обновлений (сообщений/файлов и т.д.) нет."

        ensure_log_folder()

        for update in updates:
            log_entry = f"INCOMING; UpdateID: {update.update_id}; "
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

            if update.message:
                msg = update.message
                chat_info = f"Chat: {msg.chat.id} ({msg.chat.title or msg.chat.username or 'Private'})"
                sender_info = f"Sender: {msg.from_user.id} (@{msg.from_user.username or 'NoUsername'})"
                content_info = "Content: "
                file_logged = False

                if msg.text:
                    content_info += f"Text: '{msg.text[:150]}{'...' if len(msg.text) > 150 else ''}'"
                elif msg.sticker:
                     content_info += f"Sticker: ID={msg.sticker.file_id}, Emoji={msg.sticker.emoji}"
                elif msg.photo:
                     photo: File = msg.photo[-1]
                     content_info += f"Photo: ID={photo.file_id}, Size={photo.width}x{photo.height}, FileSize={photo.file_size or 'N/A'}"
                     file_logged = True
                elif msg.document:
                     doc: File = msg.document
                     content_info += f"Document: Name='{doc.file_name}', MIME={doc.mime_type}, ID={doc.file_id}, FileSize={doc.file_size or 'N/A'}"
                     file_logged = True
                elif msg.audio:
                     audio: File = msg.audio
                     content_info += f"Audio: Name='{audio.file_name}', Title='{audio.title}', Performer='{audio.performer}', MIME={audio.mime_type}, ID={audio.file_id}, FileSize={audio.file_size or 'N/A'}"
                     file_logged = True
                elif msg.video:
                     video: File = msg.video
                     content_info += f"Video: Name='{video.file_name}', MIME={video.mime_type}, ID={video.file_id}, FileSize={video.file_size or 'N/A'}"
                     file_logged = True
                elif msg.voice:
                     voice: File = msg.voice
                     content_info += f"Voice: MIME={voice.mime_type}, ID={voice.file_id}, FileSize={voice.file_size or 'N/A'}"
                     file_logged = True
                else:
                     content_info += "Other message type"

                log_entry += f"{chat_info}; {sender_info}; {content_info}"
                log_received_data(log_entry)
                log_lines.append(f"@{msg.from_user.username or msg.from_user.id}: {content_info.replace('Content: ', '')}")
                if file_logged and app_log_callback:
                    app_log_callback(f"Залогирован файл от @{msg.from_user.username or msg.from_user.id}", success=None)

            elif update.edited_message:
                 log_entry += f"Edited Message: ChatID={update.edited_message.chat_id}, MsgID={update.edited_message.message_id}"
                 log_received_data(log_entry)
                 log_lines.append(f"Edited msg {update.edited_message.message_id}")
            elif update.callback_query:
                 q = update.callback_query
                 log_entry += f"CallbackQuery: From={q.from_user.id} (@{q.from_user.username or '?'}), Data='{q.data}', MsgID={q.message.message_id if q.message else '?'}"
                 log_received_data(log_entry)
                 log_lines.append(f"Callback from @{q.from_user.username or q.from_user.id}: '{q.data}'")
            else:
                 log_entry += f"Unknown update type: {update.to_dict()}"
                 log_received_data(log_entry)
                 log_lines.append(f"Unknown update type {update.update_id}")

            processed_count += 1
            last_update_id = update.update_id

        result_message = f"Залогировано {processed_count} обновлений в {RECEIVED_DATA_LOG}."
        logger.info(result_message)
        if app_log_callback:
             for line in log_lines[:10]:
                  app_log_callback(f"  {line}", success=None)
             if len(log_lines) > 10:
                 app_log_callback(f"  ...и еще {len(log_lines) - 10} записей.", success=None)
        return True, result_message

    except InvalidToken:
        msg = "Ошибка! Токен недействительный."
        logger.error(msg)
        if app_log_callback: app_log_callback(msg, success=False)
        return False, msg
    except TelegramError as e:
        msg = f"Ошибка при получении/логировании обновлений: {e}"
        logger.error(msg)
        if app_log_callback: app_log_callback(msg, success=False)
        return False, msg
    except Exception as e:
        msg = f"Непредвиденная ошибка при получении/логировании обновлений: {e}"
        logger.error(msg, exc_info=True)
        if app_log_callback: app_log_callback(msg, success=False)
        return False, msg

class InputScreen(ModalScreen[str]):
    BINDINGS = [
        Binding("ctrl+v", "paste", "Вставить", show=False),
    ]

    def __init__(self, prompt: str, initial: str | None = None, password: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._prompt = prompt
        self._initial = initial
        self._password = password

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="input-dialog"):
            yield Label(self._prompt)
            yield Input(value=self._initial or "", password=self._password, id="input-field")
            with Horizontal(id="input-buttons"):
                yield Button("Вставить", id="paste-button", disabled=(not pyperclip))
                yield Button("OK", variant="primary", id="ok")
                yield Button("Отмена", id="cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "ok":
            value = self.query_one(Input).value
            self.dismiss(value)
        elif button_id == "cancel":
            self.dismiss("")
        elif button_id == "paste-button":
             self.action_paste()
             self.query_one(Input).focus()

    def action_paste(self) -> None:
        if pyperclip:
            try:
                clipboard_content = pyperclip.paste()
                if clipboard_content:
                    input_widget = self.query_one(Input)
                    input_widget.insert_text_at_cursor(clipboard_content)
            except Exception as e:
                 err_msg = f"Ошибка при вставке из буфера: {e}"
                 hint = ""
                 if sys.platform.startswith('linux'):
                      hint = "\n[yellow]Подсказка для Linux:[/yellow] Убедись, что установлена утилита '[b]xclip[/]' или '[b]xsel[/]' (например, 'sudo apt install xclip')."
                 logger.error(f"{err_msg}\n{hint.replace('[yellow]', '').replace('[/yellow]', '').replace('[b]', '').replace('[/b]', '')}")
                 self.app.notify(f"Не удалось вставить из буфера.{hint}", title="Ошибка вставки", severity="error", timeout=10)
        else:
             self.app.notify("Библиотека pyperclip не найдена", title="Ошибка", severity="error")

class PhotoInputScreen(ModalScreen[str]):
    def compose(self) -> ComposeResult:
        with VerticalScroll(id="input-dialog"):
            yield Label("Введи полный путь к файлу аватарки (JPG/PNG):")
            yield Input(placeholder="/path/to/your/avatar.jpg", id="photo-path-input")
            with Horizontal(id="input-buttons"):
                yield Button("Вставить", id="paste-button", disabled=(not pyperclip))
                yield Button("OK", variant="primary", id="ok")
                yield Button("Отмена", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#photo-path-input").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "ok":
            value = self.query_one(Input).value
            if value and Path(value).exists():
                self.dismiss(value)
            elif value:
                 self.app.notify("Файл по указанному пути не найден!", title="Ошибка", severity="error")
            else:
                 self.app.notify("Путь к файлу не может быть пустым!", title="Ошибка", severity="warning")
        elif button_id == "cancel":
            self.dismiss("")
        elif button_id == "paste-button":
             if pyperclip:
                 try:
                     clipboard_content = pyperclip.paste()
                     if clipboard_content:
                         self.query_one(Input).value = clipboard_content
                 except Exception as e:
                     logger.error(f"Ошибка при вставке пути к фото: {e}")
                     self.app.notify("Ошибка при вставке из буфера.", title="Ошибка", severity="error")
             else:
                 self.app.notify("Pyperclip не найден.", title="Ошибка", severity="error")

class MessageInputScreen(ModalScreen[tuple[str, str]]):
    BINDINGS = [
        Binding("ctrl+v", "paste", "Вставить", show=False),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="message-dialog"):
            yield Label("Введи ID чата (число) или юзернейм (@username):")
            yield Input(placeholder="ID или @username", id="chat-id-input")
            yield Label("Введи текст сообщения (можно HTML):")
            yield Input(placeholder="Текст сообщения...", id="message-text-input")
            with Horizontal(id="message-buttons"):
                yield Button("Вставить", id="paste-button", disabled=(not pyperclip))
                yield Button("Отправить", variant="primary", id="send")
                yield Button("Отмена", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#chat-id-input").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "send":
            chat_id = self.query_one("#chat-id-input").value
            message_text = self.query_one("#message-text-input").value
            if chat_id and message_text:
                self.dismiss((chat_id, message_text))
            else:
                self.app.notify("Заполните оба поля!", title="Ошибка", severity="warning")
        elif button_id == "cancel":
            self.dismiss(("", ""))
        elif button_id == "paste-button":
             self.action_paste()
             focused_before_paste = self.app.focused
             if isinstance(focused_before_paste, Input):
                 focused_before_paste.focus()
             else:
                 self.query_one("#chat-id-input").focus()

    def action_paste(self) -> None:
        if pyperclip:
            try:
                clipboard_content = pyperclip.paste()
                if clipboard_content:
                    focused_input = self.app.focused
                    if isinstance(focused_input, Input):
                        focused_input.insert_text_at_cursor(clipboard_content)
                    else:
                        try:
                             input_widget = self.query_one("#message-text-input", Input)
                             input_widget.insert_text_at_cursor(clipboard_content)
                        except Exception:
                             self.app.notify("Не удалось определить поле для вставки", title="Ошибка", severity="error")

            except Exception as e:
                 err_msg = f"Ошибка при вставке из буфера в MessageInputScreen: {e}"
                 hint = ""
                 if sys.platform.startswith('linux'):
                      hint = "\n[yellow]Подсказка для Linux:[/yellow] Убедись, что установлена утилита '[b]xclip[/]' или '[b]xsel[/]'."
                 logger.error(f"{err_msg}\n{hint.replace('[yellow]', '').replace('[/yellow]', '').replace('[b]', '').replace('[/b]', '')}")
                 self.app.notify(f"Не удалось вставить из буфера.{hint}", title="Ошибка вставки", severity="error", timeout=10)
        else:
            self.app.notify("Библиотека pyperclip не найдена", title="Ошибка", severity="error")

class SpamInputScreen(ModalScreen[tuple[str, str, int, float] | None]):
    BINDINGS = [
        Binding("ctrl+v", "paste", "Вставить", show=False),
    ]

    DEFAULT_COUNT = 10
    DEFAULT_DELAY = 0.5

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="spam-dialog"):
            with Grid(id="spam-grid"):
                yield Label("ID чата/юзернейм:")
                yield Input(placeholder="ID или @username", id="spam-chat-id")
                yield Label("Текст сообщения:")
                yield Input(placeholder="Текст для спама...", id="spam-text")
                yield Label("Количество:")
                yield Input(placeholder=f"{self.DEFAULT_COUNT}", value=str(self.DEFAULT_COUNT), id="spam-count")
                yield Label("Задержка (сек):")
                yield Input(placeholder=f"{self.DEFAULT_DELAY}", value=str(self.DEFAULT_DELAY), id="spam-delay")
            with Horizontal(id="spam-buttons"):
                yield Button("Вставить", id="paste-button", disabled=(not pyperclip))
                yield Button("Начать спам!", variant="error", id="spam")
                yield Button("Отмена", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#spam-chat-id").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "spam":
            chat_id = self.query_one("#spam-chat-id").value
            text = self.query_one("#spam-text").value
            count_str = self.query_one("#spam-count").value or str(self.DEFAULT_COUNT)
            delay_str = self.query_one("#spam-delay").value or str(self.DEFAULT_DELAY)

            if not chat_id or not text:
                 self.app.notify("ID чата и текст не могут быть пустыми!", title="Ошибка", severity="error")
                 return

            try:
                count = int(count_str)
                if count <= 0: raise ValueError("Количество должно быть > 0")
            except ValueError:
                self.app.notify("Количество сообщений должно быть целым положительным числом!", title="Ошибка", severity="error")
                return

            try:
                delay = float(delay_str.replace(',', '.'))
                if delay < 0: raise ValueError("Задержка не может быть < 0")
            except ValueError:
                self.app.notify("Задержка должна быть числом (>= 0)!", title="Ошибка", severity="error")
                return

            self.dismiss((chat_id, text, count, delay))

        elif button_id == "cancel":
            self.dismiss(None)
        elif button_id == "paste-button":
             self.action_paste()
             focused_before_paste = self.app.focused
             if isinstance(focused_before_paste, Input):
                 focused_before_paste.focus()
             else:
                 self.query_one("#spam-chat-id").focus()


    def action_paste(self) -> None:
        if pyperclip:
            try:
                clipboard_content = pyperclip.paste()
                if clipboard_content:
                     input_widget = self.query_one("#spam-text", Input)
                     input_widget.insert_text_at_cursor(clipboard_content)
            except Exception as e:
                 err_msg = f"Ошибка при вставке из буфера в SpamInputScreen: {e}"
                 logger.error(err_msg)
                 self.app.notify("Не удалось вставить из буфера.", title="Ошибка вставки", severity="error")
        else:
            self.app.notify("Библиотека pyperclip не найдена", title="Ошибка", severity="error")

class PositiveNumber(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            number = float(value.replace(',', '.'))
            if number > 0:
                return self.success()
            else:
                return self.failure("Значение должно быть больше нуля.")
        except ValueError:
            return self.failure("Введите число.")

class MassSpamInputScreen(ModalScreen[tuple[str, float, float] | None]):
    BINDINGS = [
        Binding("ctrl+v", "paste", "Вставить", show=False),
    ]
    DEFAULT_DELAY = 1.0
    DEFAULT_DURATION = 5.0

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="spam-dialog"):
            yield Label("[red b]МАССОВЫЙ СПАМ ПО ЛОГАМ![/]")
            yield Label("Текст сообщения:")
            yield Input(placeholder="Текст для МАССОВОГО спама...", id="spam-text")
            yield Label("Задержка между сообщениями (сек):")
            yield Input(
                placeholder=f"{self.DEFAULT_DELAY}",
                value=str(self.DEFAULT_DELAY),
                id="spam-delay",
                validators=[PositiveNumber(failure_description="Задержка должна быть > 0")]
            )
            yield Label("Длительность спама (минут):")
            yield Input(
                placeholder=f"{self.DEFAULT_DURATION}",
                value=str(self.DEFAULT_DURATION),
                id="spam-duration",
                validators=[PositiveNumber(failure_description="Длительность должна быть > 0")]
            )
            with Horizontal(id="spam-buttons"):
                yield Button("Вставить текст", id="paste-button", disabled=(not pyperclip))
                yield Button("НАЧАТЬ СПАМ!", variant="error", id="spam", classes="critical-button")
                yield Button("Отмена", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#spam-text").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "spam":
            text = self.query_one("#spam-text").value
            delay_input = self.query_one("#spam-delay", Input)
            duration_input = self.query_one("#spam-duration", Input)

            delay_str = delay_input.value or str(self.DEFAULT_DELAY)
            duration_str = duration_input.value or str(self.DEFAULT_DURATION)

            if not text:
                 self.app.notify("Текст не может быть пустым!", title="Ошибка", severity="error")
                 return

            delay_validation = delay_input.validate(delay_str)
            duration_validation = duration_input.validate(duration_str)

            if not delay_validation.is_valid:
                 self.app.notify(delay_validation.failure_description or "Неверная задержка!", title="Ошибка", severity="error")
                 return
            if not duration_validation.is_valid:
                 self.app.notify(duration_validation.failure_description or "Неверная длительность!", title="Ошибка", severity="error")
                 return

            try:
                delay = float(delay_str.replace(',', '.'))
                duration_minutes = float(duration_str.replace(',', '.'))
                self.dismiss((text, delay, duration_minutes))
            except ValueError:
                 self.app.notify("Внутренняя ошибка конвертации чисел!", title="Ошибка", severity="error")
                 return


        elif button_id == "cancel":
            self.dismiss(None)
        elif button_id == "paste-button":
             self.action_paste()
             self.query_one("#spam-text").focus()


    def action_paste(self) -> None:
        if pyperclip:
            try:
                clipboard_content = pyperclip.paste()
                if clipboard_content:
                     input_widget = self.query_one("#spam-text", Input)
                     input_widget.insert_text_at_cursor(clipboard_content)
            except Exception as e:
                 err_msg = f"Ошибка при вставке из буфера в MassSpamInputScreen: {e}"
                 logger.error(err_msg)
                 self.app.notify("Не удалось вставить из буфера.", title="Ошибка вставки", severity="error")
        else:
            self.app.notify("Библиотека pyperclip не найдена", title="Ошибка", severity="error")



class BotController(App[None]):

    CSS = """
    Screen {
        align: center middle;
    }
    #main-container {
        width: 100; height: auto; max-height: 90%;
        border: thick $accent; padding: 1 2; background: $surface;
    }
    #info-panel {
        height: auto; max-height: 10; border: round $primary;
        padding: 1; margin-bottom: 1; overflow-y: auto;
    }
    #button-panel {
        grid-size: 2;
        grid-gutter: 1 2;
        align: center top;
        margin-top: 1;
        height: auto;
        width: 100%;
        overflow-y: auto;
        max-height: 25;
    }
    #button-panel Button {
        width: 100%;
    }
    .critical-button {
        background: $error;
        color: $text;
        border: round $error-darken-2;
    }
    .critical-button:hover {
        background: $error-darken-1;
        border: round $error-darken-3;
    }

    #status-log {
        margin-top: 2;
        height: 10; border: round $primary;
        overflow-y: auto; background: $surface-darken-1;
    }
    #status-log .log--INFO { color: $text; }
    #status-log .log--ERROR { color: $error; background: $error-darken-1; text-style: bold; }
    #status-log .log--SUCCESS { color: $success; text-style: bold; }
    #status-log .log--WARNING { color: $warning; background: $warning-darken-1; }

    #input-dialog, #message-dialog, #spam-dialog {
        border: thick $accent; padding: 1 2; width: 60; height: auto;
        background: $surface-lighten-1;
    }
    #spam-grid {
        grid-size: 2; grid-gutter: 1; height: auto; margin-bottom: 1;
    }
    #spam-grid Label { text-align: right; }
    #spam-grid Input { column-span: 1; }
    #input-buttons, #message-buttons, #spam-buttons {
        margin-top: 1; align: right middle; height: auto;
    }
    #input-buttons Button, #message-buttons Button, #spam-buttons Button {
         margin-left: 1;
    }
    Input { margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Выйти", show=True, priority=True),
        Binding("t", "set_token", "Токен", show=True),
        Binding("i", "get_info", "Инфо", show=True),
        Binding("n", "set_name", "Имя", show=True),
        Binding("d", "set_desc", "Описание", show=True),
        Binding("a", "set_about", "'О себе'", show=True),
        Binding("c", "set_avatar", "Аватар", show=True),
        Binding("s", "send_msg", "Сообщение", show=True),
        Binding("p", "spam_admin", "Спам чат", show=True, key_display="P"),
        Binding("u", "get_updates", "Лог Апдейтов", show=True),
        Binding("m", "mass_spam", "[!]Масс Спам", show=True),
    ]

    bot: Bot | None = None
    current_token: str | None = None
    bot_info = var("Загрузка...")
    is_spamming = var(False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static(self.bot_info, id="info-panel")
            with Grid(id="button-panel"):
                yield Button("Токен [T]", id="set-token", variant="warning")
                yield Button("Инфо [I]", id="get-info", variant="primary")
                yield Button("Имя [N]", id="set-name", variant="default")
                yield Button("Описание [D]", id="set-desc", variant="default")
                yield Button("О себе [A]", id="set-about", variant="default")
                yield Button("Аватар [C]", id="set-avatar", variant="default")
                yield Button("Сообщение [S]", id="send-msg", variant="default")
                yield Button("Спам Чат [P]", id="spam-admin", variant="error")
                yield Button("Лог Апдейтов [U]", id="get-updates", variant="default")
                yield Button("Масс Спам (M) !", id="mass-spam", variant="error", classes="critical-button")

            yield Log(highlight=True, id="status-log")
        yield Footer()

    def watch_is_spamming(self, spamming: bool) -> None:
        try:
            spam_button = self.query_one("#spam-admin", Button)
            mass_spam_button = self.query_one("#mass-spam", Button)
            if spamming:
                spam_button.label = "Спам идёт..."
                spam_button.variant = "success"
                mass_spam_button.label = "Масс Спам идёт..."
                mass_spam_button.variant = "success"
            else:
                spam_button.label = "Спам Чат [P]"
                spam_button.variant = "error"
                mass_spam_button.label = "Масс Спам (M) !"
                mass_spam_button.variant = "error"

            other_buttons = ["get-info", "set-name", "set-desc", "set-about", "set-avatar", "send-msg", "get-updates"]
            for btn_id in other_buttons:
                 try:
                     self.query_one(f"#{btn_id}", Button).disabled = spamming
                 except Exception: pass

            spam_button.disabled = spamming
            mass_spam_button.disabled = spamming

        except Exception as e:
            pass


    def update_bot_info(self, info: str) -> None:
        self.bot_info = info
        try:
            info_widget = self.query_one("#info-panel", Static)
            info_widget.update(self.bot_info)
        except Exception as e:
            logger.error(f"Ошибка при обновлении info-panel: {e}")


    def log_status(self, message: str, success: bool | None = None, warning: bool = False) -> None:
        try:
            log_widget = self.query_one(Log)
            if warning:
                 prefix = "▢ WARNING: "
                 log_widget.add_class("log--WARNING")
            elif success is True:
                prefix = "▢ SUCCESS: "
                log_widget.remove_class("log--WARNING")
            elif success is False:
                prefix = "▢ ERROR: "
                log_widget.remove_class("log--WARNING")
            else:
                prefix = "▢ INFO: "
                log_widget.remove_class("log--WARNING")

            log_widget.write_line(prefix + message)
        except Exception as e:
            logger.warning(f"Не удалось записать в TUI лог: {message}. Ошибка: {e}")


    async def initialize_bot(self, token: str) -> bool:
        self.is_spamming = False
        self.log_status(f"Пытаюсь инициализировать бота с токеном... (последние 5 символов: ...{token[-5:]})")
        try:
            if self.bot:
                self.log_status("Закрываю предыдущее соединение бота...", success=None)
                try:
                    await self.bot.close()
                    self.log_status("Предыдущее соединение закрыто.", success=True)
                except RetryAfter as e_close:
                    self.log_status(f"Не удалось закрыть старое соединение из-за флуд-контроля: {e_close}. Игнорирую...", warning=True)
                    logger.warning(f"RetryAfter при закрытии старого бота: {e_close}")
                except Exception as e_close_other:
                     self.log_status(f"Ошибка при закрытии старого соединения: {e_close_other}.", warning=True)
                     logger.warning(f"Ошибка при закрытии старого бота: {e_close_other}", exc_info=True)
                finally:
                    self.bot = None

            self.bot = Bot(token=token)
            success, info_or_error = await get_bot_info(self.bot)
            if success:
                self.current_token = token
                self.update_bot_info(info_or_error)
                self.log_status(f"Бот @{self.bot.username} готов к работе.", success=True)
                self.set_bot_controls_enabled(True)
                return True
            else:
                self.update_bot_info(f"[red]Ошибка инициализации:[/]\n{info_or_error}")
                self.log_status(f"Ошибка при получении инфы о боте: {info_or_error}", success=False)
                if self.bot:
                    try: await self.bot.close()
                    except Exception: pass
                    self.bot = None
                self.current_token = None
                self.set_bot_controls_enabled(False)
                return False
        except InvalidToken:
            msg = "Ошибка! Токен недействительный."
            self.update_bot_info(f"[red]Неверный токен![/]")
            self.log_status(msg, success=False)
            if self.bot:
                try: await self.bot.close()
                except Exception: pass
            self.bot = None
            self.current_token = None
            self.set_bot_controls_enabled(False)
            return False
        except TelegramError as e:
            if isinstance(e, RetryAfter):
                 error_msg = f"Ошибка, флуд-контроль при инициализации (вероятно, get_me): {e}. Попробуй позже."
                 retry_delay = e.retry_after
                 self.log_status(error_msg + f" Жди {retry_delay} сек.", success=False)
            else:
                 error_msg = f"Ошибка Telegram API при инициализации: {e}"
                 self.log_status(error_msg, success=False)
            logger.error(error_msg)
            self.update_bot_info(f"[red]Ошибка инициализации![/]\n{error_msg}")
            if self.bot:
                 try: await self.bot.close()
                 except Exception: pass
                 self.bot = None
            self.current_token = None
            self.set_bot_controls_enabled(False)
            return False
        except Exception as e:
            error_msg = f"Критическая ошибка при инициализации бота: {e}"
            logger.error(error_msg, exc_info=True)
            self.update_bot_info(f"[red]Ошибка инициализации![/]\nПроверь сеть.")
            self.log_status(error_msg, success=False)
            if self.bot:
                try: await self.bot.close()
                except Exception: pass
            self.bot = None
            self.current_token = None
            self.set_bot_controls_enabled(False)
            return False

    def set_bot_controls_enabled(self, enabled: bool):
        try:
            button_ids = ["set-name", "set-desc", "set-about", "set-avatar", "send-msg", "get-info", "spam-admin", "get-updates", "mass-spam"]
            for btn_id in button_ids:
                try:
                    button = self.query_one(f"#{btn_id}", Button)
                    if self.is_spamming and btn_id not in ["spam-admin", "mass-spam"]:
                        button.disabled = True
                    else:
                         if not (self.is_spamming and btn_id in ["spam-admin", "mass-spam"]):
                              button.disabled = not enabled
                except Exception:
                    logger.warning(f"Не найдена кнопка #{btn_id} для (раз)блокировки")
            self.watch_is_spamming(self.is_spamming)

        except Exception as e:
             logger.error(f"Ошибка при (раз)блокировке кнопок: {e}")


    async def on_mount(self) -> None:
        ensure_log_folder()
        if not pyperclip:
            self.log_status("Pyperclip не найден, кнопка 'Вставить' неактивна (pip install pyperclip)", success=None)

        self.log_status("Загрузка сохраненного токена...")
        loaded_token = load_token_from_config()

        if loaded_token:
            self.log_status("Токен найден в конфиге, пытаюсь подключиться...")
            asyncio.create_task(self.initialize_bot(loaded_token))
        else:
            self.log_status("Токен не найден в config.ini. Нажми 'Установить/Сменить токен'", success=None)
            self.update_bot_info("[yellow]Токен не установлен.[/]\nНажми 't' или кнопку ниже.")
            self.set_bot_controls_enabled(False)


    async def run_bot_action(self, action_coroutine) -> None:
        if self.is_spamming:
             self.log_status("Дождись окончания спама!", warning=True)
             return

        if not asyncio.iscoroutine(action_coroutine):
            self.log_status(f"Ошибка! В run_bot_action передано ({type(action_coroutine)}).", success=False)
            logger.error(f"run_bot_action called with non-coroutine: {action_coroutine}")
            return

        coro_name = getattr(action_coroutine, '__name__', 'unknown_coroutine')
        self.log_status(f"Запускаю функцию: {coro_name}...")
        are_controls_enabled_before = True
        try:
            are_controls_enabled_before = not self.query_one("#get-info", Button).disabled
        except Exception: pass

        msg = ""
        result = None
        try:
             if coro_name not in ['spam_chat', 'spam_all_known_chats']:
                 self.set_bot_controls_enabled(False)

             result = await action_coroutine
             if isinstance(result, tuple) and len(result) == 2:
                 success, message = result
                 msg = message
             else:
                 success = False
                 message = f"Корутина {coro_name} вернула неожиданный результат: {result}"
                 msg = message
                 logger.error(message)


             if coro_name not in ['get_and_log_updates', 'spam_chat', 'spam_all_known_chats']:
                  self.log_status(message, success=success)

             if success and coro_name in ('set_bot_name', 'set_bot_description', 'set_bot_about', 'set_bot_profile_photo', 'get_bot_info'):
                  if coro_name == 'get_bot_info':
                       self.update_bot_info(message)
                  else:
                       if self.bot:
                           _, info_text = await get_bot_info(self.bot)
                           self.update_bot_info(info_text)
                       else:
                            self.log_status("Бот пропал после действия, не могу обновить инфо.", warning=True)


        except InvalidToken:
             msg = "Ошибка! Токен стал недействительным во время работы."
             self.log_status(msg, success=False)
             self.update_bot_info("[red]Токен недействителен![/]")
             if self.bot:
                 try: await self.bot.close()
                 except Exception: pass
             self.bot = None
             self.current_token = None
             self.set_bot_controls_enabled(False)
             return
        except TelegramError as e:
            error_msg = f"Ошибка Telegram API при выполнении {coro_name}: {e}"
            logger.error(error_msg)
            self.log_status(error_msg, success=False)
            msg = error_msg
        except Exception as e:
             if isinstance(e, TypeError) and "unpack" in str(e):
                  error_msg = f"Ошибка при распаковке результата {coro_name}: {e}. Корутина вернула {result}"
             else:
                  error_msg = f"Неперехваченная ошибка при выполнении {coro_name}: {e}"
             logger.error(error_msg, exc_info=True)
             self.log_status(error_msg, success=False)
             msg = error_msg
        finally:
             token_error_occurred = "недействителен" in msg or "Неверный токен" in msg
             is_spam_action = coro_name in ['spam_chat', 'spam_all_known_chats']
             if not token_error_occurred and not is_spam_action:
                  self.set_bot_controls_enabled(are_controls_enabled_before)


    async def action_get_info(self) -> None:
        if not self.bot:
            self.log_status("Бот не инициализирован. Сначала установи токен.", success=False)
            return
        await self.run_bot_action(get_bot_info(self.bot))


    def action_set_token(self) -> None:
        if self.is_spamming:
             self.log_status("Дождись окончания спама!", warning=True)
             return

        def _callback(new_token: str):
            if new_token:
                if new_token.strip():
                    save_token_to_config(new_token.strip())
                    asyncio.create_task(self.initialize_bot(new_token.strip()))
                else:
                    self.log_status("Введен пустой токен, установка отменена.", warning=True)
            else:
                self.log_status("Установка токена отменена.", success=None)

        self.app.push_screen(InputScreen("Введи токен твоего бота:", password=True), _callback)


    def action_set_name(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        def _callback(new_name: str):
            if new_name:
                 asyncio.create_task(self.run_bot_action(set_bot_name(self.bot, new_name)))

        current_name = self.bot.first_name if self.bot else ""
        self.app.push_screen(InputScreen("Введи новое имя бота:", initial=current_name), _callback)

    def action_set_desc(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        def _callback(new_desc: str):
             asyncio.create_task(self.run_bot_action(set_bot_description(self.bot, new_desc)))

        self.app.push_screen(InputScreen("Введи новое основное описание (до 512 символов):"), _callback)

    def action_set_about(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        def _callback(new_about: str):
             asyncio.create_task(self.run_bot_action(set_bot_about(self.bot, new_about)))

        self.app.push_screen(InputScreen("Введи новое короткое описание 'О себе' (до 120 символов):"), _callback)

    def action_set_avatar(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        def _callback(photo_path: str):
            if photo_path:
                 asyncio.create_task(self.run_bot_action(set_bot_profile_photo(self.bot, photo_path)))

        self.app.push_screen(PhotoInputScreen(), _callback)


    def action_send_msg(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        def _callback(result: tuple[str, str]):
            chat_id, message_text = result
            if chat_id and message_text:
                 asyncio.create_task(self.run_bot_action(send_message_to_chat(self.bot, chat_id, message_text)))

        self.app.push_screen(MessageInputScreen(), _callback)

    async def action_spam_admin(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        if self.is_spamming:
            self.log_status("Спам уже идет!", warning=True)
            return

        def _callback(result: tuple[str, str, int, float] | None):
            if result:
                chat_id, text, count, delay = result
                log_callback = self.log_status

                async def spam_task_wrapper():
                    self.is_spamming = True
                    try:
                        await spam_chat(self.bot, chat_id, text, count, delay, log_callback)
                    except Exception as e:
                        err_msg = f"Критическая ошибка в задаче спама (spam_chat): {e}"
                        logger.error(err_msg, exc_info=True)
                        self.log_status(err_msg, success=False)
                    finally:
                         self.is_spamming = False
                         if self.bot and self.current_token:
                              self.set_bot_controls_enabled(True)
                         else:
                              self.set_bot_controls_enabled(False)

                asyncio.create_task(spam_task_wrapper())
            else:
                self.log_status("Спам отменен.", success=None)

        self.app.push_screen(SpamInputScreen(), _callback)


    async def action_mass_spam(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return
        if self.is_spamming:
            self.log_status("Другой спам уже идет!", warning=True)
            return

        def _callback(result: tuple[str, float, float] | None):
            if result:
                text, delay, duration_minutes = result
                log_callback = self.log_status

                async def mass_spam_task_wrapper():
                    self.is_spamming = True
                    try:
                        await spam_all_known_chats(self.bot, text, delay, duration_minutes, log_callback)
                    except Exception as e:
                         err_msg = f"Критическая ошибка в задаче МАССОВОГО спама: {e}"
                         logger.error(err_msg, exc_info=True)
                         self.log_status(err_msg, success=False)
                    finally:
                         self.is_spamming = False
                         if self.bot and self.current_token:
                              self.set_bot_controls_enabled(True)
                         else:
                              self.set_bot_controls_enabled(False)

                asyncio.create_task(mass_spam_task_wrapper())
            else:
                self.log_status("Массовый спам отменен.", success=None)

        self.app.push_screen(MassSpamInputScreen(), _callback)


    async def action_get_updates(self) -> None:
        if not self.bot:
             self.log_status("Бот не инициализирован.", success=False)
             return

        self.log_status("ЗАПРОС get_updates МОЖЕТ КОНФЛИКТОВАТЬ с другими запущенными экземплярами бота!", warning=True)
        self.log_status("Он 'съест' необработанные сообщения с сервера.", warning=True)

        await self.run_bot_action(get_and_log_updates(self.bot, app_log_callback=self.log_status))


    async def on_button_pressed(self, event: Button.Pressed) -> None:
        action_map = {
            "set-token": self.action_set_token,
            "get-info": self.action_get_info,
            "set-name": self.action_set_name,
            "set-desc": self.action_set_desc,
            "set-about": self.action_set_about,
            "set-avatar": self.action_set_avatar,
            "send-msg": self.action_send_msg,
            "spam-admin": self.action_spam_admin,
            "get-updates": self.action_get_updates,
            "mass-spam": self.action_mass_spam,
        }
        button_id = event.button.id

        if button_id == "set-token":
             method_to_call = action_map.get(button_id)
             if method_to_call:
                 self.log_status(f"Запуск функции'{button_id}'", success=None)
                 method_to_call()
             else:
                 logger.error(f"Ошибка! Не найден метод для кнопки 'set-token' в action_map.")
                 self.log_status("Ошибка: Не могу найти действие для кнопки 'Токен'", success=False)
             return

        if not self.bot:
            self.log_status("Сначала установи рабочий токен!", success=False)
            return

        if button_id in action_map:
             method_to_call = action_map[button_id]
             if button_id in ["spam-admin", "mass-spam"]:
                 await method_to_call()
             elif button_id in ["get-info", "get-updates"]:
                 coroutine_to_run = None
                 if button_id == "get-info":
                      coroutine_to_run = get_bot_info(self.bot)
                 elif button_id == "get-updates":
                      coroutine_to_run = get_and_log_updates(self.bot, app_log_callback=self.log_status)

                 if coroutine_to_run:
                     asyncio.create_task(self.run_bot_action(coroutine_to_run))
                 else:
                     logger.warning(f"Запуск функции {button_id} невозможен.")
                     self.log_status(f"Не удалось запустить функцию {button_id}.", success=False)
             else:
                 self.log_status(f"Запуск функции '{button_id}'", success=None)
                 method_to_call()



if __name__ == '__main__':
    try:
        width = 168
        height = 54
        if sys.platform == 'win32':
            os.system(f'mode con: cols={width} lines={height}')
        elif sys.platform.startswith('linux') or sys.platform == 'darwin':
            sys.stdout.write(f"\x1b[8;{height};{width}t")
            sys.stdout.flush()
            logger.info(f"Отправлена команда изменения размера для Linux/macOS на {width}x{height}")
        else:
            logger.warning(f"Неизвестная платформа ({sys.platform}), не могу изменить размер консоли.")
    except Exception as e:
        logger.warning(f"Ошибка при попытке изменить размер консоли: {e}")

    print(f"Запускаю BotController... Логи будут писаться в {os.path.abspath('BotController.log')}")
    print(f"Логи полученных данных бота будут в: {RECEIVED_DATA_LOG.absolute()}")
    ensure_log_folder()
    app = BotController()
    app.run()
