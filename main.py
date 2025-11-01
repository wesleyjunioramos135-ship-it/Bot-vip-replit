# -*- coding: utf-8 -*-

# =========================================================================================
# ||| BOT VIP - VERSÃO FINAL v11.0 (SISTEMA DE ASSINATURA VIP) |||
# =========================================================================================

import os
import json
import asyncio
import logging
import random 
from datetime import datetime, timedelta # Nova importação
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÃO (NÃO ALTERADA) ---
logging.basicConfig(format='%(asctime)ss - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = 8154517116
DB_FILE = "catalogo_videos.txt"
ARQUIVO_VIP_STATUS = "vip_status.json" # NOVO ARQUIVO
ARQUIVO_USER_DATA = "user_data.json"
ARQUIVO_ESTEIRA_STATUS = "esteira_status.json" 
PACOTE = 10
PAUSA_ENTRE_VIDEOS = 1.5
PAUSA_ENTRE_PACOTES = 5
URL_DA_IMAGEM_BANNER = "https://i.postimg.cc/pXk0zVv7/premium-banner.png"
SEU_LINK_DE_CONTATO = "https://t.me/seu_username_aqui"

# --- VARIÁVEIS GLOBAIS (REINTRODUZIDAS) ---
grupos_processados = set()
esteira_rodando = {} # True: rodando, False: pausado

# --- FUNÇÕES DE GERENCIAMENTO DE DADOS (ADICIONADAS PERSISTÊNCIA) ---
def verificar_e_criar_arquivos():
    for filename in [DB_FILE, ARQUIVO_USER_DATA, ARQUIVO_ESTEIRA_STATUS]:
        if not os.path.exists(filename):
            if filename.endswith('.json'):
                with open(filename, 'w') as f: json.dump({}, f)
            else:
                with open(filename, 'w') as f: pass
            logger.info(f"Arquivo '{filename}' criado.")
    
    # NOVO: Verifica e cria o arquivo vip_status.json
    if not os.path.exists(ARQUIVO_VIP_STATUS):
        with open(ARQUIVO_VIP_STATUS, 'w') as f: json.dump({}, f)
        logger.info(f"Arquivo '{ARQUIVO_VIP_STATUS}' criado.")

def carregar_vip_status():
    with open(ARQUIVO_VIP_STATUS, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def salvar_vip_status(data):
    with open(ARQUIVO_VIP_STATUS, 'w') as f:
        json.dump(data, f, indent=4)

def carregar_ids_dos_videos():
    if not os.path.exists(DB_FILE): return []
    with open(DB_FILE, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def carregar_user_data():
    with open(ARQUIVO_USER_DATA, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def salvar_user_data(data):
    with open(ARQUIVO_USER_DATA, 'w') as f:
        json.dump(data, f, indent=4)

def atualizar_user_data(user):
    if user and user.username:
        data = carregar_user_data()
        data[user.username.lower()] = user.id
        salvar_user_data(data)

def carregar_esteira_status():
    global esteira_rodando
    with open(ARQUIVO_ESTEIRA_STATUS, 'r') as f:
        try:
            status = json.load(f)
            # Converte chaves de string para int, pois IDs de usuário são int
            esteira_rodando = {int(k): v for k, v in status.items()}
        except json.JSONDecodeError:
            esteira_rodando = {}

def salvar_esteira_status():
    with open(ARQUIVO_ESTEIRA_STATUS, 'w') as f:
        # Converte chaves de int para string para salvar em JSON
        json.dump({str(k): v for k, v in esteira_rodando.items()}, f, indent=4)

# --- FUNÇÕES DE VERIFICAÇÃO (ALTERADA PARA VERIFICAR EXPIRAÇÃO) ---
def is_admin(user_id: int) -> bool: return user_id == ADMIN_ID

def is_vip(user_id: int, username: str) -> bool:
    if is_admin(user_id): return True
    if not username: return False
    
    vip_status = carregar_vip_status()
    username_lower = username.lower()
    
    if username_lower not in vip_status:
        return False
    
    expiration_date_str = vip_status[username_lower]
    expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
    
    if datetime.now() < expiration_date:
        return True
    else:
        # Opcional: Remover o usuário expirado
        # del vip_status[username_lower]
        # salvar_vip_status(vip_status)
        return False

# --- COMANDOS PARA O ADMIN (ADAPTADO PARA NOVA LÓGICA VIP) ---
async def admin_salva_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id): return
    file_id_novo = None
    
    # Lógica para processar álbuns (grupos de mídia)
    if update.message.media_group_id:
        if update.message.media_group_id in grupos_processados: return
        grupos_processados.add(update.message.media_group_id)
        context.job_queue.run_once(lambda ctx: grupos_processados.remove(update.message.media_group_id), 5)
        await asyncio.sleep(2)
        try:
            group_messages = await context.bot.get_media_group(chat_id=update.message.chat_id, message_id=update.message.message_id)
            novos, existentes = 0, 0; lista_atual = carregar_ids_dos_videos()
            
            novos_videos_ids = []
            
            with open(DB_FILE, 'a') as f:
                for msg in group_messages:
                    if msg.video:
                        file_id = msg.video.file_id
                        if file_id not in lista_atual: 
                            f.write(file_id + "\n")
                            lista_atual.append(file_id)
                            novos_videos_ids.append(file_id)
                            novos += 1
                        else: 
                            existentes += 1
                            
            await update.message.reply_text(f"Álbum processado!\n✅ {novos} novos vídeos catalogados.\nℹ️ {existentes} já estavam no catálogo.")
            
            # Envio Contínuo para todos os VIPs que NÃO ESTÃO PAUSADOS
            if novos_videos_ids:
                user_data = carregar_user_data()
                vip_status = carregar_vip_status()
                
                for vip_username in vip_status.keys():
                    user_id = user_data.get(vip_username)
                    # Verifica se o ID existe, se é VIP (por data) e se a esteira NÃO está pausada
                    if user_id and is_vip(user_id, vip_username) and esteira_rodando.get(user_id, True): 
                        try:
                            await context.bot.send_message(chat_id=user_id, text="🔥 **Novo conteúdo AO VIVO!** Chegando para você...")
                            for video_id in novos_videos_ids:
                                await context.bot.send_video(chat_id=user_id, video=video_id)
                                await asyncio.sleep(PAUSA_ENTRE_VIDEOS)
                            logger.info(f"Enviado {len(novos_videos_ids)} vídeos 'Contínuos' para o usuário {user_id}")
                        except Exception as e: 
                            logger.error(f"Falha ao enviar conteúdo 'Contínuo' para {user_id}: {e}")
                        
        except Exception as e: 
            logger.error(f"Erro ao processar álbum: {e}")
            await update.message.reply_text("❌ Ocorreu um erro ao processar o lote.")
            
    # Lógica para processar vídeo único
    elif update.message.video:
        file_id = update.message.video.file_id
        lista_atual = carregar_ids_dos_videos()
        if file_id not in lista_atual:
            with open(DB_FILE, 'a') as f: f.write(file_id + "\n")
            await update.message.reply_text(f"✅ Vídeo #{len(lista_atual) + 1} catalogado!")
            file_id_novo = file_id
        else: 
            await update.message.reply_text("ℹ️ Este vídeo já estava no catálogo.")
            
    # Envio Contínuo para todos os VIPs que NÃO ESTÃO PAUSADOS
    if file_id_novo:
        user_data = carregar_user_data()
        vip_status = carregar_vip_status()
        
        for vip_username in vip_status.keys():
            user_id = user_data.get(vip_username)
            # Verifica se o ID existe, se é VIP (por data) e se a esteira NÃO está pausada
            if user_id and is_vip(user_id, vip_username) and esteira_rodando.get(user_id, True): 
                try:
                    await context.bot.send_message(chat_id=user_id, text="🔥 **Novo conteúdo AO VIVO!** Chegando para você...")
                    await context.bot.send_video(chat_id=user_id, video=file_id_novo)
                    logger.info(f"Enviado conteúdo 'Contínuo' para o usuário {user_id}")
                except Exception as e: 
                    logger.error(f"Falha ao enviar conteúdo 'Contínuo' para {user_id}: {e}")


async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    atualizar_user_data(update.message.from_user)
    if not is_admin(update.message.from_user.id): return
    try:
        username_to_add = context.args[0].replace('@', '').lower()
        vip_status = carregar_vip_status()
        
        # Define a data de expiração (30 dias a partir de agora)
        expiration_date = datetime.now() + timedelta(days=30)
        expiration_date_str = expiration_date.strftime('%Y-%m-%d')
        
        vip_status[username_to_add] = expiration_date_str
        salvar_vip_status(vip_status)
        
        await update.message.reply_text(f"✅ Usuário @{username_to_add} adicionado à lista VIP!\nExpira em: {expiration_date_str}")
        
        user_data = carregar_user_data()
        if username_to_add in user_data:
            user_id_to_notify = user_data[username_to_add]
            try: await context.bot.send_message(chat_id=user_id_to_notify, text=f"🎉 **Você foi adicionado ao grupo VIP!**\n\nSeu acesso expira em **{expiration_date_str}**.\nUse /videos para começar a receber o conteúdo.")
            except Exception as e: logger.warning(f"Falha ao notificar @{username_to_add} sobre a adição: {e}")
        else: await context.bot.send_message(chat_id=update.message.chat_id, text=f"🔔 Lembrete: Peça para @{username_to_add} enviar /start ao bot para que ele possa receber notificações.")
        
    except IndexError: await update.message.reply_text("⚠️ Uso: /adduser @username")

async def removeuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    atualizar_user_data(update.message.from_user)
    if not is_admin(update.message.from_user.id): return
    try:
        username_to_remove = context.args[0].replace('@', '').lower()
        vip_status = carregar_vip_status()
        
        if username_to_remove in vip_status:
            user_data = carregar_user_data()
            user_id_to_remove = user_data.get(username_to_remove)
            
            # Notifica o usuário
            if user_id_to_remove:
                try:
                    mensagem_remocao = "🚫 **Seu acesso VIP foi revogado.**\n\nPara voltar a ver os conteúdos, entre em contato com o administrador."
                    await context.bot.send_message(chat_id=user_id_to_remove, text=mensagem_remocao)
                except Exception as e: logger.warning(f"Falha ao notificar @{username_to_remove} sobre a remoção: {e}")
            
            # Remove do status VIP
            del vip_status[username_to_remove]
            salvar_vip_status(vip_status)
            
            await update.message.reply_text(f"✅ Usuário @{username_to_remove} removido da lista VIP!")
            
            # Remove o status da esteira
            if user_id_to_remove in esteira_rodando:
                del esteira_rodando[user_id_to_remove]
                salvar_esteira_status()
        else: await update.message.reply_text(f"ℹ️ Usuário @{username_to_remove} não encontrado na lista VIP.")
    except IndexError: await update.message.reply_text("⚠️ Uso: /removeuser @username")

async def vermembros_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    atualizar_user_data(update.message.from_user)
    if not is_admin(update.message.from_user.id): return
    
    vip_status = carregar_vip_status()
    clientes_vip = sorted(vip_status.keys())
    
    if not clientes_vip: await update.message.reply_text("ℹ️ Não há membros VIP cadastrados."); return
    
    mensagem = "👑 **Lista de Membros VIP** 👑\n\n"
    for i, vip_username in enumerate(clientes_vip, 1): 
        exp_date_str = vip_status[vip_username]
        exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d')
        dias_restantes = (exp_date - datetime.now()).days
        
        status = f"Expira em: {exp_date_str}"
        if dias_restantes < 0: status = "EXPIRADO 🚫"
        elif dias_restantes == 0: status = "EXPIRA HOJE ⚠️"
        elif dias_restantes == 1: status = "Falta 1 dia"
        else: status = f"Faltam {dias_restantes} dias"
        
        mensagem += f"{i}. `@{vip_username}` - {status}\n"
        
    mensagem += f"\nTotal: **{len(clientes_vip)}** membro(s) VIP."
    await update.message.reply_text(mensagem, parse_mode='Markdown')

# NOVO COMANDO: /status
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    atualizar_user_data(user)
    
    if is_admin(user.id):
        await update.message.reply_text("👑 Você é o Administrador. Seu acesso é permanente.")
        return
    
    vip_status = carregar_vip_status()
    username_lower = user.username.lower()
    
    if username_lower not in vip_status:
        await update.message.reply_text("🚫 Você não é um membro VIP. Use /start para saber como ter acesso.")
        return
    
    expiration_date_str = vip_status[username_lower]
    expiration_date = datetime.strptime(expiration_date_str, '%Y-%m-%d')
    dias_restantes = (expiration_date - datetime.now()).days
    
    if dias_restantes < 0:
        await update.message.reply_text("🚫 **Seu acesso VIP expirou.** Entre em contato com o administrador para renovar.")
    elif dias_restantes == 0:
        await update.message.reply_text("⚠️ **Seu acesso VIP expira hoje!** Entre em contato com o administrador para renovar.")
    else:
        await update.message.reply_text(f"✅ **Seu acesso VIP está ativo!**\n\nFaltam **{dias_restantes}** dias para a expiração ({expiration_date_str}).")


# --- COMANDOS PARA OS USUÁRIOS (ADAPTADO PARA NOVA LÓGICA VIP) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    atualizar_user_data(user)
    if is_vip(user.id, user.username):
        await update.message.reply_text("Olá, Membro VIP! 👋\n\nUse /videos para receber nosso conteúdo.\nUse /parar para pausar e /retomar para continuar a qualquer momento.\nUse /status para verificar a validade do seu acesso.")
    else:
        texto_boas_vindas = ("**Este bot gerencia vários grupos e os conteúdos são atualizados 24 horas.**\n\n"
            "Todo vídeo que cai lá no grupo, cai aqui automaticamente. Essa foi a maneira que consegui criar um grupo sem tomar Ban.\n\n"
            "Clique abaixo para saber como ter acesso.")
        keyboard = [[InlineKeyboardButton("💎 Quero Ser VIP 💎", callback_data="quero_vip")]]
        await context.bot.send_photo(chat_id=user.id, photo=URL_DA_IMAGEM_BANNER, caption=texto_boas_vindas, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    atualizar_user_data(user)
    if not is_vip(user.id, user.username): await update.message.reply_text("🚫 Acesso negado. Seu acesso VIP pode ter expirado. Use /status para verificar."); return
    
    # Mensagem de início personalizada
    await context.bot.send_message(chat_id=user.id, text="acesso reconhecido!!🎂. Abaixo tem os vídeos de todos os grupos conectado a esse bot. Mais de 2000000📷 e os conteúdos são atualizados 24 horas por dia⏳ ao vivo aproveite o vip👑😁", parse_mode='Markdown')
    
    # Inicia o envio da esteira inicial (todos os vídeos antigos)
    if not esteira_rodando.get(user.id):
        esteira_rodando[user.id] = True
        salvar_esteira_status()
        asyncio.create_task(rodar_esteira_inicial(user.id, user.username, context))
    else:
        await context.bot.send_message(chat_id=user.id, text="ℹ️ A rolagem já está ativa. Use /parar para pausar.")

async def parar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    atualizar_user_data(user)
    if not is_vip(user.id, user.username): await update.message.reply_text("🚫 Acesso negado. Seu acesso VIP pode ter expirado. Use /status para verificar."); return
    
    if esteira_rodando.get(user.id):
        esteira_rodando[user.id] = False
        salvar_esteira_status()
        await update.message.reply_text("⏸️ Rolagem pausada. Você não receberá novos vídeos 'Ao Vivo' até usar /retomar.")
    else:
        await update.message.reply_text("ℹ️ A rolagem já estava pausada.")

async def retomar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    atualizar_user_data(user)
    if not is_vip(user.id, user.username): await update.message.reply_text("🚫 Acesso negado. Seu acesso VIP pode ter expirado. Use /status para verificar."); return
    
    if not esteira_rodando.get(user.id):
        esteira_rodando[user.id] = True
        salvar_esteira_status()
        await update.message.reply_text("▶️ Rolagem retomada! Você voltará a receber os vídeos 'Ao Vivo' e a rolagem continuará de forma aleatória.")
        # Se a esteira não estava rodando, precisa ser reiniciada (o loop infinito cuida disso)
        asyncio.create_task(rodar_esteira_inicial(user.id, user.username, context))
    else:
        await update.message.reply_text("ℹ️ A rolagem já estava ativa.")

async def rodar_esteira_inicial(user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE):
    
    # Loop Infinito para garantir que o cliente sempre receba vídeos
    while True:
        # Verifica se o usuário pausou a rolagem ou se o acesso expirou
        if not esteira_rodando.get(user_id) or not is_vip(user_id, username):
            # Se pausado ou expirado, espera um tempo e verifica novamente
            await asyncio.sleep(10) 
            continue

        lista_de_videos = carregar_ids_dos_videos()
        
        if not lista_de_videos:
            await context.bot.send_message(chat_id=user_id, text="ℹ️ O catálogo está vazio. Aguardando novos vídeos para iniciar a rolagem.")
            await asyncio.sleep(60) # Espera 1 minuto antes de tentar recarregar a lista
            continue
        
        # Embaralha a lista de vídeos a cada ciclo
        random.shuffle(lista_de_videos)
        total_videos = len(lista_de_videos)
        
        try:
            for i in range(total_videos):
                # Verifica se o usuário pausou durante a rolagem ou se o acesso expirou
                if not esteira_rodando.get(user_id) or not is_vip(user_id, username): 
                    return # Interrompe se pausado ou não for mais VIP
                
                video_id = lista_de_videos[i]
                await context.bot.send_video(chat_id=user_id, video=video_id)
                await asyncio.sleep(PAUSA_ENTRE_VIDEOS)
                
                if (i + 1) % PACOTE == 0 and (i + 1) < total_videos:
                    await context.bot.send_message(chat_id=user_id, text="Pausa para evitar spam... os vídeos continuam rodando ao vivo direto dos grupos.")
                    await asyncio.sleep(PAUSA_ENTRE_PACOTES)
                    
            # A rolagem continua de forma invisível
            logger.info(f"Fim do ciclo de rolagem para {user_id}. Reiniciando o loop.")
            
        except Exception as e:
            logger.error(f"Erro na esteira inicial para {user_id}: {e}")
            if esteira_rodando.get(user_id):
                await context.bot.send_message(chat_id=user_id, text="❌ Ocorreu um erro durante a rolagem. Tentando reiniciar em 1 minuto.")
                await asyncio.sleep(60) # Espera 1 minuto em caso de erro
        finally:
            pass # Não há mais controle de estado global

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "quero_vip":
        texto_instrucoes = ("🔑 **Como Obter seu Acesso VIP:**\n\n"
            "É muito simples! Para se tornar um membro, entre em contato com nosso administrador através do link abaixo para receber as instruções.")
        keyboard = [[InlineKeyboardButton("📲 Contatar Administrador", url=SEU_LINK_DE_CONTATO)]]
        await query.edit_message_caption(caption=texto_instrucoes, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

# --- CÓDIGO DO SERVIDOR WEB (NÃO ALTERADO) ---
app_flask = Flask(__name__)
@app_flask.route('/')
def index(): return "Bot VIP está ativo!"
def run_flask(): app_flask.run(host='0.0.0.0', port=8080)

# --- FUNÇÃO PRINCIPAL QUE INICIA TUDO (COM REINÍCIO AUTOMÁTICO) ---
def main():
    verificar_e_criar_arquivos()
    carregar_esteira_status() # Carrega o estado da esteira
    
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    logger.info("Iniciando bot (Versão Final v11.0)...")
    app = Application.builder().token(TOKEN).build()
    
    # Comandos de Usuário
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("videos", videos_command))
    app.add_handler(CommandHandler("parar", parar_command)) 
    app.add_handler(CommandHandler("retomar", retomar_command)) 
    app.add_handler(CommandHandler("status", status_command)) # NOVO COMANDO
    
    # Comandos de Admin
    app.add_handler(CommandHandler("adduser", adduser_command))
    app.add_handler(CommandHandler("removeuser", removeuser_command))
    app.add_handler(CommandHandler("vermenbros", vermembros_command))
    app.add_handler(MessageHandler(filters.VIDEO & ~filters.COMMAND, admin_salva_video))
    
    # Callback de Botão
    app.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("Bot em funcionamento!")
    app.run_polling()

if __name__ == '__main__':
    main()
