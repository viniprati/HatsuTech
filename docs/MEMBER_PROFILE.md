# Perfil do Café

`/perfil` mostra o cartão do próprio autor. Não aceita outro usuário como alvo.
A resposta é privada por padrão; `publico:True` compartilha o cartão no canal.
O cartão público contém nome, avatar, ingresso, VIP, guilda, pontos, saldos,
descrição e conquistas. O próprio membro decide compartilhá-lo.

## Personalização

- `tema`: Café, Sakura ou Meia-noite, com cores e contraste próprios.
- `sobre`: descrição de até 100 caracteres; um espaço limpa a descrição salva.
- Botão **Ver conquistas**: requisitos e progresso em resposta privada.
- Botão **Destacar insígnias**: seleciona até três insígnias desbloqueadas;
  selecionar nenhuma remove os destaques. Reabra `/perfil` para atualizar o cartão.

Há um intervalo de vinte segundos por membro/servidor e no máximo dois cartões
em geração simultânea. Os botões expiram em até três minutos e só aceitam o
autor. Não há concessão de cargos, prêmios econômicos ou notificações por DM.

## Critérios das dez insígnias

| Insígnia | Evidência necessária |
| --- | --- |
| Lenda do Café | 365 dias desde o ingresso atual no servidor. |
| Cafeinado | 10.000 pontos do ranking de chat. |
| Voz do Café | 100 horas do ranking de voz. |
| Criador da Hatsu | Conta do desenvolvedor configurada em `BOT_OWNER_ID`. |
| Maratonista | 1.000 horas do ranking de voz. |
| Primeiro Gole | Pelo menos um ponto de chat ou tempo registrado no ranking de voz. |
| Presença Marcante | Participar em sete dias distintos, acumulados desde a implantação. Não precisa ser uma sequência. |
| Alma da Guilda | Contribuição pessoal de 1.000 XP na guilda atual. O XP total da guilda não concede a insígnia sozinho. |
| Campeão de Eventos | Maior pontuação positiva em um evento encerrado; empates concedem a ambos. |
| Apoiador do Café | Tag visível do servidor, boost atual ou cargo Apoiador. É uma condição atual. |

Pontos de chat e horas de voz incluem os bônus existentes do ranking; não são
contagens literais de mensagens nem tempo de call sem bônus. A maior categoria
VIP possuída é mostrada no cartão.

Presença Marcante registra mensagens novas no lobby configurado e presença em
voz/stage fora do AFK. Bots são ignorados. A voz é observada na mudança de estado
e a cada cinco minutos, inclusive para quem atravessa a meia-noite conectado.
Cada membro gera no máximo uma gravação confirmada por dia BRT no processo; o
registro mantém apenas sete datas distintas. Não se tenta deduzir dias antigos
a partir de contadores agregados.

## Persistência e limites do histórico

Os dados ficam em `member_profiles`, com `_id` `guild_id:user_id`, IDs string,
preferências, até sete datas e um mapa limitado aos dez timestamps de conquistas.
O índice composto por `guild_id`/`user_id` é criado pela inicialização existente.
Conteúdo de mensagens e avatares não são armazenados por esta feature.

As conquistas verificadas são gravadas com `$min`, preservando a primeira data
observada sob concorrência. Permanecem após resets dos contadores. Apoiador é
avaliado pelo estado atual e não permanece visível depois da perda da condição.
Outras conquistas são avaliadas quando o membro consulta o perfil; se um contador
antigo já foi apagado antes da primeira consulta, não é possível reconstruí-lo.

Vitórias novas são registradas ao encerrar eventos manualmente ou por expiração
no fluxo existente. O encerramento por expiração continua dependendo da próxima
mensagem válida no canal do evento. O arquivo de pontos é capturado atomicamente
do banco, sem usar os pontos desatualizados do cache de roteamento. Também são
reconhecidos os vencedores da última edição disponível de cada um dos dois
eventos ao consultar o perfil. Eventos mais antigos, já sobrescritos antes desta
atualização, não têm histórico reconstruível. Uma vitória pode criar o registro
de um participante que saiu depois do evento: a conquista é histórica, não uma
concessão de cargo. Falhas ao salvar são registradas; o último ranking disponível
permite uma nova confirmação na consulta do vencedor.

O servidor de testes compartilha as fontes canônicas de economia/rankings/guildas
da main, conforme `get_data_guild_id`. Ingresso, preferências, presença, avatar e
conquistas persistidas continuam separados pelo servidor real da interação.
Registros com IDs explícitos de outro usuário/servidor são descartados.

Se qualquer leitura falhar, os números do banco aparecem como indisponíveis e
novas conquistas baseadas nesses dados não são concedidas. Uma leitura confirmada
sem registro de contador/saldo representa um usuário ainda sem pontuação/saldo
inicializado e aparece como zero, sem criar documentos de economia. Falhas de
gravação nunca são apresentadas como personalização salva.

## Arte e operação

As dez fontes SVG e PNGs transparentes estão em `assets/profile/badges/`.
`python scripts/build_profile_assets.py` reconstrói ambos a partir das mesmas
geometrias com Pillow. Montserrat e sua licença OFL estão em `assets/profile/fonts/`.
Não há chamada a uma IA ou serviço de imagem na execução do bot.

`python scripts/preview_profile.py --theme sakura` gera uma prévia fictícia em
`scripts/output/profile_preview.png`. Essa pasta já é ignorada pelo Git. O
renderer recebe somente bytes de avatar obtidos do Asset do Discord, limita
tamanho e dimensões e usa uma imagem padrão quando o avatar não puder ser lido.
Não aceita URL de imagem, upload de fundo ou caminho arbitrário pelo comando.

Implante o código e toda a pasta `assets/profile/`, mantenha acesso ao MongoDB e
os intents já usados pelo bot e execute `!sync` com uma conta autorizada em cada
servidor. Não há token, variável de ambiente ou dependência nova. Este PR não
executa deploy nem sincroniza comandos na produção.

Logs principais: `profile_rendered` (latência e disponibilidade),
`profile_failed`/`profile_delivery_failed` (tipo de erro sem texto privado),
`profile_achievements_observed` (quantidade e confirmação de gravação) e
`profile_event_awards_saved`/`profile_event_awards_incomplete` (vitórias).
As requisições de cartão usam `request_id` para correlação. Datas de desbloqueio
significam primeira observação confirmada, não a data histórica reconstruída.
