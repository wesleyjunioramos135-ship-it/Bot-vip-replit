# -*- coding: utf-8 -*-
"""
BOT PREMIUM V2 - COMPATÍVEL COM TABELAS V1
- Sistema de idiomas (PT/EN/ES)
- Barra de progresso animada
- Catalogação automática de vídeos
- USA AS TABELAS DA V1 (premium_media, premium_keys, premium_users)
"""

import os
import json
import asyncio
import logging
import random
import string
import threading
from datetime import datetime
from typing import Optional, Dict, List
from urllib.parse import quote

import httpx
from flask import Flask, jsonify
from waitress import serve

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.error import RetryAfter, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ============================================================
# LOG
# ============================================================

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bot_premium_v2")

# ============================================================
# CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_PREMIUM", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6496057548") or "6496057548")

# CONFIGURAÇÕES DO BOT PREMIUM
VIDEOS_POR_LOTE = 50
PROTECT_CONTENT = True

# DB (Supabase)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_DB = os.getenv("SUPABASE_DB", "public").strip()

# Delay entre envios
SEND_DELAY_SECONDS = float(os.getenv("SEND_DELAY_SECONDS", "0.35") or "0.35")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Configure SUPABASE_URL e SUPABASE_KEY!")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_PREMIUM não definido!")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID não definido!")

# ============================================================
# NOMES DAS TABELAS (COMPATÍVEL COM V1)
# ============================================================

TABLE_VIDEOS = "premium_media"      # Tabela de vídeos (V1)
TABLE_KEYS = "premium_keys"         # Tabela de chaves (V1)
TABLE_USERS = "premium_users"       # Tabela de usuários (V1)
TABLE_LANG = "user_lang_pref"       # Tabela de idiomas (NOVA - criar se não existir)

# ============================================================
# BARRA DE PROGRESSO ANIMADA
# ============================================================

PROGRESS_FRAMES = [
    "⏳ [□□□□□□□□□□] 0%",
    "⚙️ [■□□□□□□□□□] 10%",
    "⚙️ [■■□□□□□□□□] 20%",
    "⚙️ [■■■□□□□□□□] 30%",
    "⚙️ [■■■■□□□□□□] 40%",
    "⚙️ [■■■■■□□□□□] 50%",
    "⚙️ [■■■■■■□□□□] 60%",
    "⚙️ [■■■■■■■□□□] 70%",
    "⚙️ [■■■■■■■■□□] 80%",
    "⚙️ [■■■■■■■■■□] 90%",
    "✅ [■■■■■■■■■■] 100%",
]

async def mostrar_loading(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    texto_inicial: str,
    texto_final: str,
    duracao: float = 2.0
):
    """Barra de progresso animada estilo videogame"""
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"{texto_inicial}\n\n{PROGRESS_FRAMES[0]}",
            parse_mode="HTML"
        )
        
        delay_per_frame = duracao / len(PROGRESS_FRAMES)
        
        for frame in PROGRESS_FRAMES[1:]:
            await asyncio.sleep(delay_per_frame)
            try:
                await msg.edit_text(f"{texto_inicial}\n\n{frame}")
            except:
                pass
        
        await asyncio.sleep(0.3)
        await msg.edit_text(texto_final, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Erro no loading: {e}")

# ============================================================
# I18N
# ============================================================

LANGS = ("pt", "en", "es")
LANG_PREF_CACHE: Dict[int, str] = {}

def tr(lang: str, pt: str, en: str, es: str = "") -> str:
    if not es:
        es = en
    if (lang or "pt") == "pt":
        return pt
    elif lang == "es":
        return es
    else:
        return en

# ============================================================
# TEXTOS TRADUZIDOS
# ============================================================

TEXTOS = {
    "welcome_msg": {
        "pt": (
            "🌟 <b>BEM-VINDO AO BOT PREMIUM!</b> 🌟\n\n"
            "🎬 Acesso exclusivo a conteúdo premium\n"
            "🔒 100% protegido e seguro\n"
            "⚡ Envio rápido de vídeos\n"
            "🚫 SEM anúncios\n\n"
            "💎 Para começar, escolha seu idioma:"
        ),
        "en": (
            "🌟 <b>WELCOME TO PREMIUM BOT!</b> 🌟\n\n"
            "🎬 Exclusive access to premium content\n"
            "🔒 100% protected and secure\n"
            "⚡ Fast video delivery\n"
            "🚫 NO ads\n\n"
            "💎 To start, choose your language:"
        ),
        "es": (
            "🌟 <b>¡BIENVENIDO AL BOT PREMIUM!</b> 🌟\n\n"
            "🎬 Acceso exclusivo a contenido premium\n"
            "🔒 100% protegido y seguro\n"
            "⚡ Envío rápido de videos\n"
            "🚫 SIN anuncios\n\n"
            "💎 Para comenzar, elige tu idioma:"
        ),
    },
    "loading_key": {
        "pt": "🔐 <b>VALIDANDO CHAVE...</b>",
        "en": "🔐 <b>VALIDATING KEY...</b>",
        "es": "🔐 <b>VALIDANDO CLAVE...</b>",
    },
    "key_approved": {
        "pt": (
            "✅ <b>CHAVE APROVADA!</b>\n\n"
            "🎉 Você agora tem acesso PREMIUM!\n"
            "📦 Preparando seus vídeos exclusivos..."
        ),
        "en": (
            "✅ <b>KEY APPROVED!</b>\n\n"
            "🎉 You now have PREMIUM access!\n"
            "📦 Preparing your exclusive videos..."
        ),
        "es": (
            "✅ <b>¡CLAVE APROBADA!</b>\n\n"
            "🎉 ¡Ahora tienes acceso PREMIUM!\n"
            "📦 Preparando tus videos exclusivos..."
        ),
    },
    "loading_videos": {
        "pt": "📤 <b>ENVIANDO VÍDEOS PREMIUM...</b>",
        "en": "📤 <b>SENDING PREMIUM VIDEOS...</b>",
        "es": "📤 <b>ENVIANDO VIDEOS PREMIUM...</b>",
    },
    "videos_sent": {
        "pt": "✅ <b>Lote enviado com sucesso!</b>",
        "en": "✅ <b>Batch sent successfully!</b>",
        "es": "✅ <b>¡Lote enviado con éxito!</b>",
    },
}

# ============================================================
# UI (Teclados)
# ============================================================

MENU = {
    "pt": {
        "send_media": "📥 ADICIONAR VÍDEOS",
        "gen_key": "🔑 GERAR CHAVE PREMIUM",
        "list_keys": "📋 LISTAR CHAVES",
        "broadcast": "📣 MENSAGEM PARA TODOS",
        "stats": "📊 ESTATÍSTICAS",
        "lang": "🌐 IDIOMA",
    },
    "en": {
        "send_media": "📥 ADD VIDEOS",
        "gen_key": "🔑 GENERATE PREMIUM KEY",
        "list_keys": "📋 LIST KEYS",
        "broadcast": "📣 BROADCAST",
        "stats": "📊 STATISTICS",
        "lang": "🌐 LANGUAGE",
    },
    "es": {
        "send_media": "📥 AGREGAR VIDEOS",
        "gen_key": "🔑 GENERAR CLAVE PREMIUM",
        "list_keys": "📋 LISTAR CLAVES",
        "broadcast": "📣 MENSAJE PARA TODOS",
        "stats": "📊 ESTADÍSTICAS",
        "lang": "🌐 IDIOMA",
    },
}

def get_admin_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    L = MENU.get(lang or "pt", MENU["pt"])
    layout = [
        [KeyboardButton(L["send_media"])],
        [KeyboardButton(L["gen_key"]), KeyboardButton(L["list_keys"])],
        [KeyboardButton(L["broadcast"])],
        [KeyboardButton(L["stats"]), KeyboardButton(L["lang"])],
    ]
    return ReplyKeyboardMarkup(layout, resize_keyboard=True)

def language_picker_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🇧🇷 Português", callback_data="setlang_pt")],
            [InlineKeyboardButton("🇺🇸 English", callback_data="setlang_en")],
            [InlineKeyboardButton("🇪🇸 Español", callback_data="setlang_es")],
        ]
    )

def painel_inicial_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                tr(lang, "🔑 ATIVAR CHAVE PREMIUM", "🔑 ACTIVATE PREMIUM KEY", "🔑 ACTIVAR CLAVE PREMIUM"),
                callback_data="ativar_chave"
            )],
        ]
    )

def continuar_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                tr(lang, "✅ Sim, continuar", "✅ Yes, continue", "✅ Sí, continuar"),
                callback_data="continuar_sim"
            )],
            [InlineKeyboardButton(
                tr(lang, "❌ Não, parar", "❌ No, stop", "❌ No, parar"),
                callback_data="continuar_nao"
            )],
        ]
    )

# ============================================================
# ESTADO EM MEMÓRIA
# ============================================================

MEDIA_CACHE: List[Dict[str, str]] = []
MEDIA_VERSION: int = 0

USER_ID_MAP: Dict[str, int] = {}
ID_TO_USERNAME: Dict[int, str] = {}

USER_VIDEO_POSITION: Dict[int, int] = {}
PENDING_KEY_ACTIVATION: Dict[int, bool] = {}

# ============================================================
# SUPABASE HELPERS
# ============================================================

def _sb_headers(extra_prefer: str = "") -> Dict[str, str]:
    prefer = "return=representation"
    if extra_prefer:
        prefer = prefer + "," + extra_prefer
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }
    if SUPABASE_DB and SUPABASE_DB != "public":
        headers["Accept-Profile"] = SUPABASE_DB
        headers["Content-Profile"] = SUPABASE_DB
    return headers

def _ensure_select(filters_qs: str) -> str:
    if not filters_qs:
        return "?select=*"
    if "select=" in filters_qs:
        return filters_qs
    if filters_qs.startswith("?"):
        return "?select=*&" + filters_qs[1:]
    return "?select=*&" + filters_qs

async def sb_select(table: str, filters: str = ""):
    url = f"{SUPABASE_URL}/rest/v1/{table}{_ensure_select(filters)}"
    logger.info(f"🔍 SELECT: {table}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=_sb_headers())
        logger.info(f"✅ Status: {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

async def sb_insert(table: str, data: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    logger.info(f"➕ INSERT em {table}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=_sb_headers(), json=data)
        logger.info(f"✅ Status: {resp.status_code}")
        if resp.status_code >= 400:
            logger.error(f"❌ Erro: {resp.text}")
        resp.raise_for_status()
        return resp.json()

async def sb_update(table: str, filters: str, data: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}{filters}"
    logger.info(f"✏️ UPDATE em {table}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.patch(url, headers=_sb_headers(), json=data)
        logger.info(f"✅ Status: {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

async def sb_delete(table: str, filters: str):
    url = f"{SUPABASE_URL}/rest/v1/{table}{filters}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(url, headers=_sb_headers())
        resp.raise_for_status()
        return resp.json()

# ============================================================
# FUNÇÕES DE BANCO (USANDO TABELAS V1)
# ============================================================

async def load_media_from_db() -> List[Dict[str, str]]:
    """Carrega vídeos da tabela premium_media (V1)"""
    try:
        logger.info("📥 Carregando vídeos do banco...")
        rows = await sb_select(TABLE_VIDEOS, "?order=added_at.desc")
        result = []
        for r in rows:
            result.append({
                "file_id": r["file_id"],
                "tipo": r.get("file_type", "video"),  # V1 usa 'file_type'
            })
        logger.info(f"✅ {len(result)} vídeos carregados")
        return result
    except Exception as e:
        logger.error(f"❌ Erro ao carregar vídeos: {e}")
        return []

async def save_media_to_db(file_id: str, tipo: str = "video"):
    """Salva vídeo na tabela premium_media (V1)"""
    try:
        logger.info(f"💾 Salvando {tipo}: {file_id[:20]}...")
        
        # Verifica duplicata
        try:
            existing = await sb_select(TABLE_VIDEOS, f"?file_id=eq.{file_id}")
            if existing and len(existing) > 0:
                logger.warning(f"⚠️ Vídeo já existe!")
                return True
        except:
            pass
        
        # Insere (V1 usa 'file_type' em vez de 'tipo')
        data = {
            "file_id": file_id,
            "file_type": tipo,  # V1 usa este nome
            "added_at": datetime.utcnow().isoformat()
        }
        
        await sb_insert(TABLE_VIDEOS, data)
        logger.info(f"✅ Vídeo salvo com sucesso!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erro ao salvar: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def get_lang_pref(user_id: int) -> Optional[str]:
    """Busca idioma (tenta tabela nova, senão usa da V1)"""
    try:
        # Tenta tabela nova primeiro
        rows = await sb_select(TABLE_LANG, f"?user_id=eq.{user_id}")
        if rows and len(rows) > 0:
            return rows[0].get("lang", "pt")
    except:
        # Se não existir, tenta na tabela V1
        try:
            rows = await sb_select(TABLE_USERS, f"?user_id=eq.{user_id}")
            if rows and len(rows) > 0:
                return rows[0].get("lang", "pt")
        except:
            pass
    return None

async def set_lang_pref(user_id: int, lang: str):
    """Salva idioma (tenta tabela nova, senão salva na V1)"""
    try:
        # Tenta salvar na tabela nova
        rows = await sb_select(TABLE_LANG, f"?user_id=eq.{user_id}")
        if rows and len(rows) > 0:
            await sb_update(TABLE_LANG, f"?user_id=eq.{user_id}", {"lang": lang})
        else:
            await sb_insert(TABLE_LANG, {"user_id": user_id, "lang": lang})
    except:
        # Se falhar, salva na tabela V1
        try:
            await sb_update(TABLE_USERS, f"?user_id=eq.{user_id}", {"lang": lang})
        except:
            pass

async def generate_premium_key() -> str:
    """Gera chave premium"""
    while True:
        key = "PREMIUM-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        try:
            rows = await sb_select(TABLE_KEYS, f"?key_code=eq.{key}")
            if not rows or len(rows) == 0:
                await sb_insert(TABLE_KEYS, {
                    "key_code": key,
                    "used": False,  # V1 usa 'used' não 'is_used'
                    "created_at": datetime.utcnow().isoformat()
                })
                return key
        except:
            continue

async def validate_and_use_key(key_code: str, user_id: int) -> bool:
    """Valida e ativa chave"""
    try:
        rows = await sb_select(TABLE_KEYS, f"?key_code=eq.{key_code}")
        if not rows or len(rows) == 0:
            return False
        
        key_data = rows[0]
        if key_data.get("used"):  # V1 usa 'used'
            return False
        
        # Marca como usada (V1 usa 'used' e 'used_by_user_id')
        await sb_update(TABLE_KEYS, f"?key_code=eq.{key_code}", {
            "used": True,
            "used_by_user_id": user_id,  # V1 usa este nome
            "used_at": datetime.utcnow().isoformat()
        })
        
        # Registra usuário (V1 pode usar 'ativado_em')
        try:
            await sb_insert(TABLE_USERS, {
                "user_id": user_id,
                "ativado_em": datetime.utcnow().isoformat(),  # V1 usa este nome
                "key_used": key_code
            })
        except:
            pass
        
        return True
    except Exception as e:
        logger.error(f"Erro ao validar chave: {e}")
        return False

async def is_premium_user(user_id: int) -> bool:
    """Verifica se é premium"""
    try:
        rows = await sb_select(TABLE_USERS, f"?user_id=eq.{user_id}")
        return rows and len(rows) > 0
    except:
        return False

async def get_all_premium_keys() -> List[Dict]:
    """Lista todas as chaves"""
    try:
        return await sb_select(TABLE_KEYS, "?order=created_at.desc")
    except:
        return []

async def get_all_premium_users() -> List[int]:
    """Lista usuários premium"""
    try:
        rows = await sb_select(TABLE_USERS, "?select=user_id")
        return [r["user_id"] for r in rows if "user_id" in r]
    except:
        return []

async def get_stats() -> Dict:
    """Estatísticas"""
    try:
        keys = await sb_select(TABLE_KEYS, "")
        users = await sb_select(TABLE_USERS, "")
        
        total_keys = len(keys)
        used_keys = len([k for k in keys if k.get("used")])  # V1 usa 'used'
        
        return {
            "total_keys": total_keys,
            "used_keys": used_keys,
            "available_keys": total_keys - used_keys,
            "total_users": len(users),
            "total_videos": len(MEDIA_CACHE)
        }
    except:
        return {}

# ============================================================
# ENVIO DE VÍDEOS
# ============================================================

async def enviar_lote_videos(user_id: int, context: ContextTypes.DEFAULT_TYPE, lang: str):
    """Envia lote com loading"""
    try:
        pos = USER_VIDEO_POSITION.get(user_id, 0)
        
        if pos >= len(MEDIA_CACHE):
            msg = tr(
                lang,
                "✅ <b>Todos os vídeos foram enviados!</b>\n\n💎 Aproveite!",
                "✅ <b>All videos sent!</b>\n\n💎 Enjoy!",
                "✅ <b>¡Todos los videos enviados!</b>\n\n💎 ¡Disfruta!"
            )
            await context.bot.send_message(user_id, msg, parse_mode="HTML")
            return
        
        # Loading
        await mostrar_loading(
            user_id,
            context,
            TEXTOS["loading_videos"][lang],
            TEXTOS["videos_sent"][lang],
            duracao=2.0
        )
        
        # Envia vídeos
        fim = min(pos + VIDEOS_POR_LOTE, len(MEDIA_CACHE))
        enviados = 0
        
        for i in range(pos, fim):
            media = MEDIA_CACHE[i]
            try:
                if media["tipo"] == "video":
                    await context.bot.send_video(
                        chat_id=user_id,
                        video=media["file_id"],
                        protect_content=PROTECT_CONTENT,
                    )
                elif media["tipo"] == "photo":
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=media["file_id"],
                        protect_content=PROTECT_CONTENT,
                    )
                enviados += 1
                await asyncio.sleep(SEND_DELAY_SECONDS)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                logger.error(f"Erro ao enviar: {e}")
        
        USER_VIDEO_POSITION[user_id] = fim
        
        # Pergunta se quer mais
        if fim < len(MEDIA_CACHE):
            restantes = len(MEDIA_CACHE) - fim
            msg = tr(
                lang,
                f"📦 <b>{enviados} vídeos enviados!</b>\n\n"
                f"📊 Restam <b>{restantes} vídeos</b>\n\n"
                f"💎 Continuar?",
                f"📦 <b>{enviados} videos sent!</b>\n\n"
                f"📊 <b>{restantes} videos</b> remaining\n\n"
                f"💎 Continue?",
                f"📦 <b>¡{enviados} videos enviados!</b>\n\n"
                f"📊 Quedan <b>{restantes} videos</b>\n\n"
                f"💎 ¿Continuar?"
            )
            await context.bot.send_message(
                user_id,
                msg,
                parse_mode="HTML",
                reply_markup=continuar_keyboard(lang)
            )
        else:
            msg = tr(
                lang,
                "🎉 <b>PARABÉNS!</b>\n\nTodos os vídeos enviados!",
                "🎉 <b>CONGRATULATIONS!</b>\n\nAll videos sent!",
                "🎉 <b>¡FELICITACIONES!</b>\n\n¡Todos los videos enviados!"
            )
            await context.bot.send_message(user_id, msg, parse_mode="HTML")
    
    except Exception as e:
        logger.error(f"Erro no envio: {e}")

# ============================================================
# HANDLERS
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    lang = LANG_PREF_CACHE.get(user.id) or await get_lang_pref(user.id)
    
    # Admin
    if user.id == ADMIN_ID:
        if not lang:
            lang = "pt"
            LANG_PREF_CACHE[user.id] = lang
            await set_lang_pref(user.id, lang)
        
        kb = get_admin_menu_keyboard(lang)
        msg = tr(
            lang,
            "⭐ <b>PAINEL ADMIN</b>\n\n"
            "📥 Envie vídeos para catalogar automaticamente!\n\n"
            "Use o teclado:",
            "⭐ <b>ADMIN PANEL</b>\n\n"
            "📥 Send videos to catalog automatically!\n\n"
            "Use keyboard:",
            "⭐ <b>PANEL ADMIN</b>\n\n"
            "📥 ¡Envía videos para catalogar!\n\n"
            "Usa el teclado:"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return
    
    # Usuário sem idioma
    if not lang:
        await update.message.reply_text(
            TEXTOS["welcome_msg"]["pt"],
            parse_mode="HTML",
            reply_markup=language_picker_markup()
        )
        return
    
    LANG_PREF_CACHE[user.id] = lang
    is_premium = await is_premium_user(user.id)
    
    if is_premium:
        msg = tr(
            lang,
            "💎 <b>BEM-VINDO!</b>\n\n✅ Acesso PREMIUM ativo\n🎬 Pronto?",
            "💎 <b>WELCOME!</b>\n\n✅ PREMIUM access active\n🎬 Ready?",
            "💎 <b>¡BIENVENIDO!</b>\n\n✅ Acceso PREMIUM activo\n🎬 ¿Listo?"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                tr(lang, "📥 RECEBER VÍDEOS", "📥 GET VIDEOS", "📥 RECIBIR VIDEOS"),
                callback_data="continuar_sim"
            )]
        ])
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=keyboard)
    else:
        msg = tr(
            lang,
            "💎 <b>ACESSO PREMIUM</b>\n\n🎬 Conteúdo exclusivo!\n🔑 Ative sua chave:",
            "💎 <b>PREMIUM ACCESS</b>\n\n🎬 Exclusive content!\n🔑 Activate key:",
            "💎 <b>ACCESO PREMIUM</b>\n\n🎬 ¡Contenido exclusivo!\n🔑 Activa clave:"
        )
        await update.message.reply_text(
            msg,
            parse_mode="HTML",
            reply_markup=painel_inicial_keyboard(lang)
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stats admin"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    stats = await get_stats()
    msg = (
        "📊 <b>ESTATÍSTICAS</b>\n\n"
        f"🔑 Chaves: {stats.get('total_keys', 0)}\n"
        f"✅ Usadas: {stats.get('used_keys', 0)}\n"
        f"🆓 Disponíveis: {stats.get('available_keys', 0)}\n"
        f"👥 Usuários: {stats.get('total_users', 0)}\n"
        f"🎬 Vídeos: {stats.get('total_videos', 0)}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data="bc_confirm")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="bc_cancel")],
    ])
    await update.message.reply_text(
        "📣 <b>Broadcast</b>\n\nEnviar para TODOS?",
        parse_mode="HTML",
        reply_markup=kb,
    )

async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    CATALOGAÇÃO AUTOMÁTICA
    Admin envia → Bot salva automaticamente
    """
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        return
    
    lang = LANG_PREF_CACHE.get(user.id, "pt")
    
    try:
        logger.info(f"📹 Admin enviou mídia")
        
        file_id = None
        tipo = None
        
        if update.message.video:
            file_id = update.message.video.file_id
            tipo = "video"
        elif update.message.photo:
            file_id = update.message.photo[-1].file_id
            tipo = "photo"
        
        if not file_id:
            return
        
        # Verifica cache
        if any(m["file_id"] == file_id for m in MEDIA_CACHE):
            await update.message.reply_text("⚠️ Já catalogado!")
            return
        
        # Salva
        success = await save_media_to_db(file_id, tipo)
        
        if success:
            MEDIA_CACHE.append({"file_id": file_id, "tipo": tipo})
            
            msg = tr(
                lang,
                f"✅ <b>{tipo.upper()} CATALOGADO!</b>\n\n📊 Total: {len(MEDIA_CACHE)}",
                f"✅ <b>{tipo.upper()} CATALOGED!</b>\n\n📊 Total: {len(MEDIA_CACHE)}",
                f"✅ <b>¡{tipo.upper()} CATALOGADO!</b>\n\n📊 Total: {len(MEDIA_CACHE)}"
            )
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Erro ao catalogar")
    
    except Exception as e:
        logger.error(f"❌ Erro: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"❌ Erro: {type(e).__name__}")

async def handle_other_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Outros tipos"""
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("⚠️ Apenas vídeos e fotos")

async def text_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu texto"""
    user = update.effective_user
    text = update.message.text
    
    # Usuário ativando chave
    if user.id != ADMIN_ID:
        if PENDING_KEY_ACTIVATION.get(user.id):
            lang = LANG_PREF_CACHE.get(user.id, "pt")
            
            await mostrar_loading(
                user.id,
                context,
                TEXTOS["loading_key"][lang],
                "",
                duracao=1.5
            )
            
            is_valid = await validate_and_use_key(text.strip(), user.id)
            
            if is_valid:
                PENDING_KEY_ACTIVATION[user.id] = False
                USER_VIDEO_POSITION[user.id] = 0
                
                await context.bot.send_message(
                    user.id,
                    TEXTOS["key_approved"][lang],
                    parse_mode="HTML"
                )
                await enviar_lote_videos(user.id, context, lang)
            else:
                msg = tr(
                    lang,
                    "❌ <b>CHAVE INVÁLIDA</b>\n\n⚠️ Verifique",
                    "❌ <b>INVALID KEY</b>\n\n⚠️ Check",
                    "❌ <b>CLAVE INVÁLIDA</b>\n\n⚠️ Verifica"
                )
                await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    # Admin
    lang = LANG_PREF_CACHE.get(user.id, "pt")
    L = MENU.get(lang, MENU["pt"])
    
    # Broadcast collecting
    if context.user_data.get("broadcast_collecting"):
        buf = context.user_data.get("broadcast_buffer", [])
        buf.append({
            "from_chat_id": update.message.chat_id,
            "message_id": update.message.message_id,
        })
        context.user_data["broadcast_buffer"] = buf
        await update.message.reply_text(f"✅ Msg #{len(buf)} adicionada")
        return
    
    # Gerar chave
    if text == L["gen_key"]:
        key = await generate_premium_key()
        msg = tr(
            lang,
            f"🔑 <b>CHAVE GERADA!</b>\n\n<code>{key}</code>\n\n📋 Copiar",
            f"🔑 <b>KEY GENERATED!</b>\n\n<code>{key}</code>\n\n📋 Copy",
            f"🔑 <b>¡CLAVE GENERADA!</b>\n\n<code>{key}</code>\n\n📋 Copiar"
        )
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    # Listar chaves
    if text == L["list_keys"]:
        keys = await get_all_premium_keys()
        if not keys:
            await update.message.reply_text("⚠️ Sem chaves")
            return
        
        msg = "📋 <b>CHAVES</b>\n\n"
        for k in keys[:20]:
            status = "✅ Usada" if k.get("used") else "🆓 Livre"
            msg += f"<code>{k['key_code']}</code> - {status}\n"
        
        if len(keys) > 20:
            msg += f"\n... +{len(keys)-20}"
        
        await update.message.reply_text(msg, parse_mode="HTML")
        return
    
    if text == L["stats"]:
        await stats_command(update, context)
        return
    
    if text == L["broadcast"]:
        await broadcast_command(update, context)
        return
    
    if text == L["lang"]:
        await update.message.reply_text(
            "🌐 Idioma:",
            reply_markup=language_picker_markup()
        )
        return

async def callbacks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callbacks"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    user = query.from_user
    data = query.data
    
    # Idioma
    if data.startswith("setlang_"):
        new_lang = data.replace("setlang_", "")
        LANG_PREF_CACHE[user.id] = new_lang
        await set_lang_pref(user.id, new_lang)
        
        if user.id == ADMIN_ID:
            try:
                await query.edit_message_text("✅ Idioma alterado!")
            except:
                pass
            kb = get_admin_menu_keyboard(new_lang)
            await context.bot.send_message(
                user.id,
                "⭐ <b>ADMIN</b>",
                parse_mode="HTML",
                reply_markup=kb
            )
        else:
            is_premium = await is_premium_user(user.id)
            
            if is_premium:
                msg = tr(new_lang, "💎 Pronto!", "💎 Ready!", "💎 ¡Listo!")
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        tr(new_lang, "📥 VÍDEOS", "📥 VIDEOS", "📥 VIDEOS"),
                        callback_data="continuar_sim"
                    )
                ]])
            else:
                msg = tr(new_lang, "💎 Ative chave:", "💎 Activate key:", "💎 Activa clave:")
                keyboard = painel_inicial_keyboard(new_lang)
            
            try:
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=keyboard)
            except:
                pass
        return
    
    lang = LANG_PREF_CACHE.get(user.id) or await get_lang_pref(user.id) or "pt"
    LANG_PREF_CACHE[user.id] = lang
    
    # Ativar chave
    if data == "ativar_chave":
        msg = tr(
            lang,
            "🔑 <b>ATIVAR CHAVE</b>\n\n1️⃣ Digite chave\n2️⃣ Envie",
            "🔑 <b>ACTIVATE KEY</b>\n\n1️⃣ Type key\n2️⃣ Send",
            "🔑 <b>ACTIVAR CLAVE</b>\n\n1️⃣ Escribe\n2️⃣ Envía"
        )
        PENDING_KEY_ACTIVATION[user.id] = True
        await query.edit_message_text(msg, parse_mode="HTML")
        return
    
    # Continuar
    if data == "continuar_sim":
        await mostrar_loading(
            user.id,
            context,
            TEXTOS["loading_videos"][lang],
            "",
            duracao=1.5
        )
        await enviar_lote_videos(user.id, context, lang)
        return
    
    # Parar
    if data == "continuar_nao":
        msg = tr(lang, "✅ Ok! Use /start", "✅ Ok! Use /start", "✅ ¡Ok! Usa /start")
        await query.edit_message_text(msg, parse_mode="HTML")
        return
    
    # Broadcast confirm
    if data == "bc_confirm" and user.id == ADMIN_ID:
        context.user_data["broadcast_collecting"] = True
        context.user_data["broadcast_buffer"] = []
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Enviar", callback_data="bc_send")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="bc_cancel")],
        ])
        try:
            await query.edit_message_text(
                "📣 <b>Modo broadcast</b>\n\nEnvie mensagens. Depois clique ✅",
                parse_mode="HTML",
                reply_markup=kb,
            )
        except:
            pass
        return
    
    # Broadcast cancel
    if data == "bc_cancel" and user.id == ADMIN_ID:
        context.user_data.pop("broadcast_collecting", None)
        context.user_data.pop("broadcast_buffer", None)
        try:
            await query.edit_message_text("❌ Cancelado")
        except:
            pass
        return
    
    # Broadcast send
    if data == "bc_send" and user.id == ADMIN_ID:
        buf = context.user_data.get("broadcast_buffer") or []
        if not buf:
            try:
                await query.edit_message_text("⚠️ Sem mensagens")
            except:
                pass
            return
        
        target_ids = await get_all_premium_users()
        
        if not target_ids:
            try:
                await query.edit_message_text("⚠️ Sem usuários")
            except:
                pass
            context.user_data.pop("broadcast_collecting", None)
            context.user_data.pop("broadcast_buffer", None)
            return
        
        try:
            await query.edit_message_text(
                f"📤 Enviando...\n\n👥 {len(target_ids)} usuários",
                parse_mode="HTML"
            )
        except:
            pass
        
        ok = 0
        fail = 0
        for uid in target_ids:
            try:
                for msg_data in buf:
                    await context.bot.copy_message(
                        chat_id=uid,
                        from_chat_id=msg_data["from_chat_id"],
                        message_id=msg_data["message_id"],
                        protect_content=PROTECT_CONTENT,
                    )
                    await asyncio.sleep(0.05)
                ok += 1
            except:
                fail += 1
            await asyncio.sleep(0.1)
        
        context.user_data.pop("broadcast_collecting", None)
        context.user_data.pop("broadcast_buffer", None)
        
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"✅ <b>Concluído!</b>\n\n👍 {ok}\n❌ {fail}",
                parse_mode="HTML",
            )
        except:
            pass
        return

# ============================================================
# FLASK
# ============================================================

app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return jsonify({
        "status": "online",
        "bot": "premium_v2_compativel_v1",
        "total_videos": len(MEDIA_CACHE),
        "version": "2.0-v1-compat"
    })

def run_flask_server():
    port = int(os.getenv("PORT", "8000") or "8000")
    serve(app_flask, host="0.0.0.0", port=port)

# ============================================================
# MAIN
# ============================================================

async def carregar_dados():
    """Carrega dados"""
    try:
        MEDIA_CACHE[:] = await load_media_from_db()
        logger.info(f"✅ Vídeos: {len(MEDIA_CACHE)}")
    except Exception as e:
        logger.error(f"❌ Erro: {e}")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(carregar_dados())
    
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("stats", stats_command))
    bot_app.add_handler(CommandHandler("broadcast", broadcast_command))
    
    bot_app.add_handler(CallbackQueryHandler(callbacks_handler))
    bot_app.add_handler(MessageHandler(filters.VIDEO | filters.PHOTO, handle_media_upload))
    bot_app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.Sticker.ALL, handle_other_media))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_menu_handler))
    
    threading.Thread(target=run_flask_server, daemon=True).start()
    
    logger.info("🚀 Bot Premium V2 (Compatível V1) Iniciado!")
    logger.info(f"✅ Usando tabelas: {TABLE_VIDEOS}, {TABLE_KEYS}, {TABLE_USERS}")
    logger.info("✅ Sistema de idiomas (PT/EN/ES)")
    logger.info("✅ Barra de progresso animada")
    logger.info("✅ Catalogação automática")
    
    bot_app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
