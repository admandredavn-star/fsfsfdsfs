import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
import os
from dotenv import load_dotenv
from typing import Optional, Dict, List
from datetime import datetime
import io
import html

# Carrega variáveis de ambiente
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Configurações do bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.db_lock = asyncio.Lock()
        self.active_tickets: Dict[str, dict] = {}
        self.configs: dict = {}
        self.panel_message_id: Optional[int] = None
        self.panel_channel_id: Optional[int] = None
        
    async def setup_hook(self):
        await self.load_data()
        await self.tree.sync()
        print(f"✅ Bot sincronizado com {len(self.tree.get_commands())} comandos")
        
    async def load_data(self):
        """Carrega dados do arquivo JSON"""
        try:
            with open('ticket_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.configs = data.get('configs', {})
                self.active_tickets = data.get('tickets', {})
        except FileNotFoundError:
            self.configs = {
                'ticket_categories': {
                    'suporte': {'name': '🛠️ Suporte', 'emoji': '🛠️', 'description': 'Dúvidas ou ajuda geral'},
                    'reembolso': {'name': '💰 Reembolso', 'emoji': '💰', 'description': 'Solicitações de reembolso'},
                    'evento': {'name': '📦 Receber Evento', 'emoji': '📦', 'description': 'Entrega de eventos/prêmios'},
                    'mediador': {'name': '👥 Vagas Mediadores', 'emoji': '👥', 'description': 'Candidatura a mediador'}
                }
            }
            await self.save_data()
    
    async def save_data(self):
        """Salva dados no arquivo JSON"""
        async with self.db_lock:
            data = {
                'configs': self.configs,
                'tickets': self.active_tickets
            }
            with open('ticket_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

bot = TicketBot()

# Views e Componentes

class ConfigView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
        
    @discord.ui.select(
        placeholder="Selecione os cargos de staff",
        custom_id="config_staff_select",
        min_values=1,
        max_values=25,
        row=0
    )
    async def staff_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        staff_roles = [int(role_id) for role_id in select.values]
        self.bot.configs['staff_roles'] = staff_roles
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Cargos de staff definidos: {len(staff_roles)} cargos", ephemeral=True)
    
    @discord.ui.select(
        placeholder="Selecione a categoria dos tickets",
        custom_id="config_category_select",
        min_values=1,
        max_values=1,
        row=1
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        category_id = int(select.values[0])
        self.bot.configs['ticket_category_id'] = category_id
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Categoria de tickets definida", ephemeral=True)
    
    @discord.ui.select(
        placeholder="Selecione o canal de logs",
        custom_id="config_logs_select",
        min_values=1,
        max_values=1,
        row=2
    )
    async def logs_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel_id = int(select.values[0])
        self.bot.configs['logs_channel_id'] = channel_id
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Canal de logs definido", ephemeral=True)
    
    async def update_options(self, guild: discord.Guild):
        """Atualiza as opções dos selects"""
        # Staff roles
        staff_options = []
        for role in guild.roles[1:50]:
            staff_options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    default=(role.id in self.bot.configs.get('staff_roles', []))
                )
            )
        if staff_options:
            self.children[0].options = staff_options
        
        # Categories
        category_options = []
        for category in guild.categories[:25]:
            category_options.append(
                discord.SelectOption(
                    label=category.name[:100],
                    value=str(category.id),
                    default=(category.id == self.bot.configs.get('ticket_category_id'))
                )
            )
        if category_options:
            self.children[1].options = category_options
        
        # Log channels
        channel_options = []
        for channel in guild.text_channels[:25]:
            channel_options.append(
                discord.SelectOption(
                    label=f"#{channel.name}"[:100],
                    value=str(channel.id),
                    default=(channel.id == self.bot.configs.get('logs_channel_id'))
                )
            )
        if channel_options:
            self.children[2].options = channel_options

class TicketTypeSelect(discord.ui.Select):
    def __init__(self, bot_instance):
        self.bot = bot_instance
        
        options = []
        categories = bot_instance.configs.get('ticket_categories', {})
        for key, value in categories.items():
            options.append(
                discord.SelectOption(
                    label=value['name'],
                    value=key,
                    description=value['description'][:50],
                    emoji=value['emoji']
                )
            )
        
        super().__init__(
            placeholder="🎫 Selecione o tipo de ticket...",
            options=options,
            custom_id="ticket_type_select",
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction):
        ticket_type = self.values[0]
        await interaction.response.send_modal(TicketOpenModal(self.bot, ticket_type))

class TicketPanelView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.add_item(TicketTypeSelect(bot_instance))

class TicketOpenModal(discord.ui.Modal, title="Abrir Ticket"):
    def __init__(self, bot_instance, ticket_type):
        super().__init__()
        self.bot = bot_instance
        self.ticket_type = ticket_type
        
        category_info = self.bot.configs['ticket_categories'][ticket_type]
        
        self.reason_input = discord.ui.TextInput(
            label=f"Motivo - {category_info['name']}",
            placeholder="Descreva detalhadamente o motivo do ticket...",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True
        )
        self.add_item(self.reason_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Verifica se usuário já tem ticket aberto
        for ticket_id, ticket_info in self.bot.active_tickets.items():
            if ticket_info.get('user_id') == interaction.user.id:
                channel = interaction.guild.get_channel(ticket_info.get('channel_id'))
                if channel:
                    await interaction.response.send_message(
                        f"❌ Você já possui um ticket aberto em {channel.mention}",
                        ephemeral=True
                    )
                    return
        
        await interaction.response.defer(ephemeral=True)
        
        # Cria o ticket
        ticket_data = await create_ticket(self.bot, interaction, self.ticket_type, self.reason_input.value)
        
        if ticket_data:
            await interaction.followup.send(
                f"✅ Ticket criado com sucesso! Acesse {ticket_data['channel'].mention}",
                ephemeral=True
            )

class TicketControlView(discord.ui.View):
    def __init__(self, bot_instance, ticket_id):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Assumir Ticket", emoji="✅", style=discord.ButtonStyle.success, custom_id="claim_ticket", row=0)
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verifica se é staff
        if not await is_staff(self.bot, interaction.user):
            await interaction.response.send_message("❌ Apenas staff pode assumir tickets!", ephemeral=True)
            return
        
        ticket_info = self.bot.active_tickets.get(self.ticket_id, {})
        
        if ticket_info.get('claimed_by'):
            claimed_user = interaction.guild.get_member(ticket_info['claimed_by'])
            await interaction.response.send_message(
                f"❌ Este ticket já foi assumido por {claimed_user.mention if claimed_user else 'alguém'}!",
                ephemeral=True
            )
            return
        
        # Atualiza ticket
        self.bot.active_tickets[self.ticket_id]['claimed_by'] = interaction.user.id
        self.bot.active_tickets[self.ticket_id]['claimed_at'] = datetime.utcnow().isoformat()
        await self.bot.save_data()
        
        # Atualiza o botão
        button.disabled = True
        button.label = f"Assumido por {interaction.user.name}"
        
        embed = discord.Embed(
            title="✅ Ticket Assumido",
            description=f"**{interaction.user.mention}** assumiu este ticket",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        await interaction.response.send_message(embed=embed)
        await interaction.message.edit(view=self)
        
        # Log
        await log_action(self.bot, interaction.guild, "🎫 Ticket Assumido", {
            "Ticket": f"#{interaction.channel.name}",
            "Assumido por": interaction.user.mention,
            "Usuário": f"<@{ticket_info['user_id']}>"
        })
    
    @discord.ui.button(label="Fechar Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="close_ticket", row=0)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verifica permissão
        if not await is_staff(self.bot, interaction.user):
            await interaction.response.send_message("❌ Apenas staff pode fechar tickets!", ephemeral=True)
            return
        
        # Mostra confirmação
        confirm_view = ConfirmCloseView(self.bot, self.ticket_id)
        await interaction.response.send_message(
            "⚠️ **Confirmar fechamento do ticket?**",
            view=confirm_view,
            ephemeral=True
        )

class ConfirmCloseView(discord.ui.View):
    def __init__(self, bot_instance, ticket_id):
        super().__init__(timeout=30)
        self.bot = bot_instance
        self.ticket_id = ticket_id
    
    @discord.ui.button(label="Confirmar", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_staff(self.bot, interaction.user):
            await interaction.response.send_message("❌ Apenas staff pode fechar tickets!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Gera transcript
        transcript = await generate_transcript(interaction.channel)
        
        # Log
        ticket_info = self.bot.active_tickets.get(self.ticket_id, {})
        await log_action(self.bot, interaction.guild, "🔒 Ticket Fechado", {
            "Ticket": f"#{interaction.channel.name}",
            "Fechado por": interaction.user.mention,
            "Usuário": f"<@{ticket_info.get('user_id', 'Desconhecido')}>",
            "Tipo": ticket_info.get('type', 'Desconhecido')
        }, transcript)
        
        # Envia mensagem de fechamento
        embed = discord.Embed(
            title="🔒 Ticket Fechado",
            description=f"Este ticket foi fechado por {interaction.user.mention}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        await interaction.channel.send(embed=embed)
        
        # Remove da memória
        if self.ticket_id in self.bot.active_tickets:
            del self.bot.active_tickets[self.ticket_id]
            await self.bot.save_data()
        
        # Aguarda e deleta canal
        await asyncio.sleep(5)
        await interaction.channel.delete()
    
    @discord.ui.button(label="Cancelar", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Fechamento cancelado", view=None)

# Funções auxiliares

async def is_staff(bot_instance, member: discord.Member) -> bool:
    """Verifica se o membro é staff"""
    staff_roles = bot_instance.configs.get('staff_roles', [])
    return any(role.id in staff_roles for role in member.roles)

async def create_ticket(bot_instance, interaction: discord.Interaction, ticket_type: str, reason: str):
    """Cria um novo ticket"""
    guild = interaction.guild
    category_id = bot_instance.configs.get('ticket_category_id')
    
    # Encontra ou cria categoria
    category = None
    if category_id:
        category = guild.get_channel(category_id)
    
    if not category:
        category = await guild.create_category("Tickets")
        bot_instance.configs['ticket_category_id'] = category.id
        await bot_instance.save_data()
    
    # Cria canal
    category_info = bot_instance.configs['ticket_categories'][ticket_type]
    channel_name = f"ticket-{category_info['name'].split()[1] if len(category_info['name'].split()) > 1 else ticket_type}-{interaction.user.name.lower().replace(' ', '-')}"
    
    # Configura permissões
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    
    # Adiciona staff
    staff_roles = bot_instance.configs.get('staff_roles', [])
    for role_id in staff_roles:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Cria canal
    channel = await guild.create_text_channel(
        name=channel_name[:100],
        category=category,
        overwrites=overwrites,
        topic=f"Ticket de {interaction.user.name} | Tipo: {category_info['name']}"
    )
    
    # Cria ticket ID
    ticket_id = f"{interaction.user.id}-{datetime.utcnow().timestamp()}"
    
    # Embed de boas-vindas
    embed = discord.Embed(
        title=f"{category_info['emoji']} {category_info['name']}",
        description="Um membro da equipe irá atendê-lo em breve.\nPor favor, descreva sua solicitação detalhadamente.",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    embed.add_field(name="👤 Usuário", value=interaction.user.mention, inline=True)
    embed.add_field(name="📝 Motivo", value=reason[:1024], inline=False)
    embed.add_field(name="⏰ Aguarde", value="A equipe foi notificada", inline=False)
    embed.set_footer(text=f"Ticket ID: {ticket_id[:8]}")
    
    # View de controle
    view = TicketControlView(bot_instance, ticket_id)
    
    # Menção da staff
    staff_mention = ""
    staff_roles = bot_instance.configs.get('staff_roles', [])
    for role_id in staff_roles[:3]:
        role = guild.get_role(role_id)
        if role:
            staff_mention += f"{role.mention} "
    
    # Envia mensagem
    await channel.send(
        f"{interaction.user.mention} {staff_mention}",
        embed=embed,
        view=view
    )
    
    # Salva ticket
    bot_instance.active_tickets[ticket_id] = {
        'channel_id': channel.id,
        'user_id': interaction.user.id,
        'type': ticket_type,
        'reason': reason,
        'created_at': datetime.utcnow().isoformat(),
        'status': 'open'
    }
    
    await bot_instance.save_data()
    
    # Log
    await log_action(bot_instance, guild, "🎫 Ticket Aberto", {
        "Ticket": f"#{channel.name}",
        "Usuário": interaction.user.mention,
        "Tipo": category_info['name'],
        "Motivo": reason[:200]
    })
    
    return {
        'channel': channel,
        'ticket_id': ticket_id
    }

async def generate_transcript(channel: discord.TextChannel):
    """Gera transcript do canal"""
    messages = []
    async for message in channel.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = f"{message.author.name}#{message.author.discriminator}"
        content = message.content or "[Sem conteúdo de texto]"
        
        # Adiciona embeds
        embeds_text = ""
        if message.embeds:
            for embed in message.embeds:
                embeds_text += f"\n[Embed: {embed.title or 'Sem título'}]"
        
        # Adiciona attachments
        attachments_text = ""
        if message.attachments:
            for att in message.attachments:
                attachments_text += f"\n[Anexo: {att.filename} - {att.url}]"
        
        messages.append(f"[{timestamp}] {author}: {content}{embeds_text}{attachments_text}")
    
    transcript_text = "\n".join(messages)
    
    # Cria arquivo HTML formatado
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Transcript - {channel.name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }}
            .container {{ max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 10px; }}
            .header {{ background: #7289da; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            .message {{ border-bottom: 1px solid #eee; padding: 10px; }}
            .timestamp {{ color: #666; font-size: 0.9em; }}
            .author {{ font-weight: bold; color: #7289da; }}
            .content {{ margin-top: 5px; }}
            .embed {{ background: #f5f5f5; padding: 10px; margin: 5px 0; border-left: 4px solid #7289da; }}
            .attachment {{ color: #4CAF50; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📝 Transcript do Ticket</h1>
                <p>Canal: #{channel.name}</p>
                <p>Data: {datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")}</p>
            </div>
            <div class="messages">
    """
    
    for msg in messages:
        parts = msg.split(": ", 2)
        if len(parts) >= 3:
            timestamp = parts[0].strip("[]")
            author = parts[1]
            content = parts[2]
            html_content += f"""
                <div class="message">
                    <div class="timestamp">{timestamp}</div>
                    <div class="author">{html.escape(author)}</div>
                    <div class="content">{html.escape(content)}</div>
                </div>
            """
    
    html_content += """
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_content

async def log_action(bot_instance, guild: discord.Guild, title: str, fields: dict, transcript: str = None):
    """Envia log para o canal configurado"""
    logs_channel_id = bot_instance.configs.get('logs_channel_id')
    if not logs_channel_id:
        return
    
    logs_channel = guild.get_channel(logs_channel_id)
    if not logs_channel:
        return
    
    embed = discord.Embed(
        title=title,
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    for key, value in fields.items():
        embed.add_field(name=key, value=value, inline=False)
    
    if transcript:
        # Salva transcript em arquivo
        file = discord.File(
            io.StringIO(transcript),
            filename=f"transcript-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.html"
        )
        await logs_channel.send(embed=embed, file=file)
    else:
        await logs_channel.send(embed=embed)

async def create_panel_embed(bot_instance) -> discord.Embed:
    """Cria embed do painel principal"""
    embed = discord.Embed(
        title="🎫 Sistema de Tickets",
        description=(
            "**Bem-vindo ao sistema de suporte!**\n\n"
            "Para abrir um ticket, selecione uma das opções abaixo no menu dropdown.\n"
            "Nossa equipe irá atendê-lo o mais rápido possível.\n\n"
            "**Opções disponíveis:**\n"
            "🛠️ **Suporte** - Dúvidas ou ajuda geral\n"
            "💰 **Reembolso** - Solicitações de reembolso\n"
            "📦 **Receber Evento** - Entrega de eventos/prêmios\n"
            "👥 **Vagas Mediadores** - Candidatura a mediador\n\n"
            "⏰ Tempo médio de resposta: 15-30 minutos"
        ),
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📊 Estatísticas",
        value=f"Tickets Ativos: {len(bot_instance.active_tickets)}",
        inline=False
    )
    
    embed.set_footer(text="Clique no menu abaixo para começar")
    
    return embed

# Comandos Slash

@bot.tree.command(name="config", description="Configurações gerais do sistema de tickets")
@app_commands.default_permissions(administrator=True)
async def config_command(interaction: discord.Interaction):
    view = ConfigView(bot)
    await view.update_options(interaction.guild)
    
    embed = discord.Embed(
        title="⚙️ Configurações do Sistema de Tickets",
        description="Configure os cargos, categoria e canal de logs",
        color=discord.Color.green()
    )
    
    # Mostra configurações atuais
    staff_roles = bot.configs.get('staff_roles', [])
    staff_mentions = [f"<@&{role_id}>" for role_id in staff_roles if interaction.guild.get_role(role_id)]
    
    category_id = bot.configs.get('ticket_category_id')
    category = interaction.guild.get_channel(category_id) if category_id else None
    
    logs_id = bot.configs.get('logs_channel_id')
    logs_channel = interaction.guild.get_channel(logs_id) if logs_id else None
    
    embed.add_field(
        name="👥 Staff",
        value=", ".join(staff_mentions) if staff_mentions else "Não configurado",
        inline=False
    )
    embed.add_field(
        name="📁 Categoria",
        value=category.mention if category else "Não configurado",
        inline=False
    )
    embed.add_field(
        name="📋 Logs",
        value=logs_channel.mention if logs_channel else "Não configurado",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="painel", description="Envia o painel de tickets no canal atual")
@app_commands.default_permissions(administrator=True)
async def panel_command(interaction: discord.Interaction):
    embed = await create_panel_embed(bot)
    view = TicketPanelView(bot)
    
    message = await interaction.channel.send(embed=embed, view=view)
    
    # Salva referência
    bot.panel_message_id = message.id
    bot.panel_channel_id = interaction.channel.id
    await bot.save_data()
    
    await interaction.response.send_message("✅ Painel enviado com sucesso!", ephemeral=True)

@bot.tree.command(name="tickets", description="Lista todos os tickets ativos")
@app_commands.default_permissions(manage_messages=True)
async def list_tickets_command(interaction: discord.Interaction):
    if not bot.active_tickets:
        await interaction.response.send_message("📭 Não há tickets ativos no momento.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎫 Tickets Ativos",
        description=f"Total: {len(bot.active_tickets)}",
        color=discord.Color.blue()
    )
    
    for ticket_id, ticket_info in list(bot.active_tickets.items())[:10]:
        user = interaction.guild.get_member(ticket_info.get('user_id'))
        channel = interaction.guild.get_channel(ticket_info.get('channel_id'))
        ticket_type = ticket_info.get('type', 'Desconhecido')
        claimed_by = ticket_info.get('claimed_by')
        claimed_user = interaction.guild.get_member(claimed_by) if claimed_by else None
        
        category_info = bot.configs['ticket_categories'].get(ticket_type, {})
        type_name = category_info.get('name', ticket_type)
        
        status = "✅ Assumido" if claimed_by else "⏳ Aguardando"
        
        embed.add_field(
            name=f"{type_name} - {ticket_id[:8]}",
            value=f"👤 Usuário: {user.mention if user else 'Desconhecido'}\n"
                  f"📺 Canal: {channel.mention if channel else 'Deletado'}\n"
                  f"📊 Status: {status}\n"
                  f"👔 Assumido por: {claimed_user.mention if claimed_user else 'Ninguém'}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="fechar", description="Força o fechamento de um ticket")
@app_commands.default_permissions(manage_messages=True)
async def force_close_command(interaction: discord.Interaction, ticket_id: str):
    # Verifica se é staff
    if not await is_staff(bot, interaction.user):
        await interaction.response.send_message("❌ Apenas staff pode usar este comando!", ephemeral=True)
        return
    
    ticket_info = bot.active_tickets.get(ticket_id)
    if not ticket_info:
        await interaction.response.send_message("❌ Ticket não encontrado!", ephemeral=True)
        return
    
    channel = interaction.guild.get_channel(ticket_info['channel_id'])
    if not channel:
        await interaction.response.send_message("❌ Canal do ticket não encontrado!", ephemeral=True)
        return
    
    # Gera transcript
    transcript = await generate_transcript(channel)
    
    # Log
    await log_action(bot, interaction.guild, "🔒 Ticket Fechado (Forçado)", {
        "Ticket": f"#{channel.name}",
        "Fechado por": interaction.user.mention,
        "Usuário": f"<@{ticket_info.get('user_id', 'Desconhecido')}>",
        "Tipo": ticket_info.get('type', 'Desconhecido'),
        "Método": "Comando forçado"
    }, transcript)
    
    # Remove e deleta
    del bot.active_tickets[ticket_id]
    await bot.save_data()
    await channel.delete()
    
    await interaction.response.send_message(f"✅ Ticket `{ticket_id[:8]}` fechado com sucesso!", ephemeral=True)

# Eventos

@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    print(f'📊 Comandos carregados: {len(bot.tree.get_commands())}')
    
    # Registra views persistentes
    bot.add_view(ConfigView(bot))
    bot.add_view(TicketPanelView(bot))
    
    # Reconecta views de tickets ativos
    for ticket_id, ticket_info in bot.active_tickets.items():
        channel_id = ticket_info.get('channel_id')
        if channel_id:
            channel = bot.get_channel(channel_id)
            if channel:
                view = TicketControlView(bot, ticket_id)
                bot.add_view(view)

@bot.event
async def on_guild_channel_delete(channel):
    """Limpa tickets quando canal é deletado"""
    for ticket_id, ticket_info in list(bot.active_tickets.items()):
        if ticket_info.get('channel_id') == channel.id:
            del bot.active_tickets[ticket_id]
            await bot.save_data()
            break

# Inicialização
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERRO: Token não encontrado no arquivo .env")
        print("Crie um arquivo .env com DISCORD_TOKEN=seu_token_aqui")
    else:
        bot.run(TOKEN)
