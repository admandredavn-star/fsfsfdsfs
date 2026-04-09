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

# ============================================
# VIEWS DE CONFIGURAÇÃO
# ============================================

class ConfigMenuView(discord.ui.View):
    """Menu principal de configuração"""
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
    
    @discord.ui.button(label="Configurar Cargos", emoji="👥", style=discord.ButtonStyle.primary, custom_id="config_roles", row=0)
    async def config_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = RoleConfigView(self.bot)
        embed = await create_role_config_embed(self.bot, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @discord.ui.button(label="Configurar Canais", emoji="📺", style=discord.ButtonStyle.primary, custom_id="config_channels", row=0)
    async def config_channels_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ChannelConfigView(self.bot)
        await view.update_options(interaction.guild)
        embed = await create_channel_config_embed(self.bot, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @discord.ui.button(label="Configurar Categorias", emoji="📂", style=discord.ButtonStyle.primary, custom_id="config_categories", row=1)
    async def config_categories_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CategoryConfigView(self.bot)
        embed = await create_category_config_embed(self.bot)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @discord.ui.button(label="Ver Configurações", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="view_config", row=1)
    async def view_config_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await create_full_config_embed(self.bot, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RoleConfigView(discord.ui.View):
    """View para configuração de cargos"""
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
    
    @discord.ui.select(
        placeholder="👔 Cargos que podem ASSUMIR tickets",
        custom_id="claim_roles_select",
        min_values=0,
        max_values=25,
        row=0
    )
    async def claim_roles_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        roles = [int(role_id) for role_id in select.values] if select.values else []
        self.bot.configs['claim_roles'] = roles
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Cargos para assumir tickets atualizados!", ephemeral=True)
    
    @discord.ui.select(
        placeholder="🔒 Cargos que podem FECHAR tickets",
        custom_id="close_roles_select",
        min_values=0,
        max_values=25,
        row=1
    )
    async def close_roles_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        roles = [int(role_id) for role_id in select.values] if select.values else []
        self.bot.configs['close_roles'] = roles
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Cargos para fechar tickets atualizados!", ephemeral=True)
    
    @discord.ui.select(
        placeholder="👀 Cargos que podem ACESSAR/VER tickets",
        custom_id="access_roles_select",
        min_values=0,
        max_values=25,
        row=2
    )
    async def access_roles_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        roles = [int(role_id) for role_id in select.values] if select.values else []
        self.bot.configs['access_roles'] = roles
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Cargos para acessar tickets atualizados!", ephemeral=True)
    
    async def update_options(self, guild: discord.Guild):
        """Atualiza as opções dos selects com os cargos do servidor"""
        role_options = []
        for role in guild.roles[1:50]:  # Pula @everyone
            if not role.managed and role.name != "@everyone":
                role_options.append(
                    discord.SelectOption(
                        label=role.name[:100],
                        value=str(role.id),
                        emoji="👔" if role.permissions.administrator else "👤"
                    )
                )
        
        if role_options:
            # Atualiza cada select com os cargos e marca os já selecionados
            claim_roles = self.bot.configs.get('claim_roles', [])
            close_roles = self.bot.configs.get('close_roles', [])
            access_roles = self.bot.configs.get('access_roles', [])
            
            for i, select in enumerate(self.children):
                if isinstance(select, discord.ui.Select):
                    select.options = role_options
                    
                    # Marca os defaults
                    if i == 0:  # Claim roles
                        select.default_values = [str(r) for r in claim_roles]
                    elif i == 1:  # Close roles
                        select.default_values = [str(r) for r in close_roles]
                    elif i == 2:  # Access roles
                        select.default_values = [str(r) for r in access_roles]

class ChannelConfigView(discord.ui.View):
    """View para configuração de canais"""
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
    
    @discord.ui.select(
        placeholder="📁 Selecione a categoria dos tickets",
        custom_id="ticket_category_select",
        min_values=1,
        max_values=1,
        row=0
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        category_id = int(select.values[0])
        self.bot.configs['ticket_category_id'] = category_id
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Categoria de tickets definida!", ephemeral=True)
    
    @discord.ui.select(
        placeholder="📋 Selecione o canal de logs",
        custom_id="logs_channel_select",
        min_values=1,
        max_values=1,
        row=1
    )
    async def logs_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel_id = int(select.values[0])
        self.bot.configs['logs_channel_id'] = channel_id
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Canal de logs definido!", ephemeral=True)
    
    @discord.ui.select(
        placeholder="🎫 Selecione o canal do painel",
        custom_id="panel_channel_select",
        min_values=1,
        max_values=1,
        row=2
    )
    async def panel_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        channel_id = int(select.values[0])
        self.bot.configs['panel_channel_id'] = channel_id
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Canal do painel definido! Use /painel para enviar.", ephemeral=True)
    
    async def update_options(self, guild: discord.Guild):
        """Atualiza as opções dos selects"""
        # Categorias
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
            self.children[0].options = category_options
        
        # Canais de texto
        channel_options = []
        for channel in guild.text_channels[:25]:
            channel_options.append(
                discord.SelectOption(
                    label=f"#{channel.name}"[:100],
                    value=str(channel.id),
                    description=f"Categoria: {channel.category.name if channel.category else 'Sem categoria'}",
                    default=(channel.id == self.bot.configs.get('logs_channel_id'))
                )
            )
        if channel_options:
            self.children[1].options = channel_options
            self.children[2].options = channel_options.copy()
            # Ajusta default do painel
            panel_id = self.bot.configs.get('panel_channel_id')
            if panel_id:
                for opt in self.children[2].options:
                    opt.default = (int(opt.value) == panel_id)

class CategoryConfigView(discord.ui.View):
    """View para configuração das categorias de ticket"""
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
    
    @discord.ui.button(label="Editar Suporte", emoji="🛠️", style=discord.ButtonStyle.primary, custom_id="edit_suporte", row=0)
    async def edit_suporte(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CategoryEditModal(self.bot, "suporte"))
    
    @discord.ui.button(label="Editar Reembolso", emoji="💰", style=discord.ButtonStyle.primary, custom_id="edit_reembolso", row=1)
    async def edit_reembolso(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CategoryEditModal(self.bot, "reembolso"))
    
    @discord.ui.button(label="Editar Evento", emoji="📦", style=discord.ButtonStyle.primary, custom_id="edit_evento", row=2)
    async def edit_evento(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CategoryEditModal(self.bot, "evento"))
    
    @discord.ui.button(label="Editar Mediador", emoji="👥", style=discord.ButtonStyle.primary, custom_id="edit_mediador", row=3)
    async def edit_mediador(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CategoryEditModal(self.bot, "mediador"))

class CategoryEditModal(discord.ui.Modal, title="Editar Categoria"):
    def __init__(self, bot_instance, category_key):
        super().__init__()
        self.bot = bot_instance
        self.category_key = category_key
        
        category = self.bot.configs['ticket_categories'].get(category_key, {})
        
        self.name_input = discord.ui.TextInput(
            label="Nome da Categoria",
            placeholder="Ex: 🛠️ Suporte",
            default=category.get('name', ''),
            max_length=100,
            required=True
        )
        self.add_item(self.name_input)
        
        self.emoji_input = discord.ui.TextInput(
            label="Emoji",
            placeholder="Ex: 🛠️",
            default=category.get('emoji', ''),
            max_length=10,
            required=False
        )
        self.add_item(self.emoji_input)
        
        self.desc_input = discord.ui.TextInput(
            label="Descrição",
            placeholder="Descrição da categoria...",
            default=category.get('description', ''),
            style=discord.TextStyle.paragraph,
            max_length=100,
            required=True
        )
        self.add_item(self.desc_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        self.bot.configs['ticket_categories'][self.category_key] = {
            'name': self.name_input.value,
            'emoji': self.emoji_input.value or '📝',
            'description': self.desc_input.value
        }
        await self.bot.save_data()
        await interaction.response.send_message(f"✅ Categoria {self.name_input.value} atualizada!", ephemeral=True)

# ============================================
# VIEWS DE TICKET
# ============================================

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
            placeholder="🎫 Clique aqui para ver as opções disponíveis",
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
        # Verifica se pode assumir
        if not await can_claim(self.bot, interaction.user):
            await interaction.response.send_message("❌ Você não tem permissão para assumir tickets!", ephemeral=True)
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
        if not await can_close(self.bot, interaction.user):
            await interaction.response.send_message("❌ Você não tem permissão para fechar tickets!", ephemeral=True)
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
        if not await can_close(self.bot, interaction.user):
            await interaction.response.send_message("❌ Você não tem permissão para fechar tickets!", ephemeral=True)
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

# ============================================
# FUNÇÕES DE PERMISSÃO
# ============================================

async def can_claim(bot_instance, member: discord.Member) -> bool:
    """Verifica se o membro pode assumir tickets"""
    claim_roles = bot_instance.configs.get('claim_roles', [])
    if not claim_roles:
        return member.guild_permissions.administrator
    return any(role.id in claim_roles for role in member.roles)

async def can_close(bot_instance, member: discord.Member) -> bool:
    """Verifica se o membro pode fechar tickets"""
    close_roles = bot_instance.configs.get('close_roles', [])
    if not close_roles:
        return member.guild_permissions.administrator
    return any(role.id in close_roles for role in member.roles)

async def can_access(bot_instance, member: discord.Member) -> bool:
    """Verifica se o membro pode acessar/ver tickets"""
    access_roles = bot_instance.configs.get('access_roles', [])
    if not access_roles:
        return member.guild_permissions.administrator
    return any(role.id in access_roles for role in member.roles)

# ============================================
# FUNÇÕES AUXILIARES
# ============================================

async def create_role_config_embed(bot_instance, guild: discord.Guild) -> discord.Embed:
    """Cria embed de configuração de cargos"""
    embed = discord.Embed(
        title="👥 Configuração de Cargos",
        description="Configure quais cargos podem realizar cada ação no sistema de tickets",
        color=discord.Color.blue()
    )
    
    claim_roles = bot_instance.configs.get('claim_roles', [])
    close_roles = bot_instance.configs.get('close_roles', [])
    access_roles = bot_instance.configs.get('access_roles', [])
    
    claim_mentions = [f"<@&{r}>" for r in claim_roles if guild.get_role(r)] or ["Nenhum"]
    close_mentions = [f"<@&{r}>" for r in close_roles if guild.get_role(r)] or ["Nenhum"]
    access_mentions = [f"<@&{r}>" for r in access_roles if guild.get_role(r)] or ["Nenhum"]
    
    embed.add_field(
        name="✅ Assumir Tickets",
        value="\n".join(claim_mentions[:10]) + ("\n..." if len(claim_mentions) > 10 else ""),
        inline=True
    )
    
    embed.add_field(
        name="🔒 Fechar Tickets",
        value="\n".join(close_mentions[:10]) + ("\n..." if len(close_mentions) > 10 else ""),
        inline=True
    )
    
    embed.add_field(
        name="👀 Acessar Tickets",
        value="\n".join(access_mentions[:10]) + ("\n..." if len(access_mentions) > 10 else ""),
        inline=True
    )
    
    embed.set_footer(text="Use os menus abaixo para configurar")
    return embed

async def create_channel_config_embed(bot_instance, guild: discord.Guild) -> discord.Embed:
    """Cria embed de configuração de canais"""
    embed = discord.Embed(
        title="📺 Configuração de Canais",
        description="Configure os canais e categorias do sistema",
        color=discord.Color.green()
    )
    
    category_id = bot_instance.configs.get('ticket_category_id')
    category = guild.get_channel(category_id) if category_id else None
    
    logs_id = bot_instance.configs.get('logs_channel_id')
    logs_channel = guild.get_channel(logs_id) if logs_id else None
    
    panel_id = bot_instance.configs.get('panel_channel_id')
    panel_channel = guild.get_channel(panel_id) if panel_id else None
    
    embed.add_field(
        name="📁 Categoria dos Tickets",
        value=category.mention if category else "❌ Não configurado",
        inline=False
    )
    
    embed.add_field(
        name="📋 Canal de Logs",
        value=logs_channel.mention if logs_channel else "❌ Não configurado",
        inline=False
    )
    
    embed.add_field(
        name="🎫 Canal do Painel",
        value=panel_channel.mention if panel_channel else "❌ Não configurado",
        inline=False
    )
    
    return embed

async def create_category_config_embed(bot_instance) -> discord.Embed:
    """Cria embed de configuração de categorias"""
    embed = discord.Embed(
        title="📂 Configuração de Categorias",
        description="Configure as categorias de tickets disponíveis",
        color=discord.Color.purple()
    )
    
    categories = bot_instance.configs.get('ticket_categories', {})
    
    for key, value in categories.items():
        embed.add_field(
            name=f"{value.get('emoji', '📝')} {value.get('name', key)}",
            value=value.get('description', 'Sem descrição'),
            inline=False
        )
    
    embed.set_footer(text="Clique nos botões abaixo para editar cada categoria")
    return embed

async def create_full_config_embed(bot_instance, guild: discord.Guild) -> discord.Embed:
    """Cria embed com todas as configurações"""
    embed = discord.Embed(
        title="📊 Configurações Atuais",
        description="Resumo completo das configurações do sistema",
        color=discord.Color.gold()
    )
    
    # Cargos
    claim_roles = bot_instance.configs.get('claim_roles', [])
    close_roles = bot_instance.configs.get('close_roles', [])
    access_roles = bot_instance.configs.get('access_roles', [])
    
    embed.add_field(
        name="👥 Cargos",
        value=f"**Assumir:** {len(claim_roles)} cargos\n"
              f"**Fechar:** {len(close_roles)} cargos\n"
              f"**Acessar:** {len(access_roles)} cargos",
        inline=True
    )
    
    # Canais
    category_id = bot_instance.configs.get('ticket_category_id')
    logs_id = bot_instance.configs.get('logs_channel_id')
    panel_id = bot_instance.configs.get('panel_channel_id')
    
    embed.add_field(
        name="📺 Canais",
        value=f"**Categoria:** {'✅' if category_id else '❌'}\n"
              f"**Logs:** {'✅' if logs_id else '❌'}\n"
              f"**Painel:** {'✅' if panel_id else '❌'}",
        inline=True
    )
    
    # Estatísticas
    embed.add_field(
        name="📈 Status",
        value=f"**Tickets Ativos:** {len(bot_instance.active_tickets)}\n"
              f"**Categorias:** {len(bot_instance.configs.get('ticket_categories', {}))}",
        inline=True
    )
    
    return embed

async def create_panel_embed(bot_instance) -> discord.Embed:
    """Cria embed do painel principal - SEM ESTATÍSTICAS"""
    categories = bot_instance.configs.get('ticket_categories', {})
    
    description = (
        "**Bem-vindo ao sistema de suporte!**\n\n"
        "Para abrir um ticket, selecione uma das opções abaixo no menu dropdown.\n"
        "Nossa equipe irá atendê-lo o mais rápido possível.\n\n"
        "**📋 Opções disponíveis:**\n"
    )
    
    for key, value in categories.items():
        description += f"{value.get('emoji', '📝')} **{value.get('name', key)}** - {value.get('description', '')}\n"
    
    description += "\n⏰ *Tempo médio de resposta: 15-30 minutos*"
    
    embed = discord.Embed(
        title="🎫 Sistema de Tickets",
        description=description,
        color=discord.Color.blue()
    )
    
    embed.set_footer(text="Selecione uma opção no menu abaixo para começar")
    
    return embed

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
    channel_name = f"ticket-{ticket_type}-{interaction.user.name.lower().replace(' ', '-')}"[:100]
    
    # Configura permissões
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    
    # Adiciona cargos de acesso
    access_roles = bot_instance.configs.get('access_roles', [])
    for role_id in access_roles:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Cria canal
    channel = await guild.create_text_channel(
        name=channel_name,
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
    embed.set_footer(text=f"Ticket ID: {ticket_id[:8]}")
    
    # View de controle
    view = TicketControlView(bot_instance, ticket_id)
    
    # Menção dos cargos de acesso
    mentions = []
    for role_id in access_roles[:3]:
        role = guild.get_role(role_id)
        if role:
            mentions.append(role.mention)
    
    staff_mention = " ".join(mentions) if mentions else ""
    
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
    """Gera transcript HTML do canal"""
    messages = []
    async for message in channel.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = f"{message.author.name}"
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
                attachments_text += f"\n[Anexo: {att.filename}]"
        
        messages.append(f"[{timestamp}] {author}: {content}{embeds_text}{attachments_text}")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Transcript - {channel.name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #36393f; color: #dcddde; }}
            .container {{ max-width: 1200px; margin: auto; background: #2f3136; padding: 20px; border-radius: 10px; }}
            .header {{ background: #7289da; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            .message {{ border-bottom: 1px solid #40444b; padding: 10px; }}
            .timestamp {{ color: #72767d; font-size: 0.9em; }}
            .author {{ font-weight: bold; color: #7289da; }}
            .content {{ margin-top: 5px; color: #dcddde; }}
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

# ============================================
# COMANDOS SLASH
# ============================================

@bot.tree.command(name="config", description="Abre o painel de configuração do sistema de tickets")
@app_commands.default_permissions(administrator=True)
async def config_command(interaction: discord.Interaction):
    """Comando principal de configuração"""
    embed = discord.Embed(
        title="⚙️ Painel de Configuração",
        description=(
            "Bem-vindo ao painel de configuração do sistema de tickets!\n\n"
            "Use os botões abaixo para configurar:\n"
            "👥 **Cargos** - Defina quem pode assumir, fechar e acessar tickets\n"
            "📺 **Canais** - Configure categoria, logs e canal do painel\n"
            "📂 **Categorias** - Personalize as categorias de tickets\n"
            "📊 **Ver Configurações** - Visualize todas as configurações atuais"
        ),
        color=discord.Color.blue()
    )
    
    view = ConfigMenuView(bot)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="painel", description="Envia o painel de tickets no canal configurado")
@app_commands.default_permissions(administrator=True)
async def panel_command(interaction: discord.Interaction):
    """Envia o painel de tickets"""
    panel_channel_id = bot.configs.get('panel_channel_id')
    
    if not panel_channel_id:
        await interaction.response.send_message(
            "❌ Canal do painel não configurado! Use `/config` para configurar.",
            ephemeral=True
        )
        return
    
    channel = interaction.guild.get_channel(panel_channel_id)
    if not channel:
        await interaction.response.send_message(
            "❌ Canal do painel não encontrado! Use `/config` para reconfigurar.",
            ephemeral=True
        )
        return
    
    embed = await create_panel_embed(bot)
    view = TicketPanelView(bot)
    
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        f"✅ Painel enviado com sucesso em {channel.mention}!",
        ephemeral=True
    )

@bot.tree.command(name="tickets", description="Lista todos os tickets ativos")
async def list_tickets_command(interaction: discord.Interaction):
    """Lista tickets ativos - apenas para quem tem permissão"""
    if not await can_access(bot, interaction.user):
        await interaction.response.send_message(
            "❌ Você não tem permissão para ver os tickets!",
            ephemeral=True
        )
        return
    
    if not bot.active_tickets:
        await interaction.response.send_message("📭 Não há tickets ativos no momento.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎫 Tickets Ativos",
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
            name=f"{type_name}",
            value=f"👤 **Usuário:** {user.mention if user else 'Desconhecido'}\n"
                  f"📺 **Canal:** {channel.mention if channel else 'Deletado'}\n"
                  f"📊 **Status:** {status}\n"
                  f"👔 **Assumido por:** {claimed_user.mention if claimed_user else 'Ninguém'}\n"
                  f"🆔 **ID:** `{ticket_id[:8]}`",
            inline=False
        )
    
    if len(bot.active_tickets) > 10:
        embed.set_footer(text=f"E mais {len(bot.active_tickets) - 10} tickets...")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="fechar", description="Força o fechamento de um ticket específico")
async def force_close_command(interaction: discord.Interaction, ticket_id: str):
    """Força fechamento de ticket por ID"""
    if not await can_close(bot, interaction.user):
        await interaction.response.send_message(
            "❌ Você não tem permissão para fechar tickets!",
            ephemeral=True
        )
        return
    
    # Procura o ticket
    found_ticket = None
    found_id = None
    
    for tid, ticket_info in bot.active_tickets.items():
        if tid.startswith(ticket_id) or ticket_id in tid:
            found_ticket = ticket_info
            found_id = tid
            break
    
    if not found_ticket:
        await interaction.response.send_message(
            f"❌ Ticket com ID `{ticket_id}` não encontrado!",
            ephemeral=True
        )
        return
    
    channel = interaction.guild.get_channel(found_ticket['channel_id'])
    if not channel:
        await interaction.response.send_message(
            "❌ Canal do ticket não encontrado!",
            ephemeral=True
        )
        return
    
    # Gera transcript
    transcript = await generate_transcript(channel)
    
    # Log
    await log_action(bot, interaction.guild, "🔒 Ticket Fechado (Forçado)", {
        "Ticket": f"#{channel.name}",
        "Fechado por": interaction.user.mention,
        "Usuário": f"<@{found_ticket.get('user_id', 'Desconhecido')}>",
        "Tipo": found_ticket.get('type', 'Desconhecido'),
        "Método": "Comando forçado"
    }, transcript)
    
    # Remove e deleta
    del bot.active_tickets[found_id]
    await bot.save_data()
    
    embed = discord.Embed(
        title="🔒 Ticket Fechado",
        description=f"Este ticket foi fechado por {interaction.user.mention} (forçado)",
        color=discord.Color.red()
    )
    await channel.send(embed=embed)
    
    await asyncio.sleep(3)
    await channel.delete()
    
    await interaction.response.send_message(
        f"✅ Ticket `{found_id[:8]}` fechado com sucesso!",
        ephemeral=True
    )

# ============================================
# EVENTOS
# ============================================

@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    print(f'📊 Comandos carregados: {len(bot.tree.get_commands())}')
    
    # Registra views persistentes
    bot.add_view(ConfigMenuView(bot))
    bot.add_view(RoleConfigView(bot))
    bot.add_view(ChannelConfigView(bot))
    bot.add_view(CategoryConfigView(bot))
    bot.add_view(TicketPanelView(bot))
    
    # Reconecta views de tickets ativos
    for ticket_id, ticket_info in bot.active_tickets.items():
        channel_id = ticket_info.get('channel_id')
        if channel_id:
            channel = bot.get_channel(channel_id)
            if channel:
                view = TicketControlView(bot, ticket_id)
                bot.add_view(view)
    
    # Atualiza opções dos selects
    for guild in bot.guilds:
        for view in [RoleConfigView(bot), ChannelConfigView(bot)]:
            if hasattr(view, 'update_options'):
                await view.update_options(guild)

@bot.event
async def on_guild_channel_delete(channel):
    """Limpa tickets quando canal é deletado"""
    for ticket_id, ticket_info in list(bot.active_tickets.items()):
        if ticket_info.get('channel_id') == channel.id:
            del bot.active_tickets[ticket_id]
            await bot.save_data()
            break

# ============================================
# INICIALIZAÇÃO
# ============================================

if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERRO: Token não encontrado no arquivo .env")
        print("Crie um arquivo .env com DISCORD_TOKEN=seu_token_aqui")
    else:
        bot.run(TOKEN)
